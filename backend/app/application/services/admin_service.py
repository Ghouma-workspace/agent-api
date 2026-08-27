"""Admin use-case service — surfaces current-state numbers for the admin dashboard."""

from __future__ import annotations

import structlog
from prometheus_client import REGISTRY

from app.domain.providers.interfaces import ToolRegistry

logger = structlog.get_logger()


class AdminService:
    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._tool_registry = tool_registry

    async def get_summary(self) -> dict:
        return {
            "daily_cost_usd": self._get_daily_cost(),
            "active_users":   self._get_active_users(),
            "tool_health":    await self._get_tool_health(),
        }

    def _get_daily_cost(self) -> float:
        """Read the llm_cost_usd_total counter directly from Prometheus registry."""
        try:
            for metric in REGISTRY.collect():
                if metric.name == "llm_cost_usd_total":
                    return sum(s.value for s in metric.samples if s.name.endswith("_total"))
            return 0.0
        except Exception:
            return 0.0

    def _get_active_users(self) -> int:
        """Read the active_users gauge from Prometheus registry."""
        try:
            for metric in REGISTRY.collect():
                if metric.name == "active_users":
                    for sample in metric.samples:
                        return int(sample.value)
            return 0
        except Exception:
            return 0

    async def _get_tool_health(self) -> dict[str, bool]:
        """Check each registered tool is reachable."""
        health: dict[str, bool] = {}
        for schema in self._tool_registry.list_schemas():
            name = schema.get("name", schema.get("function", {}).get("name", "unknown"))
            tool = self._tool_registry.get(name)
            if tool is None:
                health[name] = False
                continue
            try:
                if hasattr(tool, "health_check"):
                    health[name] = await tool.health_check()
                else:
                    health[name] = True   # tool exists and is registered → healthy
            except Exception:
                health[name] = False
        return health