from app.application.agent.state import AgentState
from app.domain.providers.interfaces import LLMProvider, ToolRegistry
from app.infrastructure.observability.agent_tracing import traced_node


def make_tool_selector(llm: LLMProvider, tool_registry: ToolRegistry):
    @traced_node("tool_selector", calls_llm=True)
    async def tool_selector(state: AgentState) -> dict:
        schemas = tool_registry.list_schemas()
        response = await llm.complete(state.messages, tools=schemas)
        if not response.tool_calls:
            # LLM decided direct answer after all — fall through to response generation
            return {"needs_tool": False, "draft_response": response.content}
        return {"selected_tool": response.tool_calls[0]}

    return tool_selector
