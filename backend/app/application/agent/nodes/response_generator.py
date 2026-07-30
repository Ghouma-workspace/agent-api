from app.application.agent.state import AgentState
from app.domain.entities.chat import ChatMessage, MessageRole
from app.domain.providers.interfaces import LLMProvider
from app.infrastructure.observability.agent_tracing import traced_node


def make_response_generator(llm: LLMProvider):
    @traced_node("response_generator", calls_llm=True)
    async def response_generator(state: AgentState) -> dict:
        if state.draft_response:
            # tool_selector already produced a direct answer, nothing more to do
            return {"draft_response": state.draft_response}

        context_messages = list(state.messages)
        if state.tool_result is not None:
            tool_summary = (
                f"Tool '{state.tool_result.tool_name}' returned: "
                f"{state.tool_result.output if state.tool_result.success else state.tool_result.error}"
            )
            context_messages.append(
                ChatMessage(
                    id=state.messages[-1].id,
                    conversation_id=state.conversation_id,
                    role=MessageRole.SYSTEM,
                    content=tool_summary,
                    created_at=state.messages[-1].created_at,
                )
            )

        response = await llm.complete(context_messages)
        return {
            "draft_response": response.content,
            "prompt_tokens": state.prompt_tokens + response.prompt_tokens,
            "completion_tokens": state.completion_tokens + response.completion_tokens,
        }

    return response_generator
