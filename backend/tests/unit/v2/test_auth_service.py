"""Section 8 tests — AuthService.refresh() device-id binding.

Covers the ruff SIM102 fix (collapsed nested-if device comparison in
auth_service.py). Behavior must be identical to before the fix:
  - stored_device_id is None            -> no check, refresh succeeds
  - device_id (request) is None          -> no check, refresh succeeds
  - both present and equal               -> refresh succeeds
  - both present and different           -> AuthenticationError

Pure unit tests: fake repositories, real JWTService (no network / no DB).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.domain.exceptions.base import AuthenticationError
from app.infrastructure.security.jwt import JWTService, PasswordHasher
from app.application.services.auth_service import AuthService


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeUserRepository:
    """Unused by refresh(), but required by AuthService's constructor signature."""

    async def get_by_id(self, user_id):
        return None

    async def get_by_email(self, email):
        return None

    async def create(self, email, hashed_password):
        raise NotImplementedError


class FakeSessionRepository:
    """In-memory stand-in for SqlAlchemySessionRepository."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}

    async def create(self, user_id, jti: str, expires_at, device_id: str | None = None) -> None:
        self._sessions[jti] = {
            "user_id": user_id,
            "expires_at": expires_at,
            "device_id": device_id,
            "revoked": False,
            "last_seen_ip": None,
        }

    async def is_active(self, jti: str) -> bool:
        row = self._sessions.get(jti)
        return row is not None and not row["revoked"]

    async def get_device_id(self, jti: str) -> str | None:
        row = self._sessions.get(jti)
        return row["device_id"] if row else None

    async def update_last_seen_ip(self, jti: str, ip: str) -> None:
        if jti in self._sessions:
            self._sessions[jti]["last_seen_ip"] = ip

    async def revoke(self, jti: str) -> None:
        if jti in self._sessions:
            self._sessions[jti]["revoked"] = True

    async def revoke_all_for_user(self, user_id) -> None:
        for row in self._sessions.values():
            if row["user_id"] == user_id:
                row["revoked"] = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sessions() -> FakeSessionRepository:
    return FakeSessionRepository()


@pytest.fixture
def auth_service(settings: Settings, sessions: FakeSessionRepository) -> AuthService:
    return AuthService(
        user_repo=FakeUserRepository(),
        session_repo=sessions,
        jwt_service=JWTService(settings),
        password_hasher=PasswordHasher(),
        settings=settings,
    )


async def _seed_refresh_session(
    auth_service: AuthService,
    sessions: FakeSessionRepository,
    *,
    device_id: str | None,
) -> tuple[str, str]:
    """Directly seeds a session + mints a matching refresh token, bypassing login()
    so each test can control the stored device_id precisely."""
    user_id = uuid.uuid4()
    jti = str(uuid.uuid4())
    refresh_token = auth_service._jwt.create_refresh_token(user_id, jti)
    await sessions.create(
        user_id=user_id,
        jti=jti,
        expires_at=datetime.now(UTC) + timedelta(days=7),
        device_id=device_id,
    )
    return refresh_token, jti


# ---------------------------------------------------------------------------
# Device binding matrix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_succeeds_when_stored_device_id_is_none(
    auth_service: AuthService, sessions: FakeSessionRepository
):
    """No device_id was ever stored (e.g. pre-V2 session) — no binding check applies."""
    refresh_token, _ = await _seed_refresh_session(auth_service, sessions, device_id=None)
    result = await auth_service.refresh(refresh_token, device_id="device-abc")
    assert result.access_token


@pytest.mark.asyncio
async def test_refresh_succeeds_when_request_device_id_is_none(
    auth_service: AuthService, sessions: FakeSessionRepository
):
    """Caller didn't supply a device_id on this refresh call — no binding check applies."""
    refresh_token, _ = await _seed_refresh_session(auth_service, sessions, device_id="device-abc")
    result = await auth_service.refresh(refresh_token, device_id=None)
    assert result.access_token


@pytest.mark.asyncio
async def test_refresh_succeeds_when_device_ids_match(
    auth_service: AuthService, sessions: FakeSessionRepository
):
    refresh_token, _ = await _seed_refresh_session(auth_service, sessions, device_id="device-abc")
    result = await auth_service.refresh(refresh_token, device_id="device-abc")
    assert result.access_token
    assert result.device_id == "device-abc"


@pytest.mark.asyncio
async def test_refresh_rejects_mismatched_device_id(
    auth_service: AuthService, sessions: FakeSessionRepository
):
    """The core case the SIM102-fixed condition guards: both present and different."""
    refresh_token, _ = await _seed_refresh_session(auth_service, sessions, device_id="device-abc")
    with pytest.raises(AuthenticationError, match="Device ID mismatch"):
        await auth_service.refresh(refresh_token, device_id="device-xyz")


@pytest.mark.asyncio
async def test_refresh_rotates_token_and_revokes_old_session_on_success(
    auth_service: AuthService, sessions: FakeSessionRepository
):
    refresh_token, old_jti = await _seed_refresh_session(
        auth_service, sessions, device_id="device-abc"
    )
    await auth_service.refresh(refresh_token, device_id="device-abc")
    assert await sessions.is_active(old_jti) is False  # rotated: old token is one-time-use


@pytest.mark.asyncio
async def test_refresh_updates_last_seen_ip_on_success(
    auth_service: AuthService, sessions: FakeSessionRepository
):
    refresh_token, jti = await _seed_refresh_session(auth_service, sessions, device_id=None)
    await auth_service.refresh(refresh_token, device_id=None, client_ip="203.0.113.5")
    assert sessions._sessions[jti]["last_seen_ip"] == "203.0.113.5"


@pytest.mark.asyncio
async def test_refresh_rejects_revoked_session(
    auth_service: AuthService, sessions: FakeSessionRepository
):
    refresh_token, jti = await _seed_refresh_session(auth_service, sessions, device_id=None)
    await sessions.revoke(jti)
    with pytest.raises(AuthenticationError, match="Session has been revoked"):
        await auth_service.refresh(refresh_token)


@pytest.mark.asyncio
async def test_refresh_rejects_access_token_used_as_refresh_token(
    auth_service: AuthService, sessions: FakeSessionRepository
):
    user_id = uuid.uuid4()
    access_token = auth_service._jwt.create_access_token(user_id, str(uuid.uuid4()))
    with pytest.raises(AuthenticationError, match="Not a refresh token"):
        await auth_service.refresh(access_token)
