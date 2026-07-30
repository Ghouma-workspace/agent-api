from app.infrastructure.tools.registry import ToolRegistry


class ToolService:
    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._registry = tool_registry

    def list_tools(self) -> list[dict]:
        return self._registry.list_schemas()

    async def health_check(self) -> dict[str, bool]:
        return await self._registry.health_check_all()
