"""Planner node: decides WHETHER a tool is needed and WHICH one."""

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

PLANNER_SYSTEM_PROMPT = """You are a routing assistant. You MUST respond with ONLY a JSON object — no explanation, no markdown, no text before or after.

The JSON object MUST have exactly these three fields:
- "needs_tool": boolean (true or false)
- "tool_name": string or null
- "reasoning": string (one sentence)

Available tools: {tool_names}

Rules:
- needs_tool=true for: weather, GitHub operations, real-time data, external APIs
- needs_tool=false for: general knowledge, math, explanations, creative tasks
- tool_name must be exactly one of the available tool names when needs_tool is true, otherwise null

EXAMPLE RESPONSE (tool needed):
{{"needs_tool": true, "tool_name": "weather", "reasoning": "User wants real-time weather data."}}

EXAMPLE RESPONSE (no tool needed):
{{"needs_tool": false, "tool_name": null, "reasoning": "This is a general knowledge question."}}

RESPOND WITH ONLY THE JSON OBJECT. NOTHING ELSE."""


class PlannerOutput(BaseModel):
    needs_tool: bool
    tool_name: str | None = None
    reasoning: str


def _try_parse_llm_json(raw: str) -> dict | None:
    """Try to extract a JSON object from the LLM response even if it added extra text."""
    raw = raw.strip()

    # Direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Strip markdown code fences if present
    if "```" in raw:
        import re
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

    # Find first { ... } block
    import re
    match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


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
        logger.debug("planner_raw_response", trace_id=state.trace_id, raw=raw_content[:200])

        # Try to parse — use lenient extractor to handle extra text
        parsed = _try_parse_llm_json(raw_content)

        if parsed is None:
            logger.warning(
                "planner_json_parse_error",
                trace_id=state.trace_id,
                raw_preview=raw_content[:100],
            )
            raise ValidationError(
                f"Planner returned non-JSON response",
                errors=["json_parse_failed"],
            )

        # Fix common LLM mistakes before validation:
        # 1. needs_tool as string "true"/"false" instead of boolean
        if "needs_tool" in parsed and isinstance(parsed["needs_tool"], str):
            parsed["needs_tool"] = parsed["needs_tool"].lower() == "true"

        # 2. Missing reasoning field
        if "reasoning" not in parsed:
            parsed["reasoning"] = "No reasoning provided."

        # 3. tool_name as "none" / "null" string instead of null
        if parsed.get("tool_name") in ("none", "null", "None", "Null", ""):
            parsed["tool_name"] = None

        try:
            output = PlannerOutput.model_validate(parsed)
        except PydanticValidationError as exc:
            logger.warning(
                "planner_schema_validation_error",
                trace_id=state.trace_id,
                parsed=parsed,
                error=str(exc),
            )
            raise ValidationError(
                f"Planner output failed schema validation: {exc}",
                errors=["schema_validation_failed"],
            ) from exc

        # Validate tool_name is actually registered
        if output.needs_tool and output.tool_name not in tool_names:
            logger.warning(
                "planner_unknown_tool",
                trace_id=state.trace_id,
                tool_name=output.tool_name,
                available=tool_names,
            )
            output = PlannerOutput(
                needs_tool=False,
                tool_name=None,
                reasoning=f"Planner suggested unknown tool '{output.tool_name}', falling back to direct answer.",
            )

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
            return {
                **base,
                "needs_tool": True,
                "selected_tool": ToolCall(tool_name=output.tool_name, arguments={}),
            }

        return {**base, "needs_tool": False}

    return planner