from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.chat import User
from app.infrastructure.db.models.orm import SessionORM, UserORM


def _to_domain(row: UserORM) -> User:
    return User(
        id=row.id,
        email=row.email,
        hashed_password=row.hashed_password,
        is_active=row.is_active,
        created_at=row.created_at,
    )


class SqlAlchemyUserRepository:
    """Implements domain.repositories.interfaces.UserRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        row = await self._session.get(UserORM, user_id)
        return _to_domain(row) if row else None

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(UserORM).where(UserORM.email == email))
        row = result.scalar_one_or_none()
        return _to_domain(row) if row else None

    async def create(self, email: str, hashed_password: str) -> User:
        row = UserORM(email=email, hashed_password=hashed_password)
        self._session.add(row)
        await self._session.flush()
        return _to_domain(row)


class SqlAlchemySessionRepository:
    """Implements domain.repositories.interfaces.SessionRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, user_id: UUID, jti: str, expires_at: datetime, device_id: str | None = None
    ) -> None:
        self._session.add(
            SessionORM(jti=jti, user_id=user_id, expires_at=expires_at, device_id=device_id)
        )
        await self._session.flush()

    async def is_active(self, jti: str) -> bool:
        row = await self._session.get(SessionORM, jti)
        if row is None:
            return False
        return not row.revoked and row.expires_at > datetime.now(row.expires_at.tzinfo)

    async def get_device_id(self, jti: str) -> str | None:
        row = await self._session.get(SessionORM, jti)
        return row.device_id if row else None

    async def update_last_seen_ip(self, jti: str, ip: str) -> None:
        row = await self._session.get(SessionORM, jti)
        if row is not None:
            row.last_seen_ip = ip
            await self._session.flush()

    async def revoke(self, jti: str) -> None:
        row = await self._session.get(SessionORM, jti)
        if row is not None:
            row.revoked = True
            await self._session.flush()

    async def revoke_all_for_user(self, user_id: UUID) -> None:
        result = await self._session.execute(
            select(SessionORM).where(SessionORM.user_id == user_id)
        )
        for row in result.scalars():
            row.revoked = True
        await self._session.flush()
