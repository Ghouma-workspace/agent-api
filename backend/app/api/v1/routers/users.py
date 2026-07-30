from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.deps.auth import get_current_user_id

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
async def get_me(request: Request, user_id: UUID = Depends(get_current_user_id)) -> dict:
    scope = request.state.scope
    user = await scope.user_repo.get_by_id(user_id)
    return {"id": str(user.id), "email": user.email} if user else {}
