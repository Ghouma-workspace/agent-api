"""Per-tool circuit breaker with Redis-backed state.

States: CLOSED (normal) → OPEN (fail-fast) → HALF_OPEN (probe) → CLOSED or OPEN.

Redis keys:
  circuit:{tool_name}:state        — "closed" | "open" | "half_open"
  circuit:{tool_name}:failures     — consecutive failure count (int)
  circuit:{tool_name}:successes    — consecutive successes in HALF_OPEN (int)
  circuit:{tool_name}:opened_at    — epoch timestamp when circuit opened (float)

All transitions update the circuit_breaker_state Gauge metric.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable
from enum import StrEnum

import structlog
from redis.asyncio import Redis

from app.domain.exceptions.base import ToolExecutionError
from app.infrastructure.observability.metrics import CIRCUIT_BREAKER_STATE

logger = structlog.get_logger()

_STATE_GAUGE_VALUES = {"closed": 0, "half_open": 1, "open": 2}


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Shared circuit breaker instance — one state machine per tool, stored in Redis."""

    def __init__(
        self,
        redis: Redis,
        *,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        success_threshold: int = 2,
    ) -> None:
        self._redis = redis
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._success_threshold = success_threshold

    # ------------------------------------------------------------------
    # Redis key helpers
    # ------------------------------------------------------------------

    def _key(self, tool_name: str, suffix: str) -> str:
        return f"circuit:{tool_name}:{suffix}"

    async def _get_state(self, tool_name: str) -> CircuitState:
        try:
            raw = await self._redis.get(self._key(tool_name, "state"))
            return CircuitState(raw) if raw else CircuitState.CLOSED
        except Exception:  # noqa: BLE001
            return CircuitState.CLOSED  # fail-open if Redis is unavailable

    async def _set_state(self, tool_name: str, state: CircuitState) -> None:
        try:
            await self._redis.set(self._key(tool_name, "state"), state.value)
            CIRCUIT_BREAKER_STATE.labels(tool_name=tool_name).set(
                _STATE_GAUGE_VALUES[state.value]
            )
            logger.info("circuit_breaker_state_change", tool=tool_name, state=state.value)
        except Exception as exc:  # noqa: BLE001
            logger.warning("circuit_breaker_redis_error", tool=tool_name, error=str(exc))

    async def _get_int(self, tool_name: str, suffix: str) -> int:
        try:
            raw = await self._redis.get(self._key(tool_name, suffix))
            return int(raw) if raw else 0
        except Exception:  # noqa: BLE001
            return 0

    async def _set_int(self, tool_name: str, suffix: str, value: int) -> None:
        try:
            await self._redis.set(self._key(tool_name, suffix), str(value))
        except Exception:  # noqa: BLE001
            pass

    async def _get_float(self, tool_name: str, suffix: str) -> float:
        try:
            raw = await self._redis.get(self._key(tool_name, suffix))
            return float(raw) if raw else 0.0
        except Exception:  # noqa: BLE001
            return 0.0

    async def _set_float(self, tool_name: str, suffix: str, value: float) -> None:
        try:
            await self._redis.set(self._key(tool_name, suffix), str(value))
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_status(self, tool_name: str) -> dict:
        """Return a status snapshot for the /api/tools/circuit-status endpoint."""
        state = await self._get_state(tool_name)
        failures = await self._get_int(tool_name, "failures")
        successes = await self._get_int(tool_name, "successes")
        opened_at = await self._get_float(tool_name, "opened_at")
        return {
            "tool_name": tool_name,
            "state": state.value,
            "failures": failures,
            "successes": successes,
            "opened_at": opened_at,
        }

    async def call(self, tool_name: str, coro: Awaitable) -> object:
        """Execute ``coro`` through the circuit breaker.

        Raises ToolExecutionError(retryable=False) immediately when OPEN.
        On HALF_OPEN, a single probe is allowed through.
        Records success/failure and transitions state accordingly.
        """
        state = await self._get_state(tool_name)

        if state == CircuitState.OPEN:
            # Check if recovery_timeout has elapsed — if so, move to HALF_OPEN
            opened_at = await self._get_float(tool_name, "opened_at")
            if time.time() - opened_at >= self._recovery_timeout:
                await self._set_state(tool_name, CircuitState.HALF_OPEN)
                await self._set_int(tool_name, "successes", 0)
                state = CircuitState.HALF_OPEN
                logger.info("circuit_breaker_half_open", tool=tool_name)
            else:
                raise ToolExecutionError(
                    tool_name,
                    "Circuit breaker is OPEN — failing fast",
                    retryable=False,
                )

        try:
            result = await coro
            await self._on_success(tool_name, state)
            return result
        except ToolExecutionError:
            raise  # preserve existing retryable flag
        except Exception as exc:
            await self._on_failure(tool_name, state)
            raise ToolExecutionError(tool_name, str(exc), retryable=True) from exc

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    async def _on_success(self, tool_name: str, prev_state: CircuitState) -> None:
        if prev_state == CircuitState.HALF_OPEN:
            successes = await self._get_int(tool_name, "successes") + 1
            await self._set_int(tool_name, "successes", successes)
            if successes >= self._success_threshold:
                # Enough consecutive successes → CLOSED
                await self._set_state(tool_name, CircuitState.CLOSED)
                await self._set_int(tool_name, "failures", 0)
                await self._set_int(tool_name, "successes", 0)
        else:
            # CLOSED: reset failure counter on success
            await self._set_int(tool_name, "failures", 0)

    async def _on_failure(self, tool_name: str, prev_state: CircuitState) -> None:
        if prev_state == CircuitState.HALF_OPEN:
            # Probe failed → back to OPEN immediately
            await self._set_state(tool_name, CircuitState.OPEN)
            await self._set_float(tool_name, "opened_at", time.time())
            await self._set_int(tool_name, "successes", 0)
        else:
            # CLOSED: increment failure counter
            failures = await self._get_int(tool_name, "failures") + 1
            await self._set_int(tool_name, "failures", failures)
            if failures >= self._failure_threshold:
                await self._set_state(tool_name, CircuitState.OPEN)
                await self._set_float(tool_name, "opened_at", time.time())
                await self._set_int(tool_name, "failures", 0)
