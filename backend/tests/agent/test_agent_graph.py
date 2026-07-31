import uuid
from datetime import UTC, datetime

import pytest

from app.application.agent.graph import build_agent_graph
from app.application.agent.state import AgentState
from app.core.config import Settings
from app.domain.entities.chat import ChatMessage, LLMResponse, MessageRole
from app.infrastructure.tools.base import EnvCredentialProvider
from app.infrastructure.tools.registry import ToolRegistry
from tests.conftest import FakeLLMProvider


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
    fake_llm = FakeLLMProvider([LLMResponse(content="DIRECT"), LLMResponse(content="Here you go!")])
    registry = ToolRegistry(EnvCredentialProvider(settings))

    graph = build_agent_graph(fake_llm, registry, settings)
    result = await graph.ainvoke(_make_state("what's 2+2?"))

    assert result["draft_response"] == "DIRECT"
    assert "tool_executor" not in result["node_path"]
    assert not result["validation_errors"]


# @pytest.mark.asyncio
# async def test_tool_path_invokes_mock_tool(settings: Settings):
#     fake_llm = FakeLLMProvider(
#         [
#             LLMResponse(content="TOOL"),
#             LLMResponse(content="", tool_calls=[ToolCall(tool_name="mock_api", arguments={"payload": "ping"})]),
#             LLMResponse(content="The tool echoed: ping"),
#         ]
#     )
#     registry = ToolRegistry(EnvCredentialProvider(settings))

#     graph = build_agent_graph(fake_llm, registry, settings)
#     result = await graph.ainvoke(_make_state("call the mock tool with ping"))

#     assert "tool_executor" in result["node_path"]
#     assert result["tool_result"].success is True
#     assert result["tool_result"].output == {"echo": "ping"}
