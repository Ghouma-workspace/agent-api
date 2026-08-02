from __future__ import annotations

import json

import structlog
from pydantic import BaseModel, ValidationError as PydanticValidationError

from app.application.agent.state import AgentState
from app.application.services.prompt_service import PromptService
from app.domain.exceptions.base import ValidationError
from app.domain.providers.interfaces import LLMProvider, ToolRegistry
from app.infrastructure.observability.agent_tracing import traced_node

logger = structlog.get_logger()

PLANNER_SYSTEM_PROMPT = (
    "You are a planning assistant. Your job is to decide whether answering the user's message "
    "requires calling an external tool, or whether you can answer directly with your own knowledge.\n\n"
    "Respond ONLY with a valid JSON object — no markdown, no extra text — with exactly these fields:\n"
    '{{"needs_tool": true|false, "tool_name": "tool-name-or-null", "reasoning": "one sentence"}}\n\n'
    "Available tools: {tool_names}\n\n"
    "Rules:\n"
    "- Set needs_tool=true only when real-time data, external APIs, or side-effects are required.\n"
    "- Set needs_tool=false for general knowledge, reasoning, math, or creative tasks.\n"
    "- tool_name must be exactly one of the available tool names, or null.\n"
)


class PlannerOutput(BaseModel):
    """Validated structure of the planner's LLM response."""

    needs_tool: bool
    tool_name: str | None = None
    reasoning: str


def make_planner(llm: LLMProvider, tool_registry: ToolRegistry, prompt_service: PromptService):
    """Returns a planner node that calls the LLM with JSON mode and validates the output.
    Planner node: decides whether the agent needs a tool or can answer directly.
    Uses Groq's JSON mode + Pydantic validation so the decision is always structured and
    inspectable. The `reasoning` field is the single most important debugging signal —
    it appears in Langfuse, structlog, and AgentState."""

    @traced_node("planner", calls_llm=True)
    async def planner(state: AgentState) -> dict:
        tool_schemas = tool_registry.list_llm_tools()
        tool_names = [t["function"]["name"] for t in tool_schemas]

        prompt_template = prompt_service.get("planner_system", fallback=PLANNER_SYSTEM_PROMPT)
        system_prompt = prompt_template.format(tool_names=", ".join(tool_names))
        from app.domain.entities.chat import ChatMessage, MessageRole
        import uuid

        planning_messages = [
            ChatMessage(
                id=uuid.uuid4(),
                conversation_id=state.conversation_id,
                role=MessageRole.SYSTEM,
                content=system_prompt,
                created_at=state.messages[-1].created_at if state.messages else __import__("datetime").datetime.now(__import__("datetime").UTC),
            ),
            *state.messages,
        ]

        response = await llm.complete(
            planning_messages,
            tools=None,  # JSON mode — no function-calling schema; decision is in the JSON
            response_format={"type": "json_object"},
        )

        raw_content = response.content.strip()
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            logger.warning(
                "planner_json_parse_error",
                trace_id=state.trace_id,
                conversation_id=str(state.conversation_id),
                error=str(exc),
            )
            raise ValidationError(
                f"Planner returned non-JSON response: {exc}",
                errors=["json_parse_failed"],
            ) from exc

        try:
            output = PlannerOutput.model_validate(parsed)
        except PydanticValidationError as exc:
            logger.warning(
                "planner_schema_validation_error",
                trace_id=state.trace_id,
                conversation_id=str(state.conversation_id),
                error=str(exc),
            )
            raise ValidationError(
                f"Planner output failed schema validation: {exc}",
                errors=["schema_validation_failed"],
            ) from exc

        logger.info(
            "planner_decision",
            trace_id=state.trace_id,
            needs_tool=output.needs_tool,
            tool_name=output.tool_name,
            reasoning=output.reasoning,
        )

        if output.needs_tool and output.tool_name:
            # Resolve matching tool call from registry to build a ToolCall entity
            from app.domain.entities.chat import ToolCall
            selected = ToolCall(tool_name=output.tool_name, arguments={})
            return {
                "needs_tool": True,
                "selected_tool": selected,
                "reasoning": output.reasoning,
                "prompt_tokens": state.prompt_tokens + response.prompt_tokens,
                "completion_tokens": state.completion_tokens + response.completion_tokens,
            }

        return {
            "needs_tool": False,
            "reasoning": output.reasoning,
            "prompt_tokens": state.prompt_tokens + response.prompt_tokens,
            "completion_tokens": state.completion_tokens + response.completion_tokens,
        }

    return planner
