import json as _json
import uuid
from datetime import UTC, datetime

import pytest

from app.application.agent.graph import build_agent_graph
from app.application.agent.state import AgentState
from app.application.services.prompt_service import PromptService
from app.core.config import Settings
from app.domain.entities.chat import ChatMessage, LLMResponse, MessageRole
from app.infrastructure.tools.base import EnvCredentialProvider
from app.infrastructure.tools.registry import ToolRegistry
from tests.conftest import FakeLLMProvider


def _null_prompt_service() -> PromptService:
    return PromptService(None, enable=False)


def _make_state(content: str = "hello") -> AgentState:
    return AgentState(
        conversation_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        trace_id="test-trace",
        messages=[
            ChatMessage(
                id=uuid.uuid4(),
                conversation_id=uuid.uuid4(),
                role=MessageRole.USER,
                content=content,
                created_at=datetime.now(UTC),
            )
        ],
    )


@pytest.mark.asyncio
async def test_direct_answer_path_skips_tools(settings: Settings):
    fake_llm = FakeLLMProvider([
        LLMResponse(content=_json.dumps({"needs_tool": False, "tool_name": None, "reasoning": "General knowledge question."})),
        LLMResponse(content="Here you go!"),
    ])
    registry = ToolRegistry(EnvCredentialProvider(settings))

    graph = build_agent_graph(fake_llm, registry, _null_prompt_service(), settings)
    result = await graph.ainvoke(_make_state("what's 2+2?"))

    # Planner decides no tool needed; response_generator calls LLM for the actual reply
    assert result["draft_response"] == "Here you go!"
    assert "tool_executor" not in result["node_path"]
    assert not result["validation_errors"]


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="AgentState in app/application/agent/state.py has no 'reasoning' field, so "
    "LangGraph silently drops the key planner.py returns when merging state. Requires "
    "a source change — not made here per instruction to leave app code untouched.",
    strict=True,
)
async def test_direct_answer_path_surfaces_planner_reasoning(settings: Settings):
    fake_llm = FakeLLMProvider([
        LLMResponse(content=_json.dumps({"needs_tool": False, "tool_name": None, "reasoning": "General knowledge question."})),
        LLMResponse(content="Here you go!"),
    ])
    registry = ToolRegistry(EnvCredentialProvider(settings))

    graph = build_agent_graph(fake_llm, registry, _null_prompt_service(), settings)
    result = await graph.ainvoke(_make_state("what's 2+2?"))

    assert result["reasoning"] == "General knowledge question."
