from app.infrastructure.tools.base import BaseToolPlugin, EnvCredentialProvider
from app.infrastructure.tools.github_tool import GitHubTool
from app.infrastructure.tools.mock_tool import MockTool
from app.infrastructure.tools.stub_tools import JiraTool, NotionTool, SlackTool, StripeTool, TrelloTool
from app.infrastructure.tools.weather_tool import WeatherTool


class ToolRegistry:
    """Implements domain.providers.interfaces.ToolRegistry. Construction is the ONLY
    place that needs editing to add a new tool to the whole platform."""

    _PLUGIN_CLASSES: list[type[BaseToolPlugin]] = [
        GitHubTool,
        WeatherTool,
        MockTool,
        JiraTool,
        NotionTool,
        TrelloTool,
        SlackTool,
        StripeTool,
    ]

    def __init__(self, credentials: EnvCredentialProvider) -> None:
        self._plugins: dict[str, BaseToolPlugin] = {
            cls.name: cls(credentials) for cls in self._PLUGIN_CLASSES
        }

    def get(self, name: str) -> BaseToolPlugin | None:
        return self._plugins.get(name)

    def list_schemas(self) -> list[dict]:
        return [
            {"name": p.name, "description": p.description, "schema": p.to_llm_schema()}
            for p in self._plugins.values()
        ]

    def list_llm_tools(self) -> list[dict]:
        """Full function-calling schemas, ready to pass to LLMProvider.complete(tools=...)."""
        return [p.to_llm_schema() for p in self._plugins.values()]

    async def health_check_all(self) -> dict[str, bool]:
        return {name: await plugin.health_check() for name, plugin in self._plugins.items()}
