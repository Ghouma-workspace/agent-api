from app.application.agent.state import AgentState
from app.application.services.prompt_service import PromptService
from app.domain.providers.interfaces import LLMProvider, ToolRegistry
from app.infrastructure.observability.agent_tracing import traced_node

TOOL_SELECTOR_SYSTEM_PROMPT = (
    "You are a tool selection assistant. Given the conversation, choose the most appropriate "
    "tool and extract the required arguments from the user's message. "
    "Use function-calling to indicate which tool to invoke."
)


def make_tool_selector(llm: LLMProvider, tool_registry: ToolRegistry, prompt_service: PromptService):
    @traced_node("tool_selector", calls_llm=True)
    async def tool_selector(state: AgentState) -> dict:
        schemas = tool_registry.list_llm_tools()
        _ = prompt_service.get("tool_selector_system", fallback=TOOL_SELECTOR_SYSTEM_PROMPT)
        response = await llm.complete(state.messages, tools=schemas)
        if not response.tool_calls:
            # LLM decided direct answer after all — fall through to response generation
            return {"needs_tool": False, "draft_response": response.content}
        return {"selected_tool": response.tool_calls[0]}

    return tool_selector
