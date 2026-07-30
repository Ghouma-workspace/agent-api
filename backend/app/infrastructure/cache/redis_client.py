from __future__ import annotations

import time

from redis.asyncio import Redis

from app.core.config import Settings
from app.domain.exceptions.base import RateLimitExceededError


def create_redis_client(settings: Settings) -> Redis:
    return Redis.from_url(str(settings.redis_url), decode_responses=True)


class RedisRateLimiter:
    """Fixed-window token bucket-ish limiter, cheap and good enough for per-user throttling."""

    def __init__(self, redis: Redis, requests_per_minute: int) -> None:
        self._redis = redis
        self._limit = requests_per_minute

    async def check(self, key: str) -> None:
        window = int(time.time() // 60)
        redis_key = f"ratelimit:{key}:{window}"
        count = await self._redis.incr(redis_key)
        if count == 1:
            await self._redis.expire(redis_key, 60)
        if count > self._limit:
            raise RateLimitExceededError(retry_after_seconds=60 - int(time.time() % 60))


class RedisConversationMemory:
    """Short-term conversation-window cache to avoid re-hitting Postgres on every turn."""

    def __init__(self, redis: Redis, ttl_seconds: int = 3600) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    def _key(self, conversation_id: str) -> str:
        return f"conv:memory:{conversation_id}"

    async def get(self, conversation_id: str) -> str | None:
        return await self._redis.get(self._key(conversation_id))

    async def set(self, conversation_id: str, serialized_messages: str) -> None:
        await self._redis.set(self._key(conversation_id), serialized_messages, ex=self._ttl)

    async def invalidate(self, conversation_id: str) -> None:
        await self._redis.delete(self._key(conversation_id))
