"""Tests for ChatService.send_message()'s background-summarization dispatch.

Covers the ruff S110 fix (chat_service.py): a failure to dispatch the Celery
summarization task must be logged, not silently swallowed — and must never
interrupt the chat turn's normal response.

Pure unit tests: fake repositories/graph/langfuse, no DB, no Celery broker, no
network. The Celery `.delay()` call itself is monkeypatched so tests never try
to reach a real broker.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.application.agent.state import AgentState
from app.application.services import chat_service as chat_service_module
from app.application.services.chat_service import ChatService
from app.domain.entities.chat import ChatMessage, Conversation, MessageRole
from app.infrastructure.observability.langfuse_client import LangfuseTracker


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeConversationRepository:
    def __init__(self) -> None:
        self.touched: list[uuid.UUID] = []

    async def get_by_id(self, conversation_id):
        return Conversation(
            id=conversation_id,
            user_id=uuid.uuid4(),
            title="Existing",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    async def list_for_user(self, user_id, limit: int = 50):
        return []

    async def create(self, user_id, title: str):
        return Conversation(
            id=uuid.uuid4(), user_id=user_id, title=title,
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )

    async def touch(self, conversation_id) -> None:
        self.touched.append(conversation_id)


class FakeMessageRepository:
    """`history_size` lets each test control len(history) precisely, since that's
    what gates the 'every 20 messages' summarization trigger."""

    def __init__(self, history_size: int = 0) -> None:
        self.added: list[ChatMessage] = []
        self._history_size = history_size

    async def add(self, message: ChatMessage) -> ChatMessage:
        self.added.append(message)
        return message

    async def list_for_conversation(self, conversation_id):
        return [
            ChatMessage(
                id=uuid.uuid4(), conversation_id=conversation_id, role=MessageRole.USER,
                content=f"msg {i}", created_at=datetime.now(UTC),
            )
            for i in range(self._history_size)
        ]


class FakeAgentGraph:
    def __init__(self, response: dict | None = None) -> None:
        self._response = response or {"draft_response": "hi there", "node_path": ["response_generator"]}

    async def ainvoke(self, state: AgentState) -> dict:
        return self._response


class FakeLogger:
    """Captures structlog-style calls so tests can assert on what was logged
    without depending on structlog's own output formatting/capture machinery."""

    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict]] = []

    def warning(self, event: str, **kwargs) -> None:
        self.warnings.append((event, kwargs))

    def info(self, event: str, **kwargs) -> None:
        pass

    def error(self, event: str, **kwargs) -> None:
        pass


class FakeSummarizeTask:
    """Stands in for the Celery `summarize_conversation` task object."""

    def __init__(self, *, raise_on_delay: Exception | None = None) -> None:
        self.raise_on_delay = raise_on_delay
        self.delay_calls: list[str] = []

    def delay(self, conversation_id: str) -> None:
        self.delay_calls.append(conversation_id)
        if self.raise_on_delay is not None:
            raise self.raise_on_delay


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_logger(monkeypatch: pytest.MonkeyPatch) -> FakeLogger:
    logger = FakeLogger()
    monkeypatch.setattr(chat_service_module, "logger", logger)
    return logger


def _make_chat_service(
    *, history_size: int, agent_response: dict | None = None
) -> tuple[ChatService, FakeConversationRepository, FakeMessageRepository]:
    conversations = FakeConversationRepository()
    messages = FakeMessageRepository(history_size=history_size)
    service = ChatService(
        agent_graph=FakeAgentGraph(agent_response),
        conversation_repo=conversations,
        message_repo=messages,
        langfuse=LangfuseTracker(None),  # no-op client, exercises the real no-client path
    )
    return service, conversations, messages


# ---------------------------------------------------------------------------
# Dispatch-failure handling (the S110 fix)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarization_dispatch_failure_is_logged(
    monkeypatch: pytest.MonkeyPatch, fake_logger: FakeLogger
):
    """A broker error on .delay() must be logged with the conversation id and
    error, not silently discarded."""
    broker_error = ConnectionError("Redis broker unreachable")
    monkeypatch.setattr(
        "app.infrastructure.tasks.summarization.summarize_conversation",
        FakeSummarizeTask(raise_on_delay=broker_error),
    )
    service, _, _ = _make_chat_service(history_size=20)  # 20 % 20 == 0 -> triggers dispatch
    conversation_id = uuid.uuid4()

    await service.send_message(uuid.uuid4(), conversation_id, "hello")

    assert len(fake_logger.warnings) == 1
    event, kwargs = fake_logger.warnings[0]
    assert event == "summarization_dispatch_failed"
    assert kwargs["conversation_id"] == str(conversation_id)
    assert kwargs["error"] == "Redis broker unreachable"


@pytest.mark.asyncio
async def test_summarization_dispatch_failure_does_not_break_the_chat_turn(
    monkeypatch: pytest.MonkeyPatch, fake_logger: FakeLogger
):
    """The whole point of catching the exception: the user still gets their
    reply even if the background summarization dispatch fails."""
    monkeypatch.setattr(
        "app.infrastructure.tasks.summarization.summarize_conversation",
        FakeSummarizeTask(raise_on_delay=RuntimeError("broker down")),
    )
    service, conversations, messages = _make_chat_service(
        history_size=20, agent_response={"draft_response": "still works", "node_path": []}
    )
    conversation_id = uuid.uuid4()

    result = await service.send_message(uuid.uuid4(), conversation_id, "hello")

    assert result["message"].content == "still works"
    assert conversation_id in conversations.touched
    assert len(messages.added) == 2  # user message + assistant message


@pytest.mark.asyncio
async def test_summarization_dispatched_successfully_when_no_error(
    monkeypatch: pytest.MonkeyPatch, fake_logger: FakeLogger
):
    task = FakeSummarizeTask()
    monkeypatch.setattr("app.infrastructure.tasks.summarization.summarize_conversation", task)
    service, _, _ = _make_chat_service(history_size=20)
    conversation_id = uuid.uuid4()

    await service.send_message(uuid.uuid4(), conversation_id, "hello")

    assert task.delay_calls == [str(conversation_id)]
    assert fake_logger.warnings == []  # nothing to log — dispatch succeeded


# ---------------------------------------------------------------------------
# Dispatch gating (len(history) > 0 and len(history) % 20 == 0)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("history_size", [0, 1, 5, 19, 21, 39])
async def test_summarization_not_dispatched_off_the_20_message_boundary(
    monkeypatch: pytest.MonkeyPatch, fake_logger: FakeLogger, history_size: int
):
    task = FakeSummarizeTask()
    monkeypatch.setattr("app.infrastructure.tasks.summarization.summarize_conversation", task)
    service, _, _ = _make_chat_service(history_size=history_size)

    await service.send_message(uuid.uuid4(), uuid.uuid4(), "hello")

    assert task.delay_calls == []
    assert fake_logger.warnings == []


@pytest.mark.asyncio
@pytest.mark.parametrize("history_size", [20, 40, 60])
async def test_summarization_dispatched_exactly_on_the_20_message_boundary(
    monkeypatch: pytest.MonkeyPatch, fake_logger: FakeLogger, history_size: int
):
    task = FakeSummarizeTask()
    monkeypatch.setattr("app.infrastructure.tasks.summarization.summarize_conversation", task)
    service, _, _ = _make_chat_service(history_size=history_size)

    await service.send_message(uuid.uuid4(), uuid.uuid4(), "hello")

    assert len(task.delay_calls) == 1
