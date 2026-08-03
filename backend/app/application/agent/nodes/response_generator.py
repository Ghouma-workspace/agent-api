"""Response generator node.

When a tool result is available, the LLM receives a single self-contained USER
prompt that contains both the original question and the retrieved data. This
prevents any "according to the earlier message" / "information provided earlier"
phrasing because there is no earlier message — just one question with the data
already embedded in it.

When no tool was called, the conversation history is passed as-is so the LLM
can answer from its own knowledge.
"""

from __future__ import annotations

import json
import uuid

import structlog

from app.application.agent.state import AgentState
from app.application.services.prompt_service import PromptService
from app.domain.entities.chat import ChatMessage, MessageRole
from app.domain.providers.interfaces import LLMProvider
from app.infrastructure.observability.agent_tracing import traced_node

logger = structlog.get_logger()

RESPONSE_GENERATOR_SYSTEM_PROMPT = (
    "You are a helpful AI assistant. "
    "Answer questions clearly and concisely. "
    "When data is provided inside the user's message, present it naturally as your answer — "
    "never say 'according to the data provided', 'based on the information above', "
    "'the results show', or any similar meta-commentary. "
    "Never add disclaimers about data reliability unless you have a specific reason to doubt it. "
    "Never mention that data came from a tool, an API, or a previous message. "
    "Just answer as if you know the information."
)


def _format_tool_data(output: dict) -> str:
    """Convert raw tool output dict into readable key-value lines."""
    lines = []
    for key, value in output.items():
        # Convert snake_case keys to readable labels
        label = key.replace("_", " ").capitalize()
        lines.append(f"  {label}: {value}")
    return "\n".join(lines)


def make_response_generator(llm: LLMProvider, prompt_service: PromptService):
    @traced_node("response_generator", calls_llm=True)
    async def response_generator(state: AgentState) -> dict:
        # Pass through any answer already produced upstream (e.g. content filter refusal)
        if state.draft_response:
            return {"draft_response": state.draft_response}

        system_prompt = prompt_service.get(
            "response_generator_system", fallback=RESPONSE_GENERATOR_SYSTEM_PROMPT
        )

        now = state.messages[-1].created_at if state.messages else (
            __import__("datetime").datetime.now(__import__("datetime").UTC)
        )
        original_question = state.messages[-1].content if state.messages else ""

        if state.tool_result is not None and state.tool_result.success:
            # ── Tool succeeded: build a single self-contained prompt ──────────
            # Embedding the data directly in the user message means there is no
            # "earlier message" for the LLM to reference. It just sees a question
            # that already contains the answer data and must present it naturally.
            tool_data_str = _format_tool_data(state.tool_result.output or {})
            combined_user_prompt = (
                f"{original_question}\n\n"
                f"Data:\n{tool_data_str}"
            )
            messages_to_send = [
                ChatMessage(
                    id=uuid.uuid4(),
                    conversation_id=state.conversation_id,
                    role=MessageRole.SYSTEM,
                    content=system_prompt,
                    created_at=now,
                ),
                ChatMessage(
                    id=uuid.uuid4(),
                    conversation_id=state.conversation_id,
                    role=MessageRole.USER,
                    content=combined_user_prompt,
                    created_at=now,
                ),
            ]

        elif state.tool_result is not None and not state.tool_result.success:
            # ── Tool failed: tell the LLM what went wrong, ask it to help ────
            error_prompt = (
                f"{original_question}\n\n"
                f"Note: I tried to fetch this data but the request failed "
                f"({state.tool_result.error}). "
                f"Let the user know you could not retrieve the information right now."
            )
            messages_to_send = [
                ChatMessage(
                    id=uuid.uuid4(),
                    conversation_id=state.conversation_id,
                    role=MessageRole.SYSTEM,
                    content=system_prompt,
                    created_at=now,
                ),
                ChatMessage(
                    id=uuid.uuid4(),
                    conversation_id=state.conversation_id,
                    role=MessageRole.USER,
                    content=error_prompt,
                    created_at=now,
                ),
            ]

        else:
            # ── No tool: pass the full conversation so the LLM can answer ────
            messages_to_send = [
                ChatMessage(
                    id=uuid.uuid4(),
                    conversation_id=state.conversation_id,
                    role=MessageRole.SYSTEM,
                    content=system_prompt,
                    created_at=now,
                ),
                *state.messages,
            ]

        response = await llm.complete(messages_to_send)

        logger.info(
            "response_generator_done",
            trace_id=state.trace_id,
            has_tool_result=state.tool_result is not None,
            tool_success=state.tool_result.success if state.tool_result else None,
            tokens=response.prompt_tokens + response.completion_tokens,
        )

        return {
            "draft_response": response.content,
            "prompt_tokens": state.prompt_tokens + response.prompt_tokens,
            "completion_tokens": state.completion_tokens + response.completion_tokens,
        }

    return response_generator