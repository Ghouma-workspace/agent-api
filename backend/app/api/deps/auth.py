from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.domain.exceptions.base import AuthenticationError
from app.infrastructure.security.jwt import JWTService

_bearer_scheme = HTTPBearer(auto_error=True)


async def get_current_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> UUID:
    jwt_service: JWTService = request.app.state.container.jwt_service
    payload = jwt_service.decode(credentials.credentials)
    if payload.type.value != "access":
        raise AuthenticationError("Access token required")
    return UUID(payload.sub)
