import pytest
from httpx import ASGITransport, AsyncClient
from asgi_lifespan import LifespanManager

from app.main import create_app


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok():
    app = create_app()

    async with LifespanManager(app):
        transport = ASGITransport(app=app)

        async with AsyncClient(
            transport=transport,
            base_url="http://test"
        ) as client:
            response = await client.get("/health")

    assert response.status_code == 200

@pytest.mark.asyncio
async def test_chat_requires_authentication():
    app = create_app()

    async with LifespanManager(app):
        transport = ASGITransport(app=app)

        async with AsyncClient(
            transport=transport,
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/chat",
                json={"content": "hi"}
            )

    assert response.status_code in (401, 403)
