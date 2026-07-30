from fastapi import APIRouter, Depends

from app.api.deps.services import get_auth_service
from app.api.v1.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.application.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    body: RegisterRequest, auth_service: AuthService = Depends(get_auth_service)
) -> UserResponse:
    user = await auth_service.register(body.email, body.password)
    return UserResponse(id=str(user.id), email=user.email)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, auth_service: AuthService = Depends(get_auth_service)
) -> TokenResponse:
    tokens = await auth_service.login(body.email, body.password)
    return TokenResponse(**tokens.__dict__)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest, auth_service: AuthService = Depends(get_auth_service)
) -> TokenResponse:
    tokens = await auth_service.refresh(body.refresh_token)
    return TokenResponse(**tokens.__dict__)


@router.post("/logout", status_code=204)
async def logout(
    body: RefreshRequest, auth_service: AuthService = Depends(get_auth_service)
) -> None:
    await auth_service.logout(body.refresh_token)
