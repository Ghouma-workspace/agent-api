from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import Settings
from app.domain.exceptions.base import AuthenticationError


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class TokenPayload(BaseModel):
    sub: str
    type: TokenType
    exp: datetime
    jti: str


class JWTService:
    """Encodes/decodes access and refresh tokens. Refresh tokens are additionally
    tracked in the `sessions` table so they can be revoked server-side."""

    def __init__(self, settings: Settings) -> None:
        self._secret = settings.jwt_secret_key.get_secret_value()
        self._algorithm = settings.jwt_algorithm
        self._access_ttl = timedelta(minutes=settings.access_token_expire_minutes)
        self._refresh_ttl = timedelta(days=settings.refresh_token_expire_days)

    def _create(self, user_id: UUID, token_type: TokenType, jti: str, ttl: timedelta) -> str:
        now = datetime.now(UTC)
        payload = {
            "sub": str(user_id),
            "type": token_type.value,
            "iat": now,
            "exp": now + ttl,
            "jti": jti,
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def create_access_token(self, user_id: UUID, jti: str) -> str:
        return self._create(user_id, TokenType.ACCESS, jti, self._access_ttl)

    def create_refresh_token(self, user_id: UUID, jti: str) -> str:
        return self._create(user_id, TokenType.REFRESH, jti, self._refresh_ttl)

    def decode(self, token: str) -> TokenPayload:
        try:
            raw = jwt.decode(token, self._secret, algorithms=[self._algorithm])
            return TokenPayload(**raw)
        except JWTError as exc:
            raise AuthenticationError("Invalid or expired token") from exc


class PasswordHasher:
    def __init__(self) -> None:
        from argon2 import PasswordHasher as Argon2Hasher

        self._hasher = Argon2Hasher()

    def hash(self, plain_password: str) -> str:
        return self._hasher.hash(plain_password)

    def verify(self, hashed_password: str, plain_password: str) -> bool:
        from argon2.exceptions import VerifyMismatchError

        try:
            return self._hasher.verify(hashed_password, plain_password)
        except VerifyMismatchError:
            return False
