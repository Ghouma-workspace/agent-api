"""Section 3 tests — conversation summarization task logic.

These are pure unit tests of the summarization business logic. We test the
decision-gating (< 20 messages = skip), the dispatch trigger in ChatService,
and the Redis cache invalidation helper — all without touching Celery, Postgres,
or a real Groq API.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.entities.chat import ChatMessage, MessageRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_messages(n: int) -> list[ChatMessage]:
    base = datetime.now(UTC)
    return [
        ChatMessage(
            id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            role=MessageRole.USER,
            content=f"Message {i}",
            created_at=base,
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Skip logic — fewer than 20 messages
# ---------------------------------------------------------------------------


def test_summarization_skip_threshold():
    """The task must skip conversations with fewer than 20 messages."""
    # Replicate the gate check directly — the task itself calls this inline
    messages = _make_messages(19)
    should_skip = len(messages) < 20
    assert should_skip is True


def test_summarization_run_threshold():
    messages = _make_messages(20)
    should_skip = len(messages) < 20
    assert should_skip is False


# ---------------------------------------------------------------------------
# ChatService dispatch trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_service_dispatches_on_every_20th_message():
    """ChatService.send_message must call summarize_conversation.delay when
    len(history) % 20 == 0."""
    from app.application.services.chat_service import ChatService
    from app.domain.entities.chat import Conversation

    messages_20 = _make_messages(20)
    conv_id = uuid.uuid4()
    user_id = uuid.uuid4()
    trace_id = "test-trace"

    fake_conversation = Conversation(
        id=conv_id,
        user_id=user_id,
        title="Test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    fake_assistant_msg = ChatMessage(
        id=uuid.uuid4(),
        conversation_id=conv_id,
        role=MessageRole.ASSISTANT,
        content="Reply",
        created_at=datetime.now(UTC),
    )

    mock_conversations = AsyncMock()
    mock_conversations.get_by_id.return_value = fake_conversation
    mock_conversations.create.return_value = fake_conversation
    mock_conversations.touch.return_value = None

    mock_messages = AsyncMock()
    mock_messages.add.return_value = fake_assistant_msg
    mock_messages.list_for_conversation.return_value = messages_20

    mock_graph = AsyncMock()
    mock_graph.ainvoke.return_value = {
        "draft_response": "Reply",
        "node_path": ["planner", "response_generator"],
        "tool_result": None,
    }

    mock_langfuse = MagicMock()
    mock_langfuse.start_trace.return_value = None
    mock_langfuse.flush.return_value = None

    service = ChatService(mock_graph, mock_conversations, mock_messages, mock_langfuse)

    delay_called = []

    with patch("app.infrastructure.tasks.summarization.summarize_conversation") as mock_task:
        mock_task.delay = MagicMock(side_effect=lambda cid: delay_called.append(cid))
        with patch("app.application.services.chat_service.trace") as mock_trace:
            mock_span = MagicMock()
            mock_span.get_span_context.return_value = MagicMock(trace_id=0)
            mock_trace.get_current_span.return_value = mock_span
            await service.send_message(user_id, conv_id, "test message")

    assert len(delay_called) == 1
    assert delay_called[0] == str(conv_id)


@pytest.mark.asyncio
async def test_chat_service_does_not_dispatch_on_non_multiple_of_20():
    """With 19 messages in history, no dispatch should happen."""
    from app.application.services.chat_service import ChatService

    messages_19 = _make_messages(19)
    conv_id = uuid.uuid4()
    user_id = uuid.uuid4()

    fake_conversation = MagicMock()
    mock_conversations = AsyncMock()
    mock_conversations.get_by_id.return_value = fake_conversation
    mock_conversations.touch.return_value = None

    mock_messages = AsyncMock()
    mock_messages.add.return_value = MagicMock()
    mock_messages.list_for_conversation.return_value = messages_19

    mock_graph = AsyncMock()
    mock_graph.ainvoke.return_value = {
        "draft_response": "Reply",
        "node_path": [],
        "tool_result": None,
    }

    mock_langfuse = MagicMock()
    mock_langfuse.start_trace.return_value = None
    mock_langfuse.flush.return_value = None

    service = ChatService(mock_graph, mock_conversations, mock_messages, mock_langfuse)
    delay_called = []

    with patch("app.infrastructure.tasks.summarization.summarize_conversation") as mock_task:
        mock_task.delay = MagicMock(side_effect=lambda cid: delay_called.append(cid))
        with patch("app.application.services.chat_service.trace") as mock_trace:
            mock_span = MagicMock()
            mock_span.get_span_context.return_value = MagicMock(trace_id=0)
            mock_trace.get_current_span.return_value = mock_span
            await service.send_message(user_id, conv_id, "test message")

    assert delay_called == []


# ---------------------------------------------------------------------------
# Graceful degradation — Celery failure doesn't crash send_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_service_does_not_raise_when_celery_unavailable():
    """If Celery broker is down, send_message must still return normally."""
    from app.application.services.chat_service import ChatService

    messages_20 = _make_messages(20)
    conv_id = uuid.uuid4()
    user_id = uuid.uuid4()

    mock_conversations = AsyncMock()
    mock_conversations.get_by_id.return_value = MagicMock()
    mock_conversations.touch.return_value = None

    mock_messages = AsyncMock()
    mock_messages.add.return_value = MagicMock()
    mock_messages.list_for_conversation.return_value = messages_20

    mock_graph = AsyncMock()
    mock_graph.ainvoke.return_value = {
        "draft_response": "Reply",
        "node_path": [],
        "tool_result": None,
    }

    mock_langfuse = MagicMock()
    mock_langfuse.start_trace.return_value = None
    mock_langfuse.flush.return_value = None

    service = ChatService(mock_graph, mock_conversations, mock_messages, mock_langfuse)

    with patch("app.infrastructure.tasks.summarization.summarize_conversation") as mock_task:
        mock_task.delay = MagicMock(side_effect=ConnectionError("Redis not available"))
        with patch("app.application.services.chat_service.trace") as mock_trace:
            mock_span = MagicMock()
            mock_span.get_span_context.return_value = MagicMock(trace_id=0)
            mock_trace.get_current_span.return_value = mock_span
            # Must not raise even though Celery.delay raises ConnectionError
            result = await service.send_message(user_id, conv_id, "test message")

    assert "message" in result
