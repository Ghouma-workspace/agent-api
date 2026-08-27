from __future__ import annotations

import time
import uuid
from uuid import UUID

import structlog
from opentelemetry import trace

from app.application.agent.state import AgentState
from app.domain.entities.chat import ChatMessage, Conversation, MessageRole
from app.domain.repositories.interfaces import (
    ConversationRepository,
    MessageRepository,
)
from app.infrastructure.observability.agent_tracing import set_current_langfuse_trace
from app.infrastructure.observability.langfuse_client import LangfuseTracker
from app.infrastructure.observability.metrics import ACTIVE_USERS

logger = structlog.get_logger()

tracer = trace.get_tracer("ai-api-assistant.chat")

# Track unique users active in the last 5 minutes using a simple in-process set.
# For multi-process deployments this would move to Redis — sufficient for local dev.
import time as _time

_active_users: dict[str, float] = {}   # user_id -> last_seen timestamp
_ACTIVE_WINDOW = 300                    # 5 minutes


def _record_active_user(user_id: str) -> None:
    now = _time.time()
    _active_users[user_id] = now
    # Evict stale entries
    cutoff = now - _ACTIVE_WINDOW
    stale = [uid for uid, ts in _active_users.items() if ts < cutoff]
    for uid in stale:
        del _active_users[uid]
    ACTIVE_USERS.set(len(_active_users))


class ChatService:
    def __init__(
        self,
        agent_graph,
        conversation_repo: ConversationRepository,
        message_repo: MessageRepository,
        langfuse: LangfuseTracker,
    ) -> None:
        self._graph = agent_graph
        self._conversations = conversation_repo
        self._messages = message_repo
        self._langfuse = langfuse

    async def get_or_create_conversation(
        self, user_id: UUID, conversation_id: UUID | None
    ) -> Conversation:
        if conversation_id is not None:
            existing = await self._conversations.get_by_id(conversation_id)
            if existing is not None:
                return existing
        return await self._conversations.create(user_id=user_id, title="New conversation")

    async def send_message(self, user_id: UUID, conversation_id: UUID, content: str) -> dict:
        span_ctx = trace.get_current_span().get_span_context()
        trace_id = format(span_ctx.trace_id, "032x") if span_ctx.trace_id else str(uuid.uuid4())

        # Track this user as active
        _record_active_user(str(user_id))

        user_message = ChatMessage(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=content,
            created_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        )
        await self._messages.add(user_message)
        history = await self._messages.list_for_conversation(conversation_id)

        initial_state = AgentState(
            conversation_id=conversation_id,
            user_id=user_id,
            trace_id=trace_id,
            messages=history,
        )

        lf_trace = self._langfuse.start_trace(
            name="chat_turn",
            user_id=str(user_id),
            session_id=str(conversation_id),
            trace_id=trace_id,
        )
        set_current_langfuse_trace(lf_trace)

        start = time.perf_counter()
        final_state_dict = await self._graph.ainvoke(initial_state)
        duration_ms = (time.perf_counter() - start) * 1000

        self._langfuse.flush()

        assistant_message = ChatMessage(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=final_state_dict.get("draft_response", ""),
            created_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        )
        await self._messages.add(assistant_message)
        await self._conversations.touch(conversation_id)

        try:
            if len(history) > 0 and len(history) % 20 == 0:
                from app.infrastructure.tasks.summarization import summarize_conversation
                summarize_conversation.delay(str(conversation_id))
        except Exception as exc:
            logger.warning("summarization_dispatch_failed", conversation_id=str(conversation_id), error=str(exc))

        return {
            "message": assistant_message,
            "trace_id": trace_id,
            "duration_ms": duration_ms,
            "node_path": final_state_dict.get("node_path", []),
            "tool_result": final_state_dict.get("tool_result"),
        }