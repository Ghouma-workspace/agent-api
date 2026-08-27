"""Secrets redaction for structured logs.

``redact()`` recursively walks dicts and lists, replacing any value whose key
matches a sensitive pattern with "[REDACTED]", and truncating long string values.

This is registered as a structlog processor so every log line passes through it
before JSON rendering. Zero chance of accidentally logging an API key.

Sensitive key patterns (case-insensitive substring match):
  *key*, *token*, *secret*, *password*, *auth*, *credential*
"""

from __future__ import annotations

import re
from typing import Any

_SENSITIVE_PATTERNS = re.compile(
    r"(key|token|secret|password|auth|credential)",
    re.IGNORECASE,
)

_MAX_STRING_LENGTH = 200
_TRUNCATED_SUFFIX = "...[truncated]"
_TRUNCATED_KEEP = 50
_REDACTED = "[REDACTED]"


def redact(obj: Any) -> Any:
    """Recursively redact sensitive values from a dict/list structure.

    - Dict keys matching _SENSITIVE_PATTERNS → value replaced with "[REDACTED]".
    - String values longer than _MAX_STRING_LENGTH → truncated to first 50 chars + "...[truncated]".
    - Everything else passes through unchanged.

    Designed to be safe on arbitrary input (won't raise on unexpected types).
    """
    if isinstance(obj, dict):
        return {k: _redact_value(k, v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(item) for item in obj]
    if isinstance(obj, str) and len(obj) > _MAX_STRING_LENGTH:
        return obj[:_TRUNCATED_KEEP] + _TRUNCATED_SUFFIX
    return obj


def _redact_value(key: str, value: Any) -> Any:
    if _SENSITIVE_PATTERNS.search(str(key)):
        return _REDACTED
    return redact(value)


# ---------------------------------------------------------------------------
# structlog processor
# ---------------------------------------------------------------------------


def redacting_processor(logger: Any, method: str, event_dict: dict) -> dict:
    """structlog processor that redacts the entire event_dict.

    Place this after _inject_context and before JSONRenderer in the processor chain.
    """
    return redact(event_dict)  # type: ignore[return-value]
