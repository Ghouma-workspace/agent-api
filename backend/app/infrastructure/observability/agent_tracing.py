from __future__ import annotations

import functools
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any, TypeVar

import structlog
from opentelemetry import trace

from app.application.agent.state import AgentState
from app.infrastructure.observability.metrics import AGENT_NODE_DURATION_SECONDS, FAILURES_TOTAL

logger = structlog.get_logger()
tracer = trace.get_tracer("ai-api-assistant.agent")

T = TypeVar("T", bound=AgentState)
NodeFn = Callable[[T], Awaitable[dict]]

_langfuse_trace_var: ContextVar[Any | None] = ContextVar("langfuse_trace", default=None)


def set_current_langfuse_trace(trace_obj: Any | None) -> None:
    _langfuse_trace_var.set(trace_obj)


def _safe_serialize(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_safe_serialize(v) for v in value]
    if isinstance(value, dict):
        return {k: _safe_serialize(v) for k, v in value.items()}
    return value


def _node_input_snapshot(state: AgentState) -> dict:
    return {
        "last_message": state.messages[-1].content if state.messages else None,
        "needs_tool": state.needs_tool,
        "selected_tool": _safe_serialize(state.selected_tool),
        "tool_result": _safe_serialize(state.tool_result),
        "retry_count": state.retry_count,
        "validation_loop_count": state.validation_loop_count,
    }


def traced_node(node_name: str, *, calls_llm: bool = False) -> Callable[[NodeFn], NodeFn]:
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
                        # Extract the Langfuse prompt object if the node stored it
                        # This links the generation to the prompt version in Langfuse
                        # so the "Number of Generations" counter increments correctly
                        langfuse_prompt = state.__dict__.get("_langfuse_prompt")
                        generation_kwargs = {
                            "name": node_name,
                            "model": "groq",
                            "input": node_input,
                        }
                        if langfuse_prompt is not None:
                            generation_kwargs["prompt"] = langfuse_prompt
                        lf_observation = lf_trace.generation(**generation_kwargs)
                    else:
                        lf_observation = lf_trace.span(
                            name=node_name, input=node_input
                        )

                try:
                    result = await fn(state)
                    duration = time.perf_counter() - start
                    AGENT_NODE_DURATION_SECONDS.labels(node=node_name).observe(duration)
                    log.info("agent_node_end", latency_ms=duration * 1000)
                    result.setdefault("node_path", [*state.node_path, node_name])

                    if lf_observation is not None:
                        lf_output = _safe_serialize(result)
                        if "reasoning" in result:
                            lf_output["_reasoning"] = result["reasoning"]

                        langfuse_prompt = state.__dict__.get("_langfuse_prompt")
                        if langfuse_prompt is not None:
                            lf_observation.update(prompt=langfuse_prompt)
                        lf_observation.end(output=lf_output)

                    # Clear the prompt object after use so it doesn't leak
                    # to the next node
                    state.__dict__.pop("_langfuse_prompt", None)

                    return result

                except Exception as exc:
                    duration = time.perf_counter() - start
                    span.record_exception(exc)
                    AGENT_NODE_DURATION_SECONDS.labels(node=node_name).observe(duration)
                    FAILURES_TOTAL.labels(component=node_name).inc()
                    log.error("agent_node_error", error=str(exc), latency_ms=duration * 1000)

                    if lf_observation is not None:
                        lf_observation.end(output={"error": str(exc)}, level="ERROR")

                    state.__dict__.pop("_langfuse_prompt", None)
                    raise

        return wrapper
    return decorator