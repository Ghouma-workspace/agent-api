from app.application.agent.state import AgentState
from app.infrastructure.observability.agent_tracing import traced_node
from app.infrastructure.observability.metrics import FAILURES_TOTAL


@traced_node("error_handler")
async def error_handler(state: AgentState) -> dict:
    retryable = bool(state.tool_result and not state.tool_result.success)
    if not retryable:
        FAILURES_TOTAL.labels(component="agent").inc()
        return {
            "error": "unrecoverable",
            "draft_response": (
                "I ran into a problem completing that request and can't retry it further. "
                "Could you rephrase, or try again in a moment?"
            ),
        }
    return {"error": "retryable"}
