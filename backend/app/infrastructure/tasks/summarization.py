"""Background summarization task.

When a conversation accumulates 20+ messages, this task is dispatched by ChatService
to summarize the older portion so future turns don't burn tokens on stale history.

Celery workers are synchronous; we use a synchronous SQLAlchemy session here.
The task uses llama-3.1-8b-instant — the cheap model — intentionally. Cost matters.
"""

from __future__ import annotations

import uuid

import structlog
from groq import Groq
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.infrastructure.db.models.orm import MessageORM
from app.infrastructure.tasks.celery_app import celery_app

logger = structlog.get_logger()

_SUMMARIZATION_MODEL = "llama-3.1-8b-instant"  # hardcoded — cheap model for this use-case
_KEEP_TAIL = 10  # always preserve the last N messages verbatim


@celery_app.task(
    name="summarize_conversation",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def summarize_conversation(self, conversation_id: str) -> dict:  # type: ignore[misc]
    """Summarize the early history of a conversation and compact Postgres.

    Algorithm:
    1. Load all messages for the conversation (sync SQLAlchemy).
    2. If fewer than 20 messages, do nothing.
    3. Summarize messages[0 .. N-_KEEP_TAIL] with the cheap model.
    4. Insert a SYSTEM message at position 0: "[Conversation summary]: <summary>".
    5. Delete the original early messages from Postgres.
    6. Invalidate the Redis conversation memory cache.
    """
    log = logger.bind(conversation_id=conversation_id, task="summarize_conversation")

    settings = get_settings()

    # --- Sync SQLAlchemy session for Celery worker ---
    sync_url = str(settings.database_url).replace("+asyncpg", "")
    engine = create_engine(sync_url, pool_pre_ping=True)

    try:
        with Session(engine) as session:
            rows = session.execute(
                select(MessageORM)
                .where(MessageORM.conversation_id == conversation_id)
                .order_by(MessageORM.created_at.asc())
            ).scalars().all()

            if len(rows) < 20:
                log.info("summarization_skipped", reason="fewer_than_20_messages", count=len(rows))
                return {"skipped": True, "reason": "fewer_than_20_messages"}

            to_summarize = rows[:-_KEEP_TAIL]  # all except the tail
            ids_to_delete = [str(r.id) for r in to_summarize]

            # Build conversation text for the summarization call
            conversation_text = "\n".join(
                f"{r.role.upper()}: {r.content}" for r in to_summarize
            )

            # --- Call Groq with the cheap model ---
            try:
                groq_client = Groq(api_key=settings.groq_api_key.get_secret_value())
                response = groq_client.chat.completions.create(
                    model=_SUMMARIZATION_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a conversation summarizer. "
                                "Write a single concise paragraph summarizing the key points, "
                                "decisions, and outcomes of the following conversation. "
                                "Be specific about any tool calls made and their results."
                            ),
                        },
                        {"role": "user", "content": conversation_text},
                    ],
                    max_tokens=300,
                )
                summary = response.choices[0].message.content or ""
            except Exception as exc:
                log.error("summarization_llm_failed", error=str(exc))
                raise self.retry(exc=exc)  # type: ignore[attr-defined]

            # --- Insert summary message at position 0 (earliest created_at - 1s) ---
            earliest_ts = to_summarize[0].created_at
            summary_ts = earliest_ts.replace(microsecond=max(0, earliest_ts.microsecond - 1000))
            summary_row = MessageORM(
                id=uuid.uuid4(),
                conversation_id=conversation_id,
                role="system",
                content=f"[Conversation summary]: {summary}",
                created_at=summary_ts,
            )
            session.add(summary_row)

            # --- Delete the original early messages ---
            session.execute(
                delete(MessageORM).where(MessageORM.id.in_(ids_to_delete))
            )
            session.commit()

            log.info(
                "summarization_complete",
                deleted_count=len(ids_to_delete),
                summary_length=len(summary),
            )

    finally:
        engine.dispose()

    # --- Invalidate Redis conversation memory cache ---
    _invalidate_redis_cache(conversation_id, settings)

    return {"summarized": True, "deleted_count": len(ids_to_delete)}


def _invalidate_redis_cache(conversation_id: str, settings) -> None:
    """Best-effort Redis cache invalidation — failure is logged but not fatal."""
    try:
        import redis as sync_redis

        client = sync_redis.from_url(str(settings.redis_url), decode_responses=True)
        key = f"conv:memory:{conversation_id}"
        client.delete(key)
        client.close()
    except Exception as exc:
        logger.warning(
            "summarization_cache_invalidation_failed",
            conversation_id=conversation_id,
            error=str(exc),
        )
