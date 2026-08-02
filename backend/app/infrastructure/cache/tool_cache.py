"""Redis-backed tool result cache.

Identical tool calls within the configured TTL window return the cached result,
saving external API quota and latency. Write operations (create/post/delete) are
never cached regardless of TTL configuration.

Cache key: toolcache:<tool_name>:<sha256[:16] of sorted-key JSON of arguments>
"""

from __future__ import annotations

import hashlib
import json

import structlog
from redis.asyncio import Redis

from app.domain.entities.chat import ToolResult
from app.infrastructure.observability.metrics import CACHE_HITS_TOTAL, CACHE_MISSES_TOTAL

logger = structlog.get_logger()

_WRITE_PATTERNS = {"create", "post", "delete", "update", "put", "patch", "remove", "write"}


def _is_write_operation(arguments: dict) -> bool:
    """Heuristic: if any argument value (as string) contains a write-intent keyword,
    skip caching. Errs on the side of safety — false positives just mean a cache miss,
    false negatives would return stale data for a mutation."""
    for v in arguments.values():
        if isinstance(v, str) and any(pat in v.lower() for pat in _WRITE_PATTERNS):
            return True
    # Also check argument keys
    for k in arguments:
        if any(pat in k.lower() for pat in _WRITE_PATTERNS):
            return True
    return False


def _cache_key(tool_name: str, arguments: dict) -> str:
    fingerprint = hashlib.sha256(
        json.dumps(arguments, sort_keys=True).encode()
    ).hexdigest()[:16]
    return f"toolcache:{tool_name}:{fingerprint}"


class ToolResultCache:
    """Async Redis cache for ToolResult objects."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self, tool_name: str, arguments: dict) -> ToolResult | None:
        if _is_write_operation(arguments):
            CACHE_MISSES_TOTAL.labels(cache_name="tool_result").inc()
            return None

        key = _cache_key(tool_name, arguments)
        try:
            raw = await self._redis.get(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("tool_cache_get_error", tool=tool_name, error=str(exc))
            CACHE_MISSES_TOTAL.labels(cache_name="tool_result").inc()
            return None

        if raw is None:
            CACHE_MISSES_TOTAL.labels(cache_name="tool_result").inc()
            return None

        try:
            result = ToolResult.model_validate_json(raw)
            CACHE_HITS_TOTAL.labels(cache_name="tool_result").inc()
            logger.debug("tool_cache_hit", tool=tool_name, key=key)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("tool_cache_deserialize_error", tool=tool_name, error=str(exc))
            CACHE_MISSES_TOTAL.labels(cache_name="tool_result").inc()
            return None

    async def set(
        self, tool_name: str, arguments: dict, result: ToolResult, ttl_seconds: int
    ) -> None:
        if _is_write_operation(arguments):
            return  # never cache write operations

        key = _cache_key(tool_name, arguments)
        try:
            await self._redis.set(key, result.model_dump_json(), ex=ttl_seconds)
            logger.debug("tool_cache_set", tool=tool_name, key=key, ttl=ttl_seconds)
        except Exception as exc:  # noqa: BLE001
            logger.warning("tool_cache_set_error", tool=tool_name, error=str(exc))
