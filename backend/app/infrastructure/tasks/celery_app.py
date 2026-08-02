"""Celery application instance.

Uses Redis as both broker and result backend, on database index 2 to avoid
colliding with the app's index 0 and Langfuse's index 1.

Import this module to get the configured Celery app:
    from app.infrastructure.tasks.celery_app import celery_app
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

_settings = get_settings()

# Convert redis://host:port/0 → redis://host:port/2
_broker_url = str(_settings.redis_url).rsplit("/", 1)[0] + "/2"
_backend_url = _broker_url  # same DB index for broker and result backend

celery_app = Celery(
    "ai-api-assistant",
    broker=_broker_url,
    backend=_backend_url,
    include=["app.infrastructure.tasks.summarization"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,          # ack only after task completes → no lost tasks on crash
    worker_prefetch_multiplier=1, # fair dispatch
    task_track_started=True,
)
