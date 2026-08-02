"""Section 8 tests — JWT hardening: audience claim, device_id binding.

Pure unit tests. No DB, no Redis.
"""

from __future__ import annotations

import uuid

import pytest
from jose import jwt as jose_jwt

from app.core.config import Settings
from app.domain.exceptions.base import AuthenticationError
from app.infrastructure.security.jwt import JWTService, _AUDIENCE


@pytest.fixture
def jwt_service(settings: Settings) -> JWTService:
    return JWTService(settings)


# ---------------------------------------------------------------------------
# Audience claim is present
# ---------------------------------------------------------------------------


def test_access_token_contains_aud_claim(jwt_service: JWTService, settings: Settings):
    token = jwt_service.create_access_token(uuid.uuid4(), str(uuid.uuid4()))
    raw = jose_jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
        audience=_AUDIENCE,
    )
    assert raw["aud"] == _AUDIENCE


def test_refresh_token_contains_aud_claim(jwt_service: JWTService, settings: Settings):
    token = jwt_service.create_refresh_token(uuid.uuid4(), str(uuid.uuid4()))
    raw = jose_jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
        audience=_AUDIENCE,
    )
    assert raw["aud"] == _AUDIENCE


# ---------------------------------------------------------------------------
# Audience validation on decode
# ---------------------------------------------------------------------------


def test_decode_rejects_token_with_wrong_audience(settings: Settings):
    """A token signed with the right secret but wrong aud must be rejected."""
    user_id = uuid.uuid4()
    from datetime import UTC, datetime, timedelta

    payload = {
        "sub": str(user_id),
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=15),
        "aud": "wrong-audience",
    }
    bad_token = jose_jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    svc = JWTService(settings)
    with pytest.raises(AuthenticationError):
        svc.decode(bad_token)


def test_decode_accepts_token_with_correct_audience(jwt_service: JWTService):
    user_id = uuid.uuid4()
    jti = str(uuid.uuid4())
    token = jwt_service.create_access_token(user_id, jti)
    payload = jwt_service.decode(token)
    assert payload.sub == str(user_id)
    assert payload.aud == _AUDIENCE


def test_decode_rejects_token_missing_aud_claim(settings: Settings):
    """A token without aud must be rejected after V2 hardening."""
    from datetime import UTC, datetime, timedelta

    payload = {
        "sub": str(uuid.uuid4()),
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=15),
        # No "aud" field
    }
    no_aud_token = jose_jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    svc = JWTService(settings)
    with pytest.raises(AuthenticationError):
        svc.decode(no_aud_token)


# ---------------------------------------------------------------------------
# Backward compat: existing decode tests still pass
# ---------------------------------------------------------------------------


def test_access_token_round_trips(jwt_service: JWTService):
    user_id = uuid.uuid4()
    jti = str(uuid.uuid4())
    token = jwt_service.create_access_token(user_id, jti)
    payload = jwt_service.decode(token)
    assert payload.sub == str(user_id)
    assert payload.jti == jti
    assert payload.type.value == "access"


def test_refresh_token_has_refresh_type(jwt_service: JWTService):
    user_id = uuid.uuid4()
    token = jwt_service.create_refresh_token(user_id, str(uuid.uuid4()))
    payload = jwt_service.decode(token)
    assert payload.type.value == "refresh"


def test_decode_rejects_garbage_token(jwt_service: JWTService):
    with pytest.raises(AuthenticationError):
        jwt_service.decode("not.a.token")


def test_decode_rejects_token_signed_with_different_secret(settings: Settings):
    other_svc = JWTService(
        Settings(
            jwt_secret_key="different-secret",
            database_url=settings.database_url,
            redis_url=settings.redis_url,
            groq_api_key="x",
        )
    )
    token = other_svc.create_access_token(uuid.uuid4(), str(uuid.uuid4()))
    svc = JWTService(settings)
    with pytest.raises(AuthenticationError):
        svc.decode(token)
