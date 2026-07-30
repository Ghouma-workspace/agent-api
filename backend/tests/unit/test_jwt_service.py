import uuid

import pytest

from app.domain.exceptions.base import AuthenticationError
from app.infrastructure.security.jwt import JWTService, TokenType


def test_access_token_round_trips(settings):
    jwt_service = JWTService(settings)
    user_id = uuid.uuid4()
    jti = str(uuid.uuid4())

    token = jwt_service.create_access_token(user_id, jti)
    payload = jwt_service.decode(token)

    assert payload.sub == str(user_id)
    assert payload.type == TokenType.ACCESS
    assert payload.jti == jti


def test_refresh_token_has_refresh_type(settings):
    jwt_service = JWTService(settings)
    token = jwt_service.create_refresh_token(uuid.uuid4(), str(uuid.uuid4()))
    payload = jwt_service.decode(token)
    assert payload.type == TokenType.REFRESH


def test_decode_rejects_garbage_token(settings):
    jwt_service = JWTService(settings)
    with pytest.raises(AuthenticationError):
        jwt_service.decode("not-a-real-token")


def test_decode_rejects_token_signed_with_different_secret(settings):
    jwt_service_a = JWTService(settings)
    settings.jwt_secret_key = type(settings.jwt_secret_key)("a-different-secret")
    jwt_service_b = JWTService(settings)

    token = jwt_service_a.create_access_token(uuid.uuid4(), str(uuid.uuid4()))
    with pytest.raises(AuthenticationError):
        jwt_service_b.decode(token)
