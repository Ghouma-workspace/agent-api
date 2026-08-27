"""Section 5 tests — ToolRateLimiter sliding window.

Pure unit tests: fake Redis sorted-set implemented in memory.
"""

from __future__ import annotations

import time

import pytest

from app.domain.exceptions.base import ToolExecutionError
from app.infrastructure.cache.tool_rate_limiter import ToolRateLimiter

# ---------------------------------------------------------------------------
# In-memory Redis sorted-set fake
# ---------------------------------------------------------------------------


class FakeSortedSetRedis:
    """Minimal Redis fake supporting the sorted-set commands used by ToolRateLimiter."""

    def __init__(self) -> None:
        # key -> list of (score, member)
        self._sets: dict[str, list[tuple[float, str]]] = {}
        self._ttls: dict[str, int] = {}

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)

    def _zremrangebyscore(self, key: str, min_score, max_score) -> int:
        _min = float("-inf") if min_score == "-inf" else float(min_score)
        _max = float("inf") if max_score == "+inf" else float(max_score)
        before = len(self._sets.get(key, []))
        self._sets[key] = [
            (s, m) for s, m in self._sets.get(key, [])
            if not (_min <= s <= _max)
        ]
        return before - len(self._sets[key])

    def _zcard(self, key: str) -> int:
        return len(self._sets.get(key, []))

    def _zadd(self, key: str, mapping: dict) -> int:
        if key not in self._sets:
            self._sets[key] = []
        for member, score in mapping.items():
            self._sets[key].append((score, member))
        return len(mapping)

    def _expire(self, key: str, ttl: int) -> None:
        self._ttls[key] = ttl


class FakePipeline:
    def __init__(self, redis: FakeSortedSetRedis) -> None:
        self._redis = redis
        self._ops: list = []

    def zremrangebyscore(self, key, min_score, max_score):
        self._ops.append(("zremrangebyscore", key, min_score, max_score))
        return self

    def zcard(self, key):
        self._ops.append(("zcard", key))
        return self

    def zadd(self, key, mapping):
        self._ops.append(("zadd", key, mapping))
        return self

    def expire(self, key, ttl):
        self._ops.append(("expire", key, ttl))
        return self

    async def execute(self) -> list:
        results = []
        for op in self._ops:
            if op[0] == "zremrangebyscore":
                results.append(self._redis._zremrangebyscore(op[1], op[2], op[3]))
            elif op[0] == "zcard":
                results.append(self._redis._zcard(op[1]))
            elif op[0] == "zadd":
                results.append(self._redis._zadd(op[1], op[2]))
            elif op[0] == "expire":
                self._redis._expire(op[1], op[2])
                results.append(True)
        return results


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limiter_allows_under_limit():
    redis = FakeSortedSetRedis()
    limiter = ToolRateLimiter(redis, limits={"weather": 3})

    # 3 calls should all pass (limit is 3)
    for _ in range(3):
        await limiter.check("weather")  # should not raise


@pytest.mark.asyncio
async def test_rate_limiter_blocks_over_limit():
    redis = FakeSortedSetRedis()
    limiter = ToolRateLimiter(redis, limits={"weather": 2})

    await limiter.check("weather")
    await limiter.check("weather")

    with pytest.raises(ToolExecutionError) as exc_info:
        await limiter.check("weather")

    assert exc_info.value.retryable is True
    assert "weather" in str(exc_info.value)
    assert "Rate limit exceeded" in str(exc_info.value)


@pytest.mark.asyncio
async def test_rate_limiter_no_limit_for_unlisted_tool():
    """Tools not in the limits dict must be allowed through unconditionally."""
    redis = FakeSortedSetRedis()
    limiter = ToolRateLimiter(redis, limits={"weather": 1})

    # "github" is not in limits — call 100 times without raising
    for _ in range(100):
        await limiter.check("github")


@pytest.mark.asyncio
async def test_rate_limiter_fail_open_on_redis_error():
    """If Redis is unavailable, the call must be allowed through (fail-open)."""

    class BrokenRedis:
        def pipeline(self):
            raise ConnectionError("Redis is down")

    limiter = ToolRateLimiter(BrokenRedis(), limits={"weather": 1})
    # Should not raise
    await limiter.check("weather")


@pytest.mark.asyncio
async def test_rate_limiter_uses_sliding_window_not_fixed():
    """Verify that old entries are trimmed and don't count against the limit."""
    redis = FakeSortedSetRedis()
    limiter = ToolRateLimiter(redis, limits={"weather": 2})

    # Inject a stale entry (61 seconds ago) directly into the sorted set
    stale_score = time.time() - 61
    redis._sets["toolrate:weather"] = [(stale_score, "old-member")]

    # With the stale entry trimmed, we should be able to make 2 more calls
    await limiter.check("weather")
    await limiter.check("weather")  # second call — should not raise
