"""Tool executor node.

Execution order per call:
  1. Rate limiter check  (Section 5 — raises if limit exceeded)
  2. Cache lookup        (Section 4 — return cached result if hit)
  3. Circuit breaker     (Section 6 — fail-fast when OPEN)
  4. Actual tool call
  5. Cache write on success
"""

from __future__ import annotations

import time

import structlog

from app.application.agent.state import AgentState
from app.domain.entities.chat import ToolResult
from app.domain.exceptions.base import ToolExecutionError
from app.domain.providers.interfaces import ToolRegistry
from app.infrastructure.observability.agent_tracing import traced_node
from app.infrastructure.observability.metrics import (
    TOOL_EXECUTION_DURATION_SECONDS,
    TOOL_EXECUTIONS_TOTAL,
)
from app.infrastructure.observability.redaction import redact

logger = structlog.get_logger()


class SimpleToolContext:
    def __init__(self, user_id: str, conversation_id: str, trace_id: str) -> None:
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.trace_id = trace_id


def make_tool_executor(
    tool_registry: ToolRegistry,
    tool_cache=None,          # ToolResultCache | None
    tool_rate_limiter=None,   # ToolRateLimiter | None
    circuit_breaker=None,     # CircuitBreaker | None
    tool_cache_ttls: dict | None = None,
):
    @traced_node("tool_executor")
    async def tool_executor(state: AgentState) -> dict:
        assert state.selected_tool is not None
        tool_name = state.selected_tool.tool_name
        arguments = state.selected_tool.arguments

        tool = tool_registry.get(tool_name)
        if tool is None:
            raise ToolExecutionError(tool_name, "Tool not found in registry", retryable=False)

        # --- 1. Rate limiting ---
        if tool_rate_limiter is not None:
            await tool_rate_limiter.check(tool_name)

        # Redact arguments for safe logging / observability (never log raw secrets)
        safe_arguments = redact(arguments)
        logger.debug("tool_executor_call", tool=tool_name, arguments=safe_arguments)

        # --- 2. Cache lookup ---
        if tool_cache is not None:
            cached = await tool_cache.get(tool_name, arguments)
            if cached is not None:
                logger.info("tool_cache_hit_executor", tool=tool_name)
                TOOL_EXECUTIONS_TOTAL.labels(tool_name=tool_name, success="True").inc()
                return {"tool_result": cached}

        ctx = SimpleToolContext(
            user_id=str(state.user_id),
            conversation_id=str(state.conversation_id),
            trace_id=state.trace_id,
        )

        # --- 3 & 4. Circuit breaker wraps the actual call ---
        start = time.perf_counter()
        if circuit_breaker is not None:
            async def _call():
                return await tool.execute(arguments, ctx)
            try:
                payload = await circuit_breaker.call(tool_name, _call())
            except ToolExecutionError:
                raise
            except Exception as exc:
                latency_ms = (time.perf_counter() - start) * 1000
                result = ToolResult(
                    tool_name=tool_name, success=False, error=str(exc), latency_ms=latency_ms
                )
                TOOL_EXECUTIONS_TOTAL.labels(tool_name=tool_name, success="False").inc()
                TOOL_EXECUTION_DURATION_SECONDS.labels(
                    tool_name=tool_name, success="False"
                ).observe(latency_ms / 1000)
                return {"tool_result": result}
        else:
            try:
                payload = await tool.execute(arguments, ctx)
            except Exception as exc:
                latency_ms = (time.perf_counter() - start) * 1000
                result = ToolResult(
                    tool_name=tool_name, success=False, error=str(exc), latency_ms=latency_ms
                )
                TOOL_EXECUTIONS_TOTAL.labels(tool_name=tool_name, success="False").inc()
                TOOL_EXECUTION_DURATION_SECONDS.labels(
                    tool_name=tool_name, success="False"
                ).observe(latency_ms / 1000)
                return {"tool_result": result}

        latency_ms = (time.perf_counter() - start) * 1000
        result = ToolResult(
            tool_name=tool_name,
            success=payload.success,
            output=payload.output,
            error=payload.error,
            latency_ms=latency_ms,
        )

        TOOL_EXECUTIONS_TOTAL.labels(tool_name=tool_name, success=str(result.success)).inc()
        TOOL_EXECUTION_DURATION_SECONDS.labels(
            tool_name=tool_name, success=str(result.success)
        ).observe(latency_ms / 1000)

        # --- 5. Write to cache on success ---
        if tool_cache is not None and result.success:
            ttl = (tool_cache_ttls or {}).get(tool_name)
            if ttl is not None:
                await tool_cache.set(tool_name, arguments, result, ttl)

        return {"tool_result": result}

    return tool_executor
