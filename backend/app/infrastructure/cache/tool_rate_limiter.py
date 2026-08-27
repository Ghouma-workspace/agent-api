"""Per-tool sliding-window rate limiter backed by Redis sorted sets.

Sliding window is more accurate than fixed window at boundary conditions: a fixed
window allows a burst of 2x the limit at the window edge; sliding window prevents that.

Algorithm:
  - Key: f"toolrate:{tool_name}"
  - Members: UUID strings scored by timestamp (epoch float, microsecond precision)
  - On each check:
      1. Remove all members older than (now - 60s)  → trim the window
      2. Count remaining members
      3. If count >= limit → raise ToolExecutionError(retryable=True)
      4. Add a new member scored at now
      5. Set key TTL to 65s (slightly over the window to survive expiry races)
"""

from __future__ import annotations

import time
import uuid

import structlog
from redis.asyncio import Redis

from app.domain.exceptions.base import ToolExecutionError

logger = structlog.get_logger()

_WINDOW_SECONDS = 60
_KEY_TTL = 65  # slightly wider than the window


class ToolRateLimiter:
    """Sliding-window rate limiter. Limit is requests per minute per tool."""

    def __init__(self, redis: Redis, limits: dict[str, int]) -> None:
        """
        Args:
            redis: Async Redis client.
            limits: Mapping of tool_name → max requests per 60-second window.
                    Tools not in the dict are unlimited.
        """
        self._redis = redis
        self._limits = limits

    async def check(self, tool_name: str) -> None:
        """Raise ToolExecutionError(retryable=True) if the tool is over its rate limit.

        If the tool has no configured limit, this is a no-op.
        If Redis is unavailable, logs a warning and allows the call through (fail-open).
        """
        limit = self._limits.get(tool_name)
        if limit is None:
            return  # no limit configured for this tool

        key = f"toolrate:{tool_name}"
        now = time.time()
        window_start = now - _WINDOW_SECONDS

        try:
            pipe = self._redis.pipeline()
            # Remove stale members outside the window
            pipe.zremrangebyscore(key, "-inf", window_start)
            # Count remaining (in-window) members
            pipe.zcard(key)
            # Add the current request
            pipe.zadd(key, {str(uuid.uuid4()): now})
            # Refresh TTL
            pipe.expire(key, _KEY_TTL)
            results = await pipe.execute()
            current_count = results[1]  # zcard result
        except Exception as exc:
            logger.warning(
                "tool_rate_limiter_redis_error",
                tool=tool_name,
                error=str(exc),
            )
            return  # fail-open: allow the call if Redis is unavailable

        if current_count >= limit:
            logger.warning(
                "tool_rate_limit_exceeded",
                tool=tool_name,
                count=current_count,
                limit=limit,
            )
            raise ToolExecutionError(
                tool_name,
                f"Rate limit exceeded ({current_count}/{limit} requests per minute)",
                retryable=True,
            )
