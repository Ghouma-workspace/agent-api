"""Tests for traced_node()'s Langfuse generation/span kwargs construction.

Covers the ruff C408 fix (agent_tracing.py): `dict(...)` was rewritten as a
dict literal for `generation_kwargs`. This test locks in that the resulting
kwargs are unchanged in shape — including the conditional `prompt` key that's
only added when the node stashed a `_langfuse_prompt` on state, which is the
part most likely to regress in a careless rewrite — and that `calls_llm=False`
nodes still go through `.span()` rather than `.generation()`.

Pure unit tests: fake Langfuse trace/observation objects, no real Langfuse
client, no network.
"""

from __future__ import annotations

import uuid

import pytest

from app.application.agent.state import AgentState
from app.infrastructure.observability.agent_tracing import (
    set_current_langfuse_trace,
    traced_node,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeObservation:
    def __init__(self) -> None:
        self.ended = False
        self.end_kwargs: dict | None = None
        self.updated_kwargs: dict | None = None

    def update(self, **kwargs) -> None:
        self.updated_kwargs = kwargs

    def end(self, **kwargs) -> None:
        self.ended = True
        self.end_kwargs = kwargs


class FakeLangfuseTrace:
    """Captures the exact kwargs passed to .generation()/.span() so tests can
    assert on the dict-literal refactor without a real Langfuse client."""

    def __init__(self) -> None:
        self.generation_calls: list[dict] = []
        self.span_calls: list[dict] = []
        self.observations: list[FakeObservation] = []

    def generation(self, **kwargs) -> FakeObservation:
        self.generation_calls.append(kwargs)
        obs = FakeObservation()
        self.observations.append(obs)
        return obs

    def span(self, **kwargs) -> FakeObservation:
        self.span_calls.append(kwargs)
        obs = FakeObservation()
        self.observations.append(obs)
        return obs


def _make_state() -> AgentState:
    return AgentState(conversation_id=uuid.uuid4(), user_id=uuid.uuid4(), trace_id="test-trace")


@pytest.fixture(autouse=True)
def _reset_langfuse_trace_context():
    """traced_node reads a ContextVar — reset it around every test so state from
    one test never leaks into the next."""
    set_current_langfuse_trace(None)
    yield
    set_current_langfuse_trace(None)


# ---------------------------------------------------------------------------
# generation_kwargs shape (calls_llm=True path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generation_kwargs_has_expected_keys_without_prompt():
    fake_trace = FakeLangfuseTrace()
    set_current_langfuse_trace(fake_trace)

    @traced_node("planner", calls_llm=True)
    async def node(state: AgentState) -> dict:
        return {"draft_response": "ok"}

    await node(_make_state())

    assert len(fake_trace.generation_calls) == 1
    kwargs = fake_trace.generation_calls[0]
    assert kwargs.keys() == {"name", "model", "input"}
    assert kwargs["name"] == "planner"
    assert kwargs["model"] == "groq"


@pytest.mark.asyncio
async def test_generation_kwargs_includes_prompt_key_only_when_stashed_on_state():
    fake_trace = FakeLangfuseTrace()
    set_current_langfuse_trace(fake_trace)

    state = _make_state()
    state.__dict__["_langfuse_prompt"] = "prompt-object-v3"

    @traced_node("planner", calls_llm=True)
    async def node(s: AgentState) -> dict:
        return {"draft_response": "ok"}

    await node(state)

    kwargs = fake_trace.generation_calls[0]
    assert kwargs.keys() == {"name", "model", "input", "prompt"}
    assert kwargs["prompt"] == "prompt-object-v3"


@pytest.mark.asyncio
async def test_langfuse_prompt_is_cleared_from_state_after_the_node_runs():
    """So it doesn't leak into the next node's generation call."""
    fake_trace = FakeLangfuseTrace()
    set_current_langfuse_trace(fake_trace)

    state = _make_state()
    state.__dict__["_langfuse_prompt"] = "prompt-object-v3"

    @traced_node("planner", calls_llm=True)
    async def node(s: AgentState) -> dict:
        return {"draft_response": "ok"}

    await node(state)

    assert "_langfuse_prompt" not in state.__dict__


# ---------------------------------------------------------------------------
# Non-LLM nodes use .span(), never .generation()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_llm_node_uses_span_not_generation():
    fake_trace = FakeLangfuseTrace()
    set_current_langfuse_trace(fake_trace)

    @traced_node("tool_executor", calls_llm=False)
    async def node(state: AgentState) -> dict:
        return {}

    await node(_make_state())

    assert fake_trace.generation_calls == []
    assert len(fake_trace.span_calls) == 1
    assert fake_trace.span_calls[0] == {"name": "tool_executor", "input": {
        "last_message": None,
        "needs_tool": False,
        "selected_tool": None,
        "tool_result": None,
        "retry_count": 0,
        "validation_loop_count": 0,
    }}


# ---------------------------------------------------------------------------
# No Langfuse trace in context -> no observation calls at all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_langfuse_calls_when_no_trace_in_context():
    # _reset_langfuse_trace_context fixture already set the ContextVar to None
    @traced_node("planner", calls_llm=True)
    async def node(state: AgentState) -> dict:
        return {"draft_response": "ok"}

    result = await node(_make_state())
    assert result["draft_response"] == "ok"


# ---------------------------------------------------------------------------
# Observation is ended with error output on node failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generation_observation_ends_with_error_on_node_exception():
    fake_trace = FakeLangfuseTrace()
    set_current_langfuse_trace(fake_trace)

    @traced_node("tool_selector", calls_llm=True)
    async def node(state: AgentState) -> dict:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await node(_make_state())

    obs = fake_trace.observations[0]
    assert obs.ended is True
    assert obs.end_kwargs["output"] == {"error": "boom"}
    assert obs.end_kwargs["level"] == "ERROR"
