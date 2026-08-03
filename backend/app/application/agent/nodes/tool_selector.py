"""Tool selector node.

Receives the planner's decision (needs_tool=True, tool_name hint) and uses
function-calling to extract the exact typed arguments the tool requires.

This is intentionally a separate LLM call from the planner:
  - The planner uses JSON mode  (structured decision, no function-calling)
  - This node uses function-calling mode (argument extraction from user message)
Groq does not support both simultaneously.

When the planner already identified a specific tool, we pass only that tool's
schema so the LLM focuses argument extraction on the right tool and cannot
hallucinate a different one.
"""

from __future__ import annotations

import structlog

from app.application.agent.state import AgentState
from app.application.services.prompt_service import PromptService
from app.domain.providers.interfaces import LLMProvider, ToolRegistry
from app.infrastructure.observability.agent_tracing import traced_node

logger = structlog.get_logger()

TOOL_SELECTOR_SYSTEM_PROMPT = (
    "You are a tool invocation assistant. "
    "Extract the required arguments from the user's message and call the appropriate tool. "
    "Read the user message carefully and pass all mentioned parameters as tool arguments. "
    "Never call a tool with empty arguments if the schema marks fields as required."
)


def make_tool_selector(llm: LLMProvider, tool_registry: ToolRegistry, prompt_service: PromptService):
    @traced_node("tool_selector", calls_llm=True)
    async def tool_selector(state: AgentState) -> dict:
        all_schemas = tool_registry.list_llm_tools()

        # If the planner already identified which tool to use, pass only that
        # schema so the LLM focuses entirely on extracting the right arguments.
        # This avoids the model hallucinating a different tool and prevents
        # empty-argument calls caused by schema ambiguity.
        planner_hint = (
            state.selected_tool.tool_name
            if state.selected_tool is not None
            else None
        )
        if planner_hint:
            schemas = [s for s in all_schemas if s["function"]["name"] == planner_hint]
            if not schemas:
                schemas = all_schemas  # hint doesn't match any known tool — use all
        else:
            schemas = all_schemas

        _ = prompt_service.get("tool_selector_system", fallback=TOOL_SELECTOR_SYSTEM_PROMPT)

        response = await llm.complete(state.messages, tools=schemas)

        if not response.tool_calls:
            # LLM decided no tool is needed after seeing the full schema detail
            logger.info(
                "tool_selector_no_call",
                trace_id=state.trace_id,
                planner_hint=planner_hint,
            )
            return {"needs_tool": False, "draft_response": response.content}

        selected = response.tool_calls[0]
        logger.info(
            "tool_selector_call",
            trace_id=state.trace_id,
            tool=selected.tool_name,
            arguments=selected.arguments,
        )
        return {"selected_tool": selected}

    return tool_selector