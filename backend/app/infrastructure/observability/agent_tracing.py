"""`@traced_node` wraps every LangGraph node with three observability signals: an OTel
span, a structured log line, and — new — a nested Langfuse observation under the
current chat turn's trace. The Langfuse trace object itself is carried via a
ContextVar (set once per turn in ChatService), mirroring how request_id_var/trace_id_var
already propagate request context through this same call chain for structlog."""
from __future__ import annotations

import functools
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any, TypeVar

import structlog
from opentelemetry import trace

from app.application.agent.state import AgentState
from app.infrastructure.observability.metrics import AGENT_NODE_DURATION_SECONDS

logger = structlog.get_logger()
tracer = trace.get_tracer("ai-api-assistant.agent")

T = TypeVar("T", bound=AgentState)
NodeFn = Callable[[T], Awaitable[dict]]

_langfuse_trace_var: ContextVar[Any | None] = ContextVar("langfuse_trace", default=None)


def set_current_langfuse_trace(trace_obj: Any | None) -> None:
    """Called once per chat turn in ChatService, before the graph runs."""
    _langfuse_trace_var.set(trace_obj)


def _safe_serialize(value: Any) -> Any:
    """Converts pydantic models (ChatMessage, ToolCall, ToolResult, ...) in node
    inputs/outputs into plain dicts so Langfuse can JSON-encode them."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_safe_serialize(v) for v in value]
    if isinstance(value, dict):
        return {k: _safe_serialize(v) for k, v in value.items()}
    return value


def _node_input_snapshot(state: AgentState) -> dict:
    """What the node saw when it started — deliberately compact (last message + the
    decision-relevant state) rather than the full message history on every node."""
    return {
        "last_message": state.messages[-1].content if state.messages else None,
        "needs_tool": state.needs_tool,
        "selected_tool": _safe_serialize(state.selected_tool),
        "tool_result": _safe_serialize(state.tool_result),
        "retry_count": state.retry_count,
        "validation_loop_count": state.validation_loop_count,
    }


def traced_node(node_name: str, *, calls_llm: bool = False) -> Callable[[NodeFn], NodeFn]:
    """`calls_llm=True` opens a Langfuse *generation* (shows up alongside token/cost
    data); `calls_llm=False` opens a plain *span* (control-flow/tool-execution nodes
    that don't themselves call the LLM)."""

    def decorator(fn: NodeFn) -> NodeFn:
        @functools.wraps(fn)
        async def wrapper(state: T) -> dict:
            start = time.perf_counter()
            with tracer.start_as_current_span(f"agent.node.{node_name}") as span:
                span.set_attribute("trace_id", state.trace_id)
                span.set_attribute("conversation_id", str(state.conversation_id))
                log = logger.bind(
                    node=node_name,
                    trace_id=state.trace_id,
                    conversation_id=str(state.conversation_id),
                    user_id=str(state.user_id),
                )
                log.info("agent_node_start")

                lf_trace = _langfuse_trace_var.get()
                lf_observation = None
                node_input = _node_input_snapshot(state)
                if lf_trace is not None:
                    if calls_llm:
                        lf_observation = lf_trace.generation(
                            name=node_name, model="groq", input=node_input
                        )
                    else:
                        lf_observation = lf_trace.span(name=node_name, input=node_input)

                try:
                    result = await fn(state)
                    duration = time.perf_counter() - start
                    AGENT_NODE_DURATION_SECONDS.labels(node=node_name).observe(duration)
                    log.info("agent_node_end", latency_ms=duration * 1000)
                    result.setdefault("node_path", [*state.node_path, node_name])

                    if lf_observation is not None:
                        lf_observation.end(output=_safe_serialize(result))

                    return result
                except Exception as exc:
                    duration = time.perf_counter() - start
                    span.record_exception(exc)
                    AGENT_NODE_DURATION_SECONDS.labels(node=node_name).observe(duration)
                    log.error("agent_node_error", error=str(exc), latency_ms=duration * 1000)

                    if lf_observation is not None:
                        lf_observation.end(output={"error": str(exc)}, level="ERROR")

                    raise

        return wrapper

    return decorator
