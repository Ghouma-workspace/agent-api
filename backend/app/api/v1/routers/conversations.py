from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.deps.auth import get_current_user_id

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(
    request: Request, user_id: UUID = Depends(get_current_user_id)
) -> list[dict]:
    scope = request.state.scope
    conversations = await scope.conversation_repo.list_for_user(user_id)
    return [c.model_dump(mode="json") for c in conversations]


@router.get("/{conversation_id}/messages")
async def get_messages(
    conversation_id: UUID, request: Request, _user_id: UUID = Depends(get_current_user_id)
) -> list[dict]:
    scope = request.state.scope
    messages = await scope.message_repo.list_for_conversation(conversation_id)
    return [m.model_dump(mode="json") for m in messages]
