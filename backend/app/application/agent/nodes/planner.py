from app.application.agent.state import AgentState
from app.domain.providers.interfaces import LLMProvider, ToolRegistry
from app.infrastructure.observability.agent_tracing import traced_node


def make_planner(llm: LLMProvider, tool_registry: ToolRegistry):
    """Decides tool-vs-direct using the LLM's native function-calling rather than
    asking it to reply with a bare 'TOOL'/'DIRECT' word. Keyword-matching a chat-tuned
    model's free text is unreliable — it tends to just answer the question instead of
    following the meta-instruction. Native tool_calls are what Groq/OpenAI-style
    function-calling is built for, so we use that signal directly."""

    @traced_node("planner", calls_llm=True)
    async def planner(state: AgentState) -> dict:
        schemas = tool_registry.list_llm_tools()
        response = await llm.complete(state.messages, tools=schemas)

        if response.tool_calls:
            return {
                "needs_tool": True, "selected_tool": response.tool_calls[0],
                "prompt_tokens": state.prompt_tokens + response.prompt_tokens,
                "completion_tokens": state.completion_tokens + response.completion_tokens,
            }

        return {
            "needs_tool": False, "draft_response": response.content,
            "prompt_tokens": state.prompt_tokens + response.prompt_tokens,
            "completion_tokens": state.completion_tokens + response.completion_tokens,
        }

    return planner
