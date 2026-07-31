"""Every Depends() here reaches into either the singleton container (app.state.container,
for things like the tool registry and LLM provider) or the per-request scope
(request.state.scope, built fresh per request by DBSessionMiddleware, for anything
DB-backed). Routers never construct services themselves."""

from fastapi import Request

from app.application.services.admin_service import AdminService
from app.application.services.auth_service import AuthService
from app.application.services.chat_service import ChatService
from app.application.services.tool_service import ToolService


def get_auth_service(request: Request) -> AuthService:
    return request.state.scope.auth_service


def get_chat_service(request: Request) -> ChatService:
    return request.state.scope.chat_service


def get_tool_service(request: Request) -> ToolService:
    return request.app.state.container.tool_service


def get_admin_service(request: Request) -> AdminService:
    return request.state.scope.admin_service
