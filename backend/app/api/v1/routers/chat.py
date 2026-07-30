from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps.auth import get_current_user_id
from app.api.deps.services import get_chat_service
from app.api.v1.schemas.chat import SendMessageRequest, SendMessageResponse
from app.application.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=SendMessageResponse)
async def send_message(
    body: SendMessageRequest,
    user_id: UUID = Depends(get_current_user_id),
    chat_service: ChatService = Depends(get_chat_service),
) -> SendMessageResponse:
    conversation = await chat_service.get_or_create_conversation(user_id, body.conversation_id)
    result = await chat_service.send_message(user_id, conversation.id, body.content)
    message = result["message"]
    return SendMessageResponse(
        conversation_id=conversation.id,
        message_id=message.id,
        role=message.role.value,
        content=message.content,
        trace_id=result["trace_id"],
        duration_ms=result["duration_ms"],
        node_path=result["node_path"],
    )
