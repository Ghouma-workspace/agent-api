from uuid import UUID

from pydantic import BaseModel


class SendMessageRequest(BaseModel):
    conversation_id: UUID | None = None
    content: str


class SendMessageResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    role: str
    content: str
    trace_id: str
    duration_ms: float
    node_path: list[str]
