from fastapi import APIRouter, Depends

from app.api.deps.auth import get_current_user_id
from app.api.deps.services import get_admin_service
from app.application.services.admin_service import AdminService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/summary")
async def summary(
    _user_id=Depends(get_current_user_id), admin_service: AdminService = Depends(get_admin_service)
) -> dict:
    return {
        "daily_cost_usd": await admin_service.daily_cost(),
        "active_users": admin_service.active_users(),
        "tool_health": await admin_service.tool_health(),
    }
