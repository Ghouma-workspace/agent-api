"""Framework-free domain entities. These are NOT SQLAlchemy models — infrastructure
maps ORM rows to/from these at the repository boundary."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class User(BaseModel):
    id: UUID
    email: str
    hashed_password: str
    is_active: bool = True
    created_at: datetime


class Conversation(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ChatMessage(BaseModel):
    id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    created_at: datetime


class ToolCall(BaseModel):
    tool_name: str
    arguments: dict


class ToolResult(BaseModel):
    tool_name: str
    success: bool
    output: dict | None = None
    error: str | None = None
    latency_ms: float = 0.0


class ToolExecution(BaseModel):
    id: UUID
    message_id: UUID
    tool_name: str
    arguments: dict
    result: ToolResult
    created_at: datetime


class LLMUsage(BaseModel):
    id: UUID
    message_id: UUID
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: float
    created_at: datetime


class LLMResponse(BaseModel):
    content: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""


class LLMChunk(BaseModel):
    delta: str
    is_final: bool = False
    tool_calls: list[ToolCall] = Field(default_factory=list)
