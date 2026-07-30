import time

from app.application.agent.state import AgentState
from app.domain.entities.chat import ToolResult
from app.domain.exceptions.base import ToolExecutionError
from app.domain.providers.interfaces import ToolRegistry
from app.infrastructure.observability.agent_tracing import traced_node
from app.infrastructure.observability.metrics import (
    TOOL_EXECUTION_DURATION_SECONDS,
    TOOL_EXECUTIONS_TOTAL,
)


class SimpleToolContext:
    def __init__(self, user_id: str, conversation_id: str, trace_id: str) -> None:
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.trace_id = trace_id


def make_tool_executor(tool_registry: ToolRegistry):
    @traced_node("tool_executor")
    async def tool_executor(state: AgentState) -> dict:
        assert state.selected_tool is not None
        tool = tool_registry.get(state.selected_tool.tool_name)
        if tool is None:
            raise ToolExecutionError(
                state.selected_tool.tool_name, "Tool not found in registry", retryable=False
            )

        ctx = SimpleToolContext(
            user_id=str(state.user_id),
            conversation_id=str(state.conversation_id),
            trace_id=state.trace_id,
        )
        start = time.perf_counter()
        try:
            payload = await tool.execute(state.selected_tool.arguments, ctx)
            latency_ms = (time.perf_counter() - start) * 1000
            result = ToolResult(
                tool_name=tool.name,
                success=payload.success,
                output=payload.output,
                error=payload.error,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            result = ToolResult(
                tool_name=tool.name, success=False, error=str(exc), latency_ms=latency_ms
            )

        TOOL_EXECUTIONS_TOTAL.labels(tool_name=tool.name, success=str(result.success)).inc()
        TOOL_EXECUTION_DURATION_SECONDS.labels(
            tool_name=tool.name, success=str(result.success)
        ).observe(latency_ms / 1000)

        return {"tool_result": result}

    return tool_executor
