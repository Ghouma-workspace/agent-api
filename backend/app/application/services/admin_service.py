from app.domain.repositories.interfaces import LLMUsageRepository
from app.infrastructure.observability.metrics import ACTIVE_USERS
from app.infrastructure.tools.registry import ToolRegistry


class AdminService:
    """Backs GET /api/admin/* — Prometheus/Grafana own the historical time series,
    this service answers the 'give me current numbers for the dashboard' queries
    that are cheaper to serve straight from Postgres/in-process state."""

    def __init__(self, llm_usage_repo: LLMUsageRepository, tool_registry: ToolRegistry) -> None:
        self._llm_usage = llm_usage_repo
        self._tools = tool_registry

    async def daily_cost(self) -> float:
        return await self._llm_usage.daily_cost()

    def active_users(self) -> float:
        return ACTIVE_USERS._value.get()  # exposed via /metrics too; convenience accessor here

    async def tool_health(self) -> dict[str, bool]:
        return await self._tools.health_check_all()
