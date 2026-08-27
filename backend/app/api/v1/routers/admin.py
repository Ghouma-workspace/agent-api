"""Admin router — serves the AdminPage.tsx dashboard data."""

from fastapi import APIRouter, Depends

from app.api.deps.auth import get_current_user_id
from app.api.deps.services import get_admin_service
from app.application.services.admin_service import AdminService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/summary")
async def admin_summary(
    _user_id=Depends(get_current_user_id),
    admin_service: AdminService = Depends(get_admin_service),
) -> dict:
    """
    Returns current-state numbers for the admin dashboard:
      - daily_cost_usd: today's LLM spend
      - active_users: users active in the last 5 minutes
      - tool_health: per-tool up/down status
    """
    return await admin_service.get_summary()