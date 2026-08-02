"""Section 1 tests — structured planner output with Pydantic validation.

All tests are pure unit tests: no I/O, no DB, no Redis. Uses FakeLLMProvider.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from app.application.agent.nodes.planner import PlannerOutput, make_planner
from app.application.agent.state import AgentState
from app.domain.entities.chat import ChatMessage, LLMResponse, MessageRole
from app.domain.exceptions.base import ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(content: str = "hello") -> AgentState:
    return AgentState(
        conversation_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        trace_id="test-trace",
        messages=[
            ChatMessage(
                id=uuid.uuid4(),
                conversation_id=uuid.uuid4(),
                role=MessageRole.USER,
                content=content,
                created_at=datetime.now(UTC),
            )
        ],
    )


class FakeLLMProvider:
    """Returns canned LLMResponse objects without touching the network."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = responses
        self._calls = 0
        self.last_response_format: dict | None = None

    async def complete(self, messages, tools=None, response_format=None, **kwargs):
        self.last_response_format = response_format
        resp = self._responses[min(self._calls, len(self._responses) - 1)]
        self._calls += 1
        return resp

    async def stream(self, messages, tools=None, **kwargs):
        return  # not used in planner tests
        yield  # make it an async generator


class FakeToolRegistry:
    def list_llm_tools(self):
        return [
            {"function": {"name": "mock_api", "description": "A mock tool"}},
            {"function": {"name": "weather", "description": "Weather tool"}},
        ]

    def list_schemas(self):
        return self.list_llm_tools()


class NullPromptService:
    """Always returns the fallback — used in unit tests to avoid Langfuse."""

    def get(self, name: str, fallback: str) -> str:
        return fallback


# ---------------------------------------------------------------------------
# PlannerOutput validation
# ---------------------------------------------------------------------------


def test_planner_output_direct_answer():
    output = PlannerOutput.model_validate(
        {"needs_tool": False, "tool_name": None, "reasoning": "General knowledge question."}
    )
    assert output.needs_tool is False
    assert output.tool_name is None
    assert output.reasoning == "General knowledge question."


def test_planner_output_tool_call():
    output = PlannerOutput.model_validate(
        {"needs_tool": True, "tool_name": "weather", "reasoning": "Real-time data needed."}
    )
    assert output.needs_tool is True
    assert output.tool_name == "weather"


def test_planner_output_missing_field_raises():
    with pytest.raises(Exception):
        PlannerOutput.model_validate({"tool_name": None})  # missing needs_tool


# ---------------------------------------------------------------------------
# make_planner: direct-answer path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_direct_answer_returns_no_tool():
    llm = FakeLLMProvider(
        [LLMResponse(content=json.dumps({"needs_tool": False, "tool_name": None, "reasoning": "I know this."}))]
    )
    registry = FakeToolRegistry()
    planner = make_planner(llm, registry, NullPromptService())

    state = _make_state("what is 2+2?")
    result = await planner(state)

    assert result["needs_tool"] is False
    assert result.get("selected_tool") is None
    assert result["reasoning"] == "I know this."


# ---------------------------------------------------------------------------
# make_planner: tool path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_tool_path_sets_selected_tool():
    llm = FakeLLMProvider(
        [LLMResponse(content=json.dumps({"needs_tool": True, "tool_name": "mock_api", "reasoning": "Needs external call."}))]
    )
    registry = FakeToolRegistry()
    planner = make_planner(llm, registry, NullPromptService())

    state = _make_state("call the mock tool")
    result = await planner(state)

    assert result["needs_tool"] is True
    assert result["selected_tool"] is not None
    assert result["selected_tool"].tool_name == "mock_api"
    assert result["reasoning"] == "Needs external call."


# ---------------------------------------------------------------------------
# make_planner: malformed JSON → ValidationError (not silent fallthrough)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_malformed_json_raises_validation_error():
    """If the LLM returns non-JSON, planner must raise domain ValidationError — never silently pass."""
    llm = FakeLLMProvider([LLMResponse(content="this is not json at all")])
    registry = FakeToolRegistry()
    planner = make_planner(llm, registry, NullPromptService())

    state = _make_state("hello")
    with pytest.raises(ValidationError) as exc_info:
        await planner(state)

    assert "json_parse_failed" in exc_info.value.errors


@pytest.mark.asyncio
async def test_planner_invalid_schema_raises_validation_error():
    """If JSON parses but doesn't match PlannerOutput schema, ValidationError is raised."""
    llm = FakeLLMProvider([LLMResponse(content=json.dumps({"wrong_key": True}))])
    registry = FakeToolRegistry()
    planner = make_planner(llm, registry, NullPromptService())

    state = _make_state("hello")
    with pytest.raises(ValidationError) as exc_info:
        await planner(state)

    assert "schema_validation_failed" in exc_info.value.errors


# ---------------------------------------------------------------------------
# make_planner: response_format is passed as json_object
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_passes_json_response_format_to_llm():
    """Planner must pass response_format={'type': 'json_object'} to the LLM."""
    llm = FakeLLMProvider(
        [LLMResponse(content=json.dumps({"needs_tool": False, "tool_name": None, "reasoning": "x"}))]
    )
    registry = FakeToolRegistry()
    planner = make_planner(llm, registry, NullPromptService())

    await planner(_make_state("hi"))

    assert llm.last_response_format == {"type": "json_object"}


# ---------------------------------------------------------------------------
# AgentState carries reasoning field
# ---------------------------------------------------------------------------


def test_agent_state_has_reasoning_field():
    state = AgentState(
        conversation_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        trace_id="t",
        messages=[],
        reasoning="because of X",
    )
    assert state.reasoning == "because of X"


def test_agent_state_reasoning_defaults_to_empty():
    state = AgentState(
        conversation_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        trace_id="t",
        messages=[],
    )
    assert state.reasoning == ""
