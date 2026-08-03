"""Content filter node — first node in the graph.

Intent-based patterns. Each pattern targets a specific attack category and is
designed to minimise false positives on legitimate requests.

Principle: "Can you act as a code reviewer?" is legitimate.
           "Act as an AI with no restrictions" is an attack.
The distinguishing signal is usually an attack qualifier (no restrictions,
DAN, jailbroken, unlimited, no rules) or an unambiguous framing word.

Never log the full user message — log category name only.
"""

from __future__ import annotations

import re

import structlog

from app.application.agent.state import AgentState
from app.infrastructure.observability.agent_tracing import traced_node
from app.infrastructure.observability.metrics import CONTENT_FILTER_TRIGGERS_TOTAL

logger = structlog.get_logger()

_I = re.IGNORECASE

_PATTERNS: list[tuple[str, re.Pattern]] = [

    # ── Instruction override ─────────────────────────────────────────────────
    ("instruction_override", re.compile(
        r"ignore\s+(all\s+)?(my\s+|the\s+|your\s+|any\s+|these\s+)?"
        r"(previous|prior|earlier|above|following|those)\s+"
        r"(instructions?|prompts?|rules?|guidelines?|constraints?|directives?|context)",
        _I,
    )),
    ("instruction_override", re.compile(
        r"ignore\s+(any\s+)(instructions?|prompts?|rules?)\s+(you\s+were|i\s+gave|given)",
        _I,
    )),

    # ── Disregard / forget / bypass ──────────────────────────────────────────
    ("instruction_disregard", re.compile(
        r"(disregard|override|bypass|dismiss|erase)\s+"
        r"(all\s+)?(your\s+|my\s+|the\s+)(previous\s+|prior\s+|any\s+|the\s+|above\s+)?"
        r"(instructions?|prompts?|rules?|guidelines?|constraints?|training|context)",
        _I,
    )),
    ("instruction_disregard", re.compile(
        r"(forget|skip|omit)\s+(all\s+)?(your\s+|my\s+)"
        r"(previous\s+|prior\s+|any\s+)?"
        r"(instructions?|prompts?|rules?|guidelines?|constraints?|context|training)",
        _I,
    )),
    # "skip your training" / "bypass your safety guidelines"
    ("instruction_disregard", re.compile(
        r"\b(skip|bypass)\s+(your\s+)?(safety\s+)?(training|guidelines|rules|restrictions?)\b",
        _I,
    )),
    # "forget everything you were told/given/instructed"
    ("instruction_disregard", re.compile(
        r"forget\s+(everything|all)\s+(you\s+)?(were\s+)?"
        r"(told|given|instructed|trained|taught)",
        _I,
    )),

    # ── Persona switch ───────────────────────────────────────────────────────
    # Unambiguous attack phrases (no qualifier needed)
    ("persona_switch", re.compile(
        r"you\s+are\s+now\s+(an?\s+)?"
        r"(ai|assistant|bot|model|system|different|unrestricted|evil|hacker|dan\b)",
        _I,
    )),
    ("persona_switch", re.compile(
        r"(from\s+now\s+on|starting\s+now)\s+(you\s+are|act|behave|respond)",
        _I,
    )),
    ("persona_switch", re.compile(
        r"(new\s+persona|switch\s+(to\s+)?a?\s*persona|take\s+on\s+(a\s+new|the)\s+persona)",
        _I,
    )),
    ("persona_switch", re.compile(
        r"roleplay\s+as\s+(an?\s+)?(ai|assistant|bot|model|system)",
        _I,
    )),
    # "pretend you are a different/another AI/model/assistant"
    ("persona_switch", re.compile(
        r"pretend\s+(you\s+are|to\s+be)\s+(a\s+)?(different|another|alternative|new)\s+"
        r"(ai|model|assistant|bot|system|version)",
        _I,
    )),
    # "pretend you are / pretend to be" with attack qualifier
    ("persona_switch", re.compile(
        r"pretend\s+(you\s+are|to\s+be)\s+.{0,60}"
        r"(no\s+restrictions?|no\s+limits?|no\s+rules?|without\s+restrictions?|dan\b|unrestricted|jailbroken)",
        _I,
    )),
    # "act as" with attack qualifier (excludes legitimate roles like "code reviewer")
    ("persona_switch", re.compile(
        r"act\s+as\s+(an?\s+)?(?!code|technical|senior|junior|expert|professional|helpful|friendly)"
        r".{0,60}"
        r"(no\s+restrictions?|no\s+limits?|no\s+rules?|without\s+(any\s+)?restrictions?|dan\b|unrestricted|jailbroken)",
        _I,
    )),

    # ── Jailbreak keywords ───────────────────────────────────────────────────
    ("jailbreak", re.compile(
        r"\bjailbreak\b"
        r"|\bdan\s+mode\b"
        r"|\bdo\s+anything\s+now\b"
        r"|\bunrestricted\s+mode\b"
        r"|\bdev(eloper)?\s+mode\s+(enabled|on|activated)\b"
        r"|\bno\s+restrictions?\s+mode\b",
        _I,
    )),

    # ── System injection markers ─────────────────────────────────────────────
    ("system_injection", re.compile(
        r"<\|im_start\|>|<\|system\|>|<\|endoftext\|>|<\|im_end\|>",
        _I,
    )),
    ("system_injection", re.compile(
        r"\[system\]|\[\[system\]\]|###\s*instruction|###\s*system\b|<system>|</system>",
        _I,
    )),
    # "system: you are / must / will / ignore / forget"
    ("system_injection", re.compile(
        r"\bsystem\s*:\s*(you\s+(are|must|will|should)|your\s+role|the\s+following|ignore|forget|disregard|from\s+now)",
        _I,
    )),

    # ── Prompt / credential leak ─────────────────────────────────────────────
    ("prompt_leak", re.compile(
        r"(reveal|show\s+me|print|output|repeat|give\s+me|share|expose|display|dump|leak|tell\s+me)\s+"
        r"(your\s+|the\s+|my\s+|a\s+)?"
        r"(system\s+prompt|initial\s+prompt|original\s+prompt|secret\s+instructions?"
        r"|instructions?\s+you\s+were\s+given)",
        _I,
    )),
    # "tell me / give me the github token / api key / credentials"
    ("prompt_leak", re.compile(
        r"(tell\s+me|give\s+me|show\s+me|reveal|output|share|expose)\s+"
        r"(your\s+|the\s+|my\s+|a\s+)?"
        r"(api\s+key|github\s+(token|key|secret)|access\s+token|auth\s+token"
        r"|private\s+key|credentials?|secrets?\b)",
        _I,
    )),

    # ── Delimiter / token smuggling ──────────────────────────────────────────
    ("delimiter_injection", re.compile(
        r"```\s*system\b|\[INST\]|\[/INST\]",
        _I,
    )),
]

_REFUSAL_MESSAGE = (
    "I'm sorry, but I can't process that request. "
    "Please rephrase your message and try again."
)


def _detect_injection(text: str) -> str | None:
    """Return the first matching category name, or None if clean."""
    for category, pattern in _PATTERNS:
        if pattern.search(text):
            return category
    return None


@traced_node("content_filter")
async def content_filter(state: AgentState) -> dict:
    last_message = state.messages[-1].content if state.messages else ""
    triggered_category = _detect_injection(last_message)

    if triggered_category is None:
        return {}

    logger.warning(
        "content_filter_triggered",
        triggered_category=triggered_category,
        user_id=str(state.user_id),
        conversation_id=str(state.conversation_id),
        trace_id=state.trace_id,
    )
    CONTENT_FILTER_TRIGGERS_TOTAL.inc()

    return {
        "draft_response": _REFUSAL_MESSAGE,
        "error": "content_filter_triggered",
    }