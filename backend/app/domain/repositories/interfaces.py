"""Repository ports. Infrastructure/db/repositories provides the SQLAlchemy adapters.
Application services depend only on these Protocols, never on SQLAlchemy directly."""
from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from app.domain.entities.chat import (
    ChatMessage,
    Conversation,
    LLMUsage,
    ToolExecution,
    User,
)


@runtime_checkable
class UserRepository(Protocol):
    async def get_by_id(self, user_id: UUID) -> User | None: ...
    async def get_by_email(self, email: str) -> User | None: ...
    async def create(self, email: str, hashed_password: str) -> User: ...


@runtime_checkable
class ConversationRepository(Protocol):
    async def get_by_id(self, conversation_id: UUID) -> Conversation | None: ...
    async def list_for_user(self, user_id: UUID, limit: int = 50) -> list[Conversation]: ...
    async def create(self, user_id: UUID, title: str) -> Conversation: ...
    async def touch(self, conversation_id: UUID) -> None: ...


@runtime_checkable
class MessageRepository(Protocol):
    async def add(self, message: ChatMessage) -> ChatMessage: ...
    async def list_for_conversation(self, conversation_id: UUID) -> list[ChatMessage]: ...


@runtime_checkable
class ToolExecutionRepository(Protocol):
    async def add(self, execution: ToolExecution) -> ToolExecution: ...
    async def list_for_message(self, message_id: UUID) -> list[ToolExecution]: ...


@runtime_checkable
class LLMUsageRepository(Protocol):
    async def add(self, usage: LLMUsage) -> LLMUsage: ...
    async def daily_cost(self, user_id: UUID | None = None) -> float: ...


@runtime_checkable
class SessionRepository(Protocol):
    """Tracks refresh-token sessions so they can be revoked independently of JWT expiry."""

    async def create(self, user_id: UUID, jti: str, expires_at) -> None: ...
    async def is_active(self, jti: str) -> bool: ...
    async def revoke(self, jti: str) -> None: ...
    async def revoke_all_for_user(self, user_id: UUID) -> None: ...
