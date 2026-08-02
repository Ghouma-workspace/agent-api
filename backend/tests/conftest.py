import pytest

from app.core.config import Settings
from app.domain.entities.chat import LLMResponse


class FakeLLMProvider:
    """Deterministic stand-in for GroqProvider so agent/unit tests never hit the network."""

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self._responses = responses or [LLMResponse(content="DIRECT")]
        self._calls = 0

    async def complete(self, messages, tools=None, response_format=None, **kwargs):
        response = self._responses[min(self._calls, len(self._responses) - 1)]
        self._calls += 1
        return response

    async def stream(self, messages, tools=None, **kwargs):
        yield_content = self._responses[0].content
        yield type("Chunk", (), {"delta": yield_content, "is_final": True, "tool_calls": []})()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        jwt_secret_key="test-secret",
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/test",
        redis_url="redis://localhost:6379/0",
        groq_api_key="test-key",
    )


@pytest.fixture
def fake_llm() -> FakeLLMProvider:
    return FakeLLMProvider()
