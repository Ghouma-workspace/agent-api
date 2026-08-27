"""Section 9 tests — secrets redaction.

Pure unit tests of the redact() function and the redacting_processor.
"""

from __future__ import annotations

import pytest

from app.infrastructure.observability.redaction import (
    _REDACTED,
    _SENSITIVE_PATTERNS,
    redact,
    redacting_processor,
)


# ---------------------------------------------------------------------------
# Sensitive key detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "API_KEY",
        "github_token",
        "access_token",
        "secret",
        "SECRET_KEY",
        "password",
        "hashed_password",
        "auth_header",
        "Authorization",
        "credential",
        "aws_credential",
    ],
)
def test_sensitive_key_is_detected(key: str):
    assert _SENSITIVE_PATTERNS.search(key) is not None


@pytest.mark.parametrize(
    "key",
    ["city", "user_id", "tool_name", "conversation_id", "latency_ms", "model", "timestamp"],
)
def test_safe_key_is_not_detected(key: str):
    assert _SENSITIVE_PATTERNS.search(key) is None


# ---------------------------------------------------------------------------
# redact() — flat dict
# ---------------------------------------------------------------------------


def test_redact_replaces_sensitive_value():
    result = redact({"api_key": "sk-abc123", "city": "London"})
    assert result["api_key"] == _REDACTED
    assert result["city"] == "London"


def test_redact_replaces_password():
    result = redact({"password": "super-secret", "email": "user@example.com"})
    assert result["password"] == _REDACTED
    assert result["email"] == "user@example.com"


def test_redact_replaces_token():
    result = redact({"access_token": "tok_123", "user_id": "abc"})
    assert result["access_token"] == _REDACTED
    assert result["user_id"] == "abc"


def test_redact_handles_none_value():
    result = redact({"api_key": None})
    assert result["api_key"] == _REDACTED  # key is sensitive regardless of value


def test_redact_leaves_safe_values_untouched():
    obj = {"model": "llama-3", "tool_name": "weather", "success": True, "latency_ms": 42.5}
    assert redact(obj) == obj


# ---------------------------------------------------------------------------
# redact() — nested dicts
# ---------------------------------------------------------------------------


def test_redact_nested_dict():
    result = redact({"config": {"api_key": "secret!", "model": "llama"}})
    assert result["config"]["api_key"] == _REDACTED
    assert result["config"]["model"] == "llama"


def test_redact_deeply_nested():
    result = redact({"a": {"b": {"c": {"password": "pw", "x": 1}}}})
    assert result["a"]["b"]["c"]["password"] == _REDACTED
    assert result["a"]["b"]["c"]["x"] == 1


# ---------------------------------------------------------------------------
# redact() — lists
# ---------------------------------------------------------------------------


def test_redact_list_of_dicts():
    result = redact([{"api_key": "k1"}, {"city": "Paris"}])
    assert result[0]["api_key"] == _REDACTED
    assert result[1]["city"] == "Paris"


def test_redact_list_with_strings():
    result = redact(["hello", "world"])
    assert result == ["hello", "world"]


# ---------------------------------------------------------------------------
# String truncation
# ---------------------------------------------------------------------------


def test_long_string_is_truncated():
    long_str = "a" * 300
    result = redact({"message": long_str})
    assert result["message"].endswith("...[truncated]")
    assert len(result["message"]) < 300


def test_safe_length_string_is_not_truncated():
    short_str = "a" * 100
    result = redact({"message": short_str})
    assert result["message"] == short_str


def test_truncated_string_keeps_first_50_chars():
    long_str = "x" * 50 + "y" * 300
    result = redact({"message": long_str})
    assert result["message"].startswith("x" * 50)
    assert "y" not in result["message"]


# ---------------------------------------------------------------------------
# redact() — non-dict/list passthrough
# ---------------------------------------------------------------------------


def test_redact_int_passthrough():
    assert redact(42) == 42


def test_redact_none_passthrough():
    assert redact(None) is None


def test_redact_bool_passthrough():
    assert redact(True) is True


# ---------------------------------------------------------------------------
# redacting_processor (structlog integration)
# ---------------------------------------------------------------------------


def test_redacting_processor_redacts_event_dict():
    event_dict = {"event": "login", "password": "p@ssw0rd", "user": "alice"}
    result = redacting_processor(None, "info", event_dict)
    assert result["password"] == _REDACTED
    assert result["user"] == "alice"
    assert result["event"] == "login"


def test_redacting_processor_returns_dict():
    result = redacting_processor(None, "info", {"x": 1})
    assert isinstance(result, dict)
