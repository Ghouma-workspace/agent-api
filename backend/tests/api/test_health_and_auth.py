import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.main import create_app

_ADMIN_SERVICE_ARITY_BUG = (
    "app/core/container.py calls AdminService(self.llm_usage_repo, container.tool_registry) "
    "but AdminService.__init__ only accepts (tool_registry) — one positional argument too "
    "many. This fires on every request (db_session middleware builds a RequestScope per "
    "request), so it currently 500s /health too, not just authenticated routes. Requires a "
    "source change — not made here per instruction to leave app code untouched."
)


@pytest.mark.asyncio
@pytest.mark.xfail(reason=_ADMIN_SERVICE_ARITY_BUG, strict=True)
async def test_health_endpoint_returns_ok():
    app = create_app()

    async with LifespanManager(app):
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.xfail(reason=_ADMIN_SERVICE_ARITY_BUG, strict=True)
async def test_chat_requires_authentication():
    app = create_app()

    async with LifespanManager(app):
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/chat", json={"content": "hi"})

    assert response.status_code in (401, 403)
