"""Planner node: decides WHETHER a tool is needed and WHICH one.

Uses Groq's JSON mode + Pydantic validation so the decision is always structured
and inspectable. The `reasoning` field is the primary debugging signal.

IMPORTANT: The planner does NOT extract tool arguments. It sets selected_tool with
empty arguments as a hint for tool_selector, which uses function-calling in a
separate LLM pass to extract the actual typed arguments from the user message.

  planner  →  tool_selector  →  tool_executor
  (JSON mode, decides what)   (func-calling, extracts how)
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import structlog
from pydantic import BaseModel, ValidationError as PydanticValidationError

from app.application.agent.state import AgentState
from app.application.services.prompt_service import PromptService
from app.domain.entities.chat import ChatMessage, MessageRole, ToolCall
from app.domain.exceptions.base import ValidationError
from app.domain.providers.interfaces import LLMProvider, ToolRegistry
from app.infrastructure.observability.agent_tracing import traced_node

logger = structlog.get_logger()

PLANNER_SYSTEM_PROMPT = (
    "You are a planning assistant. Decide whether answering the user's message "
    "requires calling an external tool, or whether you can answer directly.\n\n"
    "Respond ONLY with a valid JSON object with exactly these fields:\n"
    '{{"needs_tool": true|false, "tool_name": "exact-tool-name-or-null", "reasoning": "one sentence"}}\n\n'
    "Available tools: {tool_names}\n\n"
    "Rules:\n"
    "- needs_tool=true for: real-time data, live APIs, GitHub operations, weather, side-effects.\n"
    "- needs_tool=false for: general knowledge, math, creative tasks, explanations.\n"
    "- tool_name must be exactly one of the available tool names when needs_tool=true, otherwise null.\n"
    "- Do NOT attempt to extract arguments — just name the tool."
)


class PlannerOutput(BaseModel):
    needs_tool: bool
    tool_name: str | None = None
    reasoning: str


def make_planner(llm: LLMProvider, tool_registry: ToolRegistry, prompt_service: PromptService):

    @traced_node("planner", calls_llm=True)
    async def planner(state: AgentState) -> dict:
        tool_schemas = tool_registry.list_llm_tools()
        tool_names = [t["function"]["name"] for t in tool_schemas]

        prompt_template = prompt_service.get("planner_system", fallback=PLANNER_SYSTEM_PROMPT)
        system_prompt = prompt_template.format(tool_names=", ".join(tool_names))

        now = state.messages[-1].created_at if state.messages else datetime.now(UTC)
        planning_messages = [
            ChatMessage(
                id=uuid.uuid4(),
                conversation_id=state.conversation_id,
                role=MessageRole.SYSTEM,
                content=system_prompt,
                created_at=now,
            ),
            *state.messages,
        ]

        response = await llm.complete(
            planning_messages,
            tools=None,
            response_format={"type": "json_object"},
        )

        raw_content = response.content.strip()
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            logger.warning("planner_json_parse_error", trace_id=state.trace_id, error=str(exc))
            raise ValidationError(
                f"Planner returned non-JSON response: {exc}",
                errors=["json_parse_failed"],
            ) from exc

        try:
            output = PlannerOutput.model_validate(parsed)
        except PydanticValidationError as exc:
            logger.warning("planner_schema_validation_error", trace_id=state.trace_id, error=str(exc))
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

        base = {
            "reasoning": output.reasoning,
            "prompt_tokens": state.prompt_tokens + response.prompt_tokens,
            "completion_tokens": state.completion_tokens + response.completion_tokens,
        }

        if output.needs_tool and output.tool_name:
            # Store the tool hint with EMPTY arguments — tool_selector fills them in.
            return {
                **base,
                "needs_tool": True,
                "selected_tool": ToolCall(tool_name=output.tool_name, arguments={}),
            }

        return {**base, "needs_tool": False}

    return planner