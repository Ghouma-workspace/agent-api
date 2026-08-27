"""Section 6 tests — CircuitBreaker state machine.

All three transition paths are covered:
  CLOSED → OPEN  (via failure_threshold consecutive failures)
  OPEN   → HALF_OPEN  (after recovery_timeout elapses)
  HALF_OPEN → CLOSED  (via success_threshold consecutive successes)
  HALF_OPEN → OPEN    (on any failure during probe)

Pure unit tests: fake Redis, no network.
"""

from __future__ import annotations

import pytest

from app.domain.exceptions.base import ToolExecutionError
from app.infrastructure.tools.circuit_breaker import CircuitBreaker, CircuitState

# ---------------------------------------------------------------------------
# Minimal in-memory Redis fake (get/set only — circuit breaker doesn't use
# sorted sets)
# ---------------------------------------------------------------------------


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str) -> None:
        self._store[key] = value

    def pipeline(self):
        return self  # not used by CircuitBreaker


# ---------------------------------------------------------------------------
# Coroutine helpers
# ---------------------------------------------------------------------------


async def _ok():
    return "result"


async def _fail():
    raise RuntimeError("tool error")


# ---------------------------------------------------------------------------
# CLOSED → OPEN
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_closed_to_open_after_failure_threshold():
    """After failure_threshold=3 consecutive failures the circuit opens."""
    redis = FakeRedis()
    cb = CircuitBreaker(redis, failure_threshold=3, recovery_timeout=60, success_threshold=2)

    # Failures 1 and 2 — circuit stays CLOSED, ToolExecutionError is raised but circuit stays
    for _ in range(2):
        with pytest.raises(ToolExecutionError):
            await cb.call("github", _fail())

    state = await cb._get_state("github")
    assert state == CircuitState.CLOSED

    # Failure 3 — trips the circuit to OPEN
    with pytest.raises(ToolExecutionError):
        await cb.call("github", _fail())

    state = await cb._get_state("github")
    assert state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_open_circuit_raises_immediately_without_calling_coro():
    """When OPEN the circuit must fail fast without awaiting the coroutine."""
    redis = FakeRedis()
    cb = CircuitBreaker(redis, failure_threshold=1, recovery_timeout=9999, success_threshold=2)

    # Trip to OPEN
    with pytest.raises(ToolExecutionError):
        await cb.call("github", _fail())

    # Now in OPEN — next call should fail fast (retryable=False)
    called = []

    async def _probe():
        called.append(True)
        return "ok"

    with pytest.raises(ToolExecutionError) as exc_info:
        await cb.call("github", _probe())

    assert exc_info.value.retryable is False
    assert called == []  # coroutine was never awaited


# ---------------------------------------------------------------------------
# OPEN → HALF_OPEN
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_transitions_to_half_open_after_recovery_timeout():
    """After recovery_timeout elapses, the circuit moves to HALF_OPEN on next call."""
    redis = FakeRedis()
    cb = CircuitBreaker(redis, failure_threshold=1, recovery_timeout=0, success_threshold=2)

    # Trip to OPEN
    with pytest.raises(ToolExecutionError):
        await cb.call("github", _fail())

    # recovery_timeout=0 → already elapsed; next call should probe
    result = await cb.call("github", _ok())
    assert result == "result"

    # After one success in HALF_OPEN, state is still HALF_OPEN (success_threshold=2)
    state = await cb._get_state("github")
    assert state == CircuitState.HALF_OPEN


# ---------------------------------------------------------------------------
# HALF_OPEN → CLOSED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_half_open_to_closed_after_success_threshold():
    """success_threshold=2 consecutive successes in HALF_OPEN should close the circuit."""
    redis = FakeRedis()
    cb = CircuitBreaker(redis, failure_threshold=1, recovery_timeout=0, success_threshold=2)

    # Trip to OPEN, then recovery_timeout=0 means we go to HALF_OPEN on next call
    with pytest.raises(ToolExecutionError):
        await cb.call("github", _fail())

    # Success 1 in HALF_OPEN
    await cb.call("github", _ok())
    assert await cb._get_state("github") == CircuitState.HALF_OPEN

    # Success 2 → CLOSED
    await cb.call("github", _ok())
    assert await cb._get_state("github") == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# HALF_OPEN → OPEN (on failure during probe)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_half_open_to_open_on_failure():
    """A failure during the HALF_OPEN probe immediately re-opens the circuit."""
    redis = FakeRedis()
    cb = CircuitBreaker(redis, failure_threshold=1, recovery_timeout=0, success_threshold=2)

    # Trip to OPEN
    with pytest.raises(ToolExecutionError):
        await cb.call("github", _fail())

    # recovery_timeout=0 → HALF_OPEN probe allowed through, but it fails
    with pytest.raises(ToolExecutionError):
        await cb.call("github", _fail())

    assert await cb._get_state("github") == CircuitState.OPEN


# ---------------------------------------------------------------------------
# Success resets failure counter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_resets_failure_counter():
    """A successful call in CLOSED resets the consecutive failure count."""
    redis = FakeRedis()
    cb = CircuitBreaker(redis, failure_threshold=3, recovery_timeout=60, success_threshold=2)

    # 2 failures
    for _ in range(2):
        with pytest.raises(ToolExecutionError):
            await cb.call("github", _fail())

    # 1 success — resets counter
    await cb.call("github", _ok())

    # Now need 3 more failures to open
    for _ in range(2):
        with pytest.raises(ToolExecutionError):
            await cb.call("github", _fail())

    # Still CLOSED (only 2 failures after reset)
    assert await cb._get_state("github") == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_status_returns_closed_for_fresh_tool():
    cb = CircuitBreaker(FakeRedis(), failure_threshold=5, recovery_timeout=60, success_threshold=2)
    status = await cb.get_status("weather")
    assert status["state"] == "closed"
    assert status["tool_name"] == "weather"


# ---------------------------------------------------------------------------
# Redis unavailable → fail-open
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_circuit_breaker_fail_open_on_redis_error():
    """If Redis is unavailable, calls must pass through (fail-open)."""

    class BrokenRedis:
        async def get(self, key):
            raise ConnectionError("Redis is down")

        async def set(self, key, value):
            raise ConnectionError("Redis is down")

    cb = CircuitBreaker(BrokenRedis(), failure_threshold=1, recovery_timeout=60, success_threshold=2)
    # Should succeed despite Redis being broken
    result = await cb.call("github", _ok())
    assert result == "result"
