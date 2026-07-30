from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.exception_handlers import register_exception_handlers
from app.api.middleware.db_session import DBSessionMiddleware
from app.api.v1.routers import admin, auth, chat, conversations, tools, users
from app.core.config import get_settings
from app.core.container import Container
from app.infrastructure.observability.logging import RequestContextMiddleware, setup_logging
from app.infrastructure.observability.prometheus_setup import setup_prometheus
from app.infrastructure.observability.tracing import instrument_fastapi, setup_tracing


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings)
    tracer_provider = setup_tracing(settings)
    app.state.container = Container(settings)
    instrument_fastapi(app, tracer_provider)
    yield
    await app.state.container.redis.aclose()
    await app.state.container.engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    register_exception_handlers(app)
    setup_prometheus(app, settings)

    # Order matters: request-context (request_id/trace_id) must wrap DB-session scope
    # so every log line inside the DB-bound work also carries request_id/trace_id.
    app.add_middleware(DBSessionMiddleware)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(auth.router, prefix=settings.api_v1_prefix)
    app.include_router(chat.router, prefix=settings.api_v1_prefix)
    app.include_router(conversations.router, prefix=settings.api_v1_prefix)
    app.include_router(tools.router, prefix=settings.api_v1_prefix)
    app.include_router(users.router, prefix=settings.api_v1_prefix)
    app.include_router(admin.router, prefix=settings.api_v1_prefix)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
