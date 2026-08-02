from fastapi import APIRouter, Depends, Request

from app.api.deps.auth import get_current_user_id
from app.api.deps.services import get_tool_service
from app.application.services.tool_service import ToolService

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("")
async def list_tools(
    _user_id=Depends(get_current_user_id), tool_service: ToolService = Depends(get_tool_service)
) -> list[dict]:
    return tool_service.list_tools()


@router.get("/health")
async def tool_health(
    _user_id=Depends(get_current_user_id), tool_service: ToolService = Depends(get_tool_service)
) -> dict[str, bool]:
    return await tool_service.health_check()


@router.get("/circuit-status")
async def circuit_status(
    request: Request,
    _user_id=Depends(get_current_user_id),
) -> list[dict]:
    """Return circuit breaker state for every registered tool.

    Useful for the admin dashboard and ops debugging. State values:
    closed (normal), open (failing fast), half_open (recovery probe).
    """
    container = request.app.state.container
    circuit_breaker = getattr(container, "circuit_breaker", None)
    tool_registry = container.tool_registry
    tool_names = [schema["name"] for schema in tool_registry.list_schemas()]

    if circuit_breaker is None:
        return [{"tool_name": name, "state": "closed", "failures": 0, "successes": 0, "opened_at": 0.0} for name in tool_names]

    statuses = []
    for name in tool_names:
        status = await circuit_breaker.get_status(name)
        statuses.append(status)
    return statuses
