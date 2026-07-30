from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.exceptions.base import (
    AuthenticationError,
    AuthorizationError,
    DomainError,
    LLMProviderError,
    NotFoundError,
    RateLimitExceededError,
    ToolExecutionError,
    ValidationError,
)

_STATUS_MAP: dict[type[DomainError], int] = {
    NotFoundError: 404,
    AuthenticationError: 401,
    AuthorizationError: 403,
    ValidationError: 422,
    RateLimitExceededError: 429,
    ToolExecutionError: 502,
    LLMProviderError: 502,
}


def _problem_detail(request: Request, status: int, title: str, detail: str) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", None)
    return JSONResponse(
        status_code=status,
        content={
            "type": f"https://errors.ai-api-assistant/{title.lower().replace(' ', '-')}",
            "title": title,
            "status": status,
            "detail": detail,
            "trace_id": trace_id,
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        status = 500
        for exc_type, mapped_status in _STATUS_MAP.items():
            if isinstance(exc, exc_type):
                status = mapped_status
                break
        return _problem_detail(request, status, type(exc).__name__, str(exc))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        return _problem_detail(
            request, 500, "InternalServerError", "An unexpected error occurred."
        )
