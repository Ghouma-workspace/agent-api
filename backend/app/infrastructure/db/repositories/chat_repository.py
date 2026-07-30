from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.chat import (
    ChatMessage,
    Conversation,
    LLMUsage,
    MessageRole,
    ToolExecution,
    ToolResult,
)
from app.infrastructure.db.models.orm import (
    ConversationORM,
    LLMUsageORM,
    MessageORM,
    ToolExecutionORM,
)


class SqlAlchemyConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        row = await self._session.get(ConversationORM, conversation_id)
        return self._to_domain(row) if row else None

    async def list_for_user(self, user_id: UUID, limit: int = 50) -> list[Conversation]:
        result = await self._session.execute(
            select(ConversationORM)
            .where(ConversationORM.user_id == user_id)
            .order_by(ConversationORM.updated_at.desc())
            .limit(limit)
        )
        return [self._to_domain(row) for row in result.scalars()]

    async def create(self, user_id: UUID, title: str) -> Conversation:
        row = ConversationORM(user_id=user_id, title=title)
        self._session.add(row)
        await self._session.flush()
        return self._to_domain(row)

    async def touch(self, conversation_id: UUID) -> None:
        row = await self._session.get(ConversationORM, conversation_id)
        if row is not None:
            await self._session.flush()

    @staticmethod
    def _to_domain(row: ConversationORM) -> Conversation:
        return Conversation(
            id=row.id,
            user_id=row.user_id,
            title=row.title,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class SqlAlchemyMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, message: ChatMessage) -> ChatMessage:
        row = MessageORM(
            id=message.id,
            conversation_id=message.conversation_id,
            role=message.role.value,
            content=message.content,
        )
        self._session.add(row)
        await self._session.flush()
        return message

    async def list_for_conversation(self, conversation_id: UUID) -> list[ChatMessage]:
        result = await self._session.execute(
            select(MessageORM)
            .where(MessageORM.conversation_id == conversation_id)
            .order_by(MessageORM.created_at.asc())
        )
        return [
            ChatMessage(
                id=row.id,
                conversation_id=row.conversation_id,
                role=MessageRole(row.role),
                content=row.content,
                created_at=row.created_at,
            )
            for row in result.scalars()
        ]


class SqlAlchemyToolExecutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, execution: ToolExecution) -> ToolExecution:
        row = ToolExecutionORM(
            id=execution.id,
            message_id=execution.message_id,
            tool_name=execution.tool_name,
            arguments=execution.arguments,
            success=execution.result.success,
            output=execution.result.output,
            error=execution.result.error,
            latency_ms=execution.result.latency_ms,
        )
        self._session.add(row)
        await self._session.flush()
        return execution

    async def list_for_message(self, message_id: UUID) -> list[ToolExecution]:
        result = await self._session.execute(
            select(ToolExecutionORM).where(ToolExecutionORM.message_id == message_id)
        )
        return [
            ToolExecution(
                id=row.id,
                message_id=row.message_id,
                tool_name=row.tool_name,
                arguments=row.arguments,
                result=ToolResult(
                    tool_name=row.tool_name,
                    success=row.success,
                    output=row.output,
                    error=row.error,
                    latency_ms=row.latency_ms,
                ),
                created_at=row.created_at,
            )
            for row in result.scalars()
        ]


class SqlAlchemyLLMUsageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, usage: LLMUsage) -> LLMUsage:
        row = LLMUsageORM(
            id=usage.id,
            message_id=usage.message_id,
            provider=usage.provider,
            model=usage.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cost_usd=usage.cost_usd,
            latency_ms=usage.latency_ms,
        )
        self._session.add(row)
        await self._session.flush()
        return usage

    async def daily_cost(self, user_id: UUID | None = None) -> float:
        query = select(func.coalesce(func.sum(LLMUsageORM.cost_usd), 0.0)).where(
            func.date(LLMUsageORM.created_at) == func.current_date()
        )
        result = await self._session.execute(query)
        return float(result.scalar_one())
