from fastapi import APIRouter, Depends

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
