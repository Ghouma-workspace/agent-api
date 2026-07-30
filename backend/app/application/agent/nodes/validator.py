from app.application.agent.state import AgentState
from app.infrastructure.observability.agent_tracing import traced_node


@traced_node("validator")
async def validator(state: AgentState) -> dict:
    errors: list[str] = []

    if not state.draft_response.strip():
        errors.append("draft_response is empty")
    if state.tool_result is not None and not state.tool_result.success and not state.draft_response:
        errors.append("tool failed and no fallback response was generated")

    return {"validation_errors": errors}
