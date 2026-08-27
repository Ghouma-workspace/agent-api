"""Tests for GroqProvider.complete()'s request-kwargs construction.

Covers the ruff C408 fix (groq_provider.py): `dict(...)` was rewritten as a
dict literal. Purely mechanical, but this test locks in that the resulting
kwargs are byte-for-byte identical in shape and behavior — including the
conditional `response_format` key that's only added when the caller passes
one, which is the part most likely to regress in a careless rewrite.

Pure unit tests: the real GroqProvider is constructed (safe — the AsyncGroq
SDK does not touch the network on init), but its `.chat.completions.create`
is swapped for a fake that just records the kwargs it received.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.domain.entities.chat import ChatMessage, MessageRole
from app.infrastructure.llm.groq_provider import GroqProvider


def _make_settings() -> Settings:
    return Settings(
        jwt_secret_key="test-secret",
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/test",
        redis_url="redis://localhost:6379/0",
        groq_api_key="test-key",
        groq_model="llama-3.3-70b-versatile",
    )


def _make_message(content: str = "hello") -> ChatMessage:
    return ChatMessage(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        role=MessageRole.USER,
        content=content,
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Fake Groq SDK surface
# ---------------------------------------------------------------------------


class _FakeUsage:
    def __init__(self, prompt_tokens: int = 10, completion_tokens: int = 5) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeMessage:
    def __init__(self, content: str = "hi", tool_calls=None) -> None:
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeChoice:
    def __init__(self, message: _FakeMessage) -> None:
        self.message = message


class _FakeResponse:
    def __init__(self, content: str = "hi") -> None:
        self.choices = [_FakeChoice(_FakeMessage(content))]
        self.usage = _FakeUsage()


class _FakeCompletions:
    def __init__(self) -> None:
        self.received_kwargs: dict | None = None

    async def create(self, **kwargs):
        self.received_kwargs = kwargs
        return _FakeResponse()


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()


@pytest.fixture
def provider() -> tuple[GroqProvider, _FakeChat]:
    p = GroqProvider(_make_settings())
    fake_chat = _FakeChat()
    p._client.chat = fake_chat  # swap the real Groq client's chat namespace for a fake
    return p, fake_chat


# ---------------------------------------------------------------------------
# create_kwargs shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_kwargs_has_expected_keys_without_response_format(
    provider: tuple[GroqProvider, _FakeChat],
):
    p, fake_chat = provider
    await p.complete([_make_message()])

    kwargs = fake_chat.completions.received_kwargs
    assert kwargs.keys() == {"model", "messages", "tools", "timeout"}
    assert kwargs["model"] == "llama-3.3-70b-versatile"
    assert kwargs["tools"] is None
    assert kwargs["messages"] == [{"role": "user", "content": "hello"}]


@pytest.mark.asyncio
async def test_response_format_key_added_only_when_provided(
    provider: tuple[GroqProvider, _FakeChat],
):
    p, fake_chat = provider
    await p.complete([_make_message()], response_format={"type": "json_object"})

    kwargs = fake_chat.completions.received_kwargs
    assert kwargs.keys() == {"model", "messages", "tools", "timeout", "response_format"}
    assert kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_tools_passed_through_when_provided(provider: tuple[GroqProvider, _FakeChat]):
    p, fake_chat = provider
    schema = [{"type": "function", "function": {"name": "weather"}}]
    await p.complete([_make_message()], tools=schema)

    assert fake_chat.completions.received_kwargs["tools"] == schema


@pytest.mark.asyncio
async def test_multiple_messages_translated_in_order(provider: tuple[GroqProvider, _FakeChat]):
    p, fake_chat = provider
    messages = [_make_message("first"), _make_message("second")]
    await p.complete(messages)

    assert fake_chat.completions.received_kwargs["messages"] == [
        {"role": "user", "content": "first"},
        {"role": "user", "content": "second"},
    ]


# ---------------------------------------------------------------------------
# Response parsing still works with the rebuilt kwargs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_returns_llm_response_from_fake(provider: tuple[GroqProvider, _FakeChat]):
    p, fake_chat = provider
    fake_chat.completions_response_content = "answer"  # not read, just documents intent
    result = await p.complete([_make_message()])

    assert result.content == "hi"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert result.model == "llama-3.3-70b-versatile"
