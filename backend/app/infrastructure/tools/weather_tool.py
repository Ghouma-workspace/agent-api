from typing import ClassVar

from app.infrastructure.tools.base import (
    BaseToolPlugin,
    ResilientHTTPClient,
    ToolExecutionContext,
    ToolResultPayload,
)


class WeatherTool(BaseToolPlugin):
    """Second fully implemented reference tool — proves the plugin contract generalizes
    beyond GitHub-shaped 'developer' APIs to a simple public REST integration."""

    name = "weather"
    description = "Get the current weather for a given latitude/longitude."
    parameters_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "latitude": {"type": "number"},
            "longitude": {"type": "number"},
        },
        "required": ["latitude", "longitude"],
    }

    def __init__(self, credentials) -> None:
        super().__init__(credentials)
        self._http = ResilientHTTPClient(base_url="https://api.open-meteo.com", timeout=10.0)

    async def execute(self, args: dict, ctx: ToolExecutionContext) -> ToolResultPayload:
        lat, lon = args.get("latitude"), args.get("longitude")
        if lat is None or lon is None:
            return ToolResultPayload(success=False, error="'latitude' and 'longitude' are required")
        try:
            response = await self._http.request(
                "GET",
                "/v1/forecast",
                params={"latitude": lat, "longitude": lon, "current_weather": "true"},
            )
            current = response.json().get("current_weather", {})
            return ToolResultPayload(success=True, output=current)
        except Exception as exc:
            return ToolResultPayload(success=False, error=str(exc))

    async def health_check(self) -> bool:
        try:
            response = await self._http.request(
                "GET",
                "/v1/forecast",
                params={"latitude": 0, "longitude": 0, "current_weather": "true"},
            )
            return response.status_code == 200
        except Exception:
            return False
