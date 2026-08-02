"""Content filter node — first node in the graph.

Pure Python string matching, zero LLM calls. Detects prompt injection patterns and
sets draft_response + error so the graph short-circuits to END.

Security logging note: the *triggering pattern* is logged but NOT the full user
message — it may contain sensitive data (credentials, PII) that must not appear in
structured logs.
"""

from __future__ import annotations

import re

import structlog

from app.application.agent.state import AgentState
from app.infrastructure.observability.agent_tracing import traced_node
from app.infrastructure.observability.metrics import CONTENT_FILTER_TRIGGERS_TOTAL

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Injection patterns — case-insensitive substring matches
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: list[str] = [
    "ignore previous instructions",
    "ignore all instructions",
    "you are now",
    "new persona",
    "jailbreak",
    "disregard your",
    "system:",
    "###instruction",
    "<|im_start|>",
]

_COMPILED_PATTERNS = [re.compile(re.escape(p), re.IGNORECASE) for p in _INJECTION_PATTERNS]

_REFUSAL_MESSAGE = (
    "I'm sorry, but I can't process that request. "
    "Please rephrase your message and try again."
)


def _detect_injection(text: str) -> str | None:
    """Return the first matching pattern string, or None if clean."""
    for pattern, raw in zip(_COMPILED_PATTERNS, _INJECTION_PATTERNS):
        if pattern.search(text):
            return raw
    return None


@traced_node("content_filter")
async def content_filter(state: AgentState) -> dict:
    """Check the last user message for prompt injection patterns.

    Returns immediately with a refusal if triggered; otherwise returns an empty
    dict so the graph proceeds to the planner.
    """
    last_message = state.messages[-1].content if state.messages else ""
    triggered_pattern = _detect_injection(last_message)

    if triggered_pattern is None:
        return {}  # clean — proceed to planner

    # Log the pattern but NOT the user message
    logger.warning(
        "content_filter_triggered",
        triggered_pattern=triggered_pattern,
        user_id=str(state.user_id),
        conversation_id=str(state.conversation_id),
        trace_id=state.trace_id,
    )
    CONTENT_FILTER_TRIGGERS_TOTAL.inc()

    return {
        "draft_response": _REFUSAL_MESSAGE,
        "error": "content_filter_triggered",
    }
