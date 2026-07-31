from typing import ClassVar

from app.infrastructure.tools.base import BaseToolPlugin, ToolExecutionContext, ToolResultPayload


class MockTool(BaseToolPlugin):
    """Deterministic no-network tool used by agent tests and local demos so the whole
    graph can be exercised without hitting any real external API."""

    name = "mock_api"
    description = "Echoes back whatever input it receives — used for testing and demos."
    parameters_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {"payload": {"type": "string"}},
        "required": ["payload"],
    }

    async def execute(self, args: dict, ctx: ToolExecutionContext) -> ToolResultPayload:
        return ToolResultPayload(success=True, output={"echo": args.get("payload", "")})
