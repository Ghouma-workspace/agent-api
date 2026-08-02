"""Authentication use-case service.

V2 additions:
  - device_id generated on login, stored in session, returned in TokenPair
  - refresh validates device_id matches (session binding)
  - last_seen_ip updated on each successful refresh
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.config import Settings
from app.domain.entities.chat import User
from app.domain.exceptions.base import AuthenticationError
from app.domain.repositories.interfaces import SessionRepository, UserRepository
from app.infrastructure.security.jwt import JWTService, PasswordHasher


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    device_id: str
    token_type: str = "bearer"


class AuthService:
    """Use-case orchestration for authentication. Depends only on repository/provider
    interfaces — never on FastAPI or SQLAlchemy directly."""

    def __init__(
        self,
        user_repo: UserRepository,
        session_repo: SessionRepository,
        jwt_service: JWTService,
        password_hasher: PasswordHasher,
        settings: Settings,
    ) -> None:
        self._users = user_repo
        self._sessions = session_repo
        self._jwt = jwt_service
        self._hasher = password_hasher
        self._settings = settings

    async def register(self, email: str, password: str) -> User:
        existing = await self._users.get_by_email(email)
        if existing is not None:
            raise AuthenticationError("Email already registered")
        hashed = self._hasher.hash(password)
        return await self._users.create(email=email, hashed_password=hashed)

    async def login(self, email: str, password: str) -> TokenPair:
        user = await self._users.get_by_email(email)
        if user is None or not self._hasher.verify(user.hashed_password, password):
            raise AuthenticationError("Invalid email or password")
        device_id = str(uuid4())
        return await self._issue_tokens(user.id, device_id=device_id)

    async def refresh(
        self, refresh_token: str, *, device_id: str | None = None, client_ip: str | None = None
    ) -> TokenPair:
        payload = self._jwt.decode(refresh_token)
        if payload.type.value != "refresh":
            raise AuthenticationError("Not a refresh token")
        if not await self._sessions.is_active(payload.jti):
            raise AuthenticationError("Session has been revoked")

        # V2: validate device binding
        stored_device_id = await self._sessions.get_device_id(payload.jti)
        if stored_device_id is not None and device_id is not None:
            if stored_device_id != device_id:
                raise AuthenticationError("Device ID mismatch — refresh token cannot be used from this device")

        # Update IP before revoking so we capture the last access
        if client_ip and payload.jti:
            await self._sessions.update_last_seen_ip(payload.jti, client_ip)

        await self._sessions.revoke(payload.jti)  # rotate: old refresh token is one-time-use
        return await self._issue_tokens(user_id=payload.sub, device_id=stored_device_id or device_id)

    async def logout(self, refresh_token: str) -> None:
        payload = self._jwt.decode(refresh_token)
        await self._sessions.revoke(payload.jti)

    async def _issue_tokens(self, user_id, *, device_id: str | None = None) -> TokenPair:
        access_jti = str(uuid4())
        refresh_jti = str(uuid4())
        _device_id = device_id or str(uuid4())
        access_token = self._jwt.create_access_token(user_id, access_jti)
        refresh_token = self._jwt.create_refresh_token(user_id, refresh_jti)
        expires_at = datetime.now(UTC) + timedelta(days=self._settings.refresh_token_expire_days)
        await self._sessions.create(
            user_id=user_id, jti=refresh_jti, expires_at=expires_at, device_id=_device_id
        )
        return TokenPair(access_token=access_token, refresh_token=refresh_token, device_id=_device_id)
