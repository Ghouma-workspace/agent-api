import pytest

from app.infrastructure.tools.base import ToolExecutionContext
from app.infrastructure.tools.mock_tool import MockTool


@pytest.mark.asyncio
async def test_mock_tool_echoes_payload():
    tool = MockTool(credentials=None)
    ctx = ToolExecutionContext(user_id="u1", conversation_id="c1", trace_id="t1")

    result = await tool.execute({"payload": "hello world"}, ctx)

    assert result.success is True
    assert result.output == {"echo": "hello world"}
