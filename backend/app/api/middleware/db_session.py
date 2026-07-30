from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class DBSessionMiddleware(BaseHTTPMiddleware):
    """Opens one AsyncSession per request, builds a RequestScope (repositories +
    services bound to that session) on request.state.scope, and commits/rolls back
    around the handler. Keeps routers oblivious to session lifecycle entirely."""

    async def dispatch(self, request: Request, call_next):
        container = request.app.state.container
        async with container.session_factory() as session:
            request.state.scope = container.request_scope(session)
            try:
                response = await call_next(request)
                await session.commit()
                return response
            except Exception:
                await session.rollback()
                raise
