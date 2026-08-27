"""Section 4 tests — ToolResultCache.

Pure unit tests. Uses an in-memory fake Redis (dict-backed) so no container needed.
"""

from __future__ import annotations

import pytest

from app.domain.entities.chat import ToolResult
from app.infrastructure.cache.tool_cache import ToolResultCache, _cache_key, _is_write_operation

# ---------------------------------------------------------------------------
# Fake Redis
# ---------------------------------------------------------------------------


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, tuple[str, int | None]] = {}  # key -> (value, ttl)

    async def get(self, key: str) -> str | None:
        entry = self._store.get(key)
        return entry[0] if entry else None

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = (value, ex)


# ---------------------------------------------------------------------------
# Write-operation detection
# ---------------------------------------------------------------------------


def test_write_detection_in_value():
    assert _is_write_operation({"action": "create_issue"}) is True


def test_write_detection_in_key():
    assert _is_write_operation({"delete_record": "123"}) is True


def test_write_detection_negative():
    assert _is_write_operation({"location": "London", "units": "metric"}) is False


def test_write_detection_post_value():
    assert _is_write_operation({"method": "POST", "body": "data"}) is True


# ---------------------------------------------------------------------------
# Cache key determinism
# ---------------------------------------------------------------------------


def test_cache_key_is_deterministic():
    k1 = _cache_key("weather", {"city": "London", "units": "metric"})
    k2 = _cache_key("weather", {"units": "metric", "city": "London"})
    assert k1 == k2  # sort_keys=True in JSON serialization


def test_cache_key_differs_for_different_args():
    k1 = _cache_key("weather", {"city": "London"})
    k2 = _cache_key("weather", {"city": "Paris"})
    assert k1 != k2


# ---------------------------------------------------------------------------
# Cache get/set round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_miss_returns_none():
    cache = ToolResultCache(FakeRedis())
    result = await cache.get("weather", {"city": "London"})
    assert result is None


@pytest.mark.asyncio
async def test_cache_set_and_get_round_trip():
    redis = FakeRedis()
    cache = ToolResultCache(redis)

    tool_result = ToolResult(
        tool_name="weather", success=True, output={"temp": 20}, error=None, latency_ms=50.0
    )
    await cache.set("weather", {"city": "London"}, tool_result, ttl_seconds=300)
    retrieved = await cache.get("weather", {"city": "London"})

    assert retrieved is not None
    assert retrieved.success is True
    assert retrieved.output == {"temp": 20}
    assert retrieved.tool_name == "weather"


@pytest.mark.asyncio
async def test_cache_write_operations_are_never_cached():
    redis = FakeRedis()
    cache = ToolResultCache(redis)

    tool_result = ToolResult(
        tool_name="github", success=True, output={"id": 1}, error=None, latency_ms=100.0
    )
    args = {"action": "create_issue", "title": "Bug"}
    await cache.set("github", args, tool_result, ttl_seconds=3600)

    # Should not be cached
    retrieved = await cache.get("github", args)
    assert retrieved is None


@pytest.mark.asyncio
async def test_cache_get_write_op_skips_without_redis_call():
    """Write operations must be skipped before hitting Redis (no key lookup)."""

    class StrictRedis(FakeRedis):
        async def get(self, key: str) -> str | None:
            raise AssertionError("Redis.get should not be called for write operations")

    cache = ToolResultCache(StrictRedis())
    result = await cache.get("github", {"delete_record": "123"})
    assert result is None


@pytest.mark.asyncio
async def test_cache_ttl_is_passed_to_redis():
    redis = FakeRedis()
    cache = ToolResultCache(redis)

    tool_result = ToolResult(
        tool_name="weather", success=True, output={}, error=None, latency_ms=10.0
    )
    await cache.set("weather", {"city": "Oslo"}, tool_result, ttl_seconds=999)
    key = _cache_key("weather", {"city": "Oslo"})
    assert redis._store[key][1] == 999


@pytest.mark.asyncio
async def test_cache_gracefully_handles_redis_error():
    """If Redis.get raises, cache returns None (miss) without crashing."""

    class BrokenRedis(FakeRedis):
        async def get(self, key: str) -> str | None:
            raise ConnectionError("Redis is down")

    cache = ToolResultCache(BrokenRedis())
    result = await cache.get("weather", {"city": "London"})
    assert result is None
