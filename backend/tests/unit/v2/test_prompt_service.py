"""Section 2 tests — PromptService graceful degradation.

Pure unit tests: no I/O, no DB, no Redis. Langfuse client is stubbed.
"""

from __future__ import annotations

import pytest

from app.application.services.prompt_service import PromptService


# ---------------------------------------------------------------------------
# Fake Langfuse client
# ---------------------------------------------------------------------------


class FakeLangfusePrompt:
    def __init__(self, text: str) -> None:
        self._text = text

    def compile(self) -> str:
        return self._text


class FakeLangfuseClient:
    def __init__(self, prompts: dict[str, str], *, raise_on: str | None = None) -> None:
        self._prompts = prompts
        self._raise_on = raise_on

    def get_prompt(self, name: str, label: str | None = None) -> FakeLangfusePrompt:
        if self._raise_on and name == self._raise_on:
            raise RuntimeError("Langfuse unreachable")
        if name not in self._prompts:
            raise KeyError(f"Prompt '{name}' not found")
        return FakeLangfusePrompt(self._prompts[name])


# ---------------------------------------------------------------------------
# Happy path — returns Langfuse prompt text
# ---------------------------------------------------------------------------


def test_prompt_service_returns_langfuse_text():
    client = FakeLangfuseClient({"planner_system": "Langfuse version of prompt"})
    svc = PromptService(client, enable=True)

    result = svc.get("planner_system", fallback="fallback text")
    assert result == "Langfuse version of prompt"


# ---------------------------------------------------------------------------
# Fallback cases
# ---------------------------------------------------------------------------


def test_prompt_service_falls_back_when_prompt_missing():
    client = FakeLangfuseClient({})  # empty — no prompts registered
    svc = PromptService(client, enable=True)

    result = svc.get("planner_system", fallback="FALLBACK")
    assert result == "FALLBACK"


def test_prompt_service_falls_back_when_langfuse_unreachable():
    client = FakeLangfuseClient({}, raise_on="planner_system")
    svc = PromptService(client, enable=True)

    result = svc.get("planner_system", fallback="FALLBACK")
    assert result == "FALLBACK"


def test_prompt_service_falls_back_when_client_is_none():
    svc = PromptService(None, enable=True)

    result = svc.get("planner_system", fallback="FALLBACK")
    assert result == "FALLBACK"


def test_prompt_service_disabled_always_returns_fallback_without_calling_client():
    """When langfuse_enable_prompt_management=False, client is never called."""

    class ShouldNotBeCalled:
        def get_prompt(self, name: str):
            raise AssertionError("Should not be called when disabled")

    svc = PromptService(ShouldNotBeCalled(), enable=False)
    result = svc.get("planner_system", fallback="LOCAL_FALLBACK")
    assert result == "LOCAL_FALLBACK"


# ---------------------------------------------------------------------------
# Never raises
# ---------------------------------------------------------------------------


def test_prompt_service_never_raises_on_any_exception():
    """Any exception from Langfuse must be caught — system must not crash."""

    class BrokenClient:
        def get_prompt(self, name: str, label: str | None = None):
            raise Exception("Totally unexpected error")  # noqa: TRY002

    svc = PromptService(BrokenClient(), enable=True)
    # Should not raise
    result = svc.get("anything", fallback="safe")
    assert result == "safe"
