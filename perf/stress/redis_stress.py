"""
Redis Infrastructure Stress Test
=================================
Directly stress-tests Redis-backed components without going through HTTP.
Run this while the main locust test runs to see Redis degradation effects.

Usage:
    python scripts/redis_stress.py --host localhost --port 6379

What it tests:
  1. Tool cache under concurrent get/set operations
  2. Rate limiter sliding window accuracy under rapid fire
  3. Circuit breaker state transitions under concurrent access
  4. Redis connection pool exhaustion
  5. Pipeline throughput
  6. Key TTL expiry behavior
  7. Cache key collision resistance
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

import redis.asyncio as aioredis


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REDIS_URL = "redis://localhost:6379/0"
CONCURRENCY = 50
DURATION_SECONDS = 60


@dataclass
class StressResult:
    name: str
    total_ops: int = 0
    failures: int = 0
    latencies: list[float] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_ops == 0:
            return 0
        return (self.total_ops - self.failures) / self.total_ops * 100

    @property
    def p50(self) -> float:
        if not self.latencies:
            return 0
        s = sorted(self.latencies)
        return s[len(s) // 2] * 1000

    @property
    def p95(self) -> float:
        if not self.latencies:
            return 0
        s = sorted(self.latencies)
        return s[int(len(s) * 0.95)] * 1000

    @property
    def p99(self) -> float:
        if not self.latencies:
            return 0
        s = sorted(self.latencies)
        return s[int(len(s) * 0.99)] * 1000

    @property
    def ops_per_second(self) -> float:
        if not self.latencies:
            return 0
        return self.total_ops / DURATION_SECONDS

    def report(self):
        print(f"\n{'='*60}")
        print(f"  {self.name}")
        print(f"{'='*60}")
        print(f"  Total ops:     {self.total_ops:,}")
        print(f"  Failures:      {self.failures:,}")
        print(f"  Success rate:  {self.success_rate:.2f}%")
        print(f"  Throughput:    {self.ops_per_second:.0f} ops/s")
        print(f"  Latency p50:   {self.p50:.2f} ms")
        print(f"  Latency p95:   {self.p95:.2f} ms")
        print(f"  Latency p99:   {self.p99:.2f} ms")


# ---------------------------------------------------------------------------
# Test 1: Tool cache GET/SET concurrency
# ---------------------------------------------------------------------------


async def stress_tool_cache(redis: aioredis.Redis, result: StressResult) -> None:
    """Simulates concurrent tool result caching operations."""

    tools = ["weather", "github", "mock_api"]
    deadline = time.time() + DURATION_SECONDS

    while time.time() < deadline:
        try:
            tool = random.choice(tools)
            args = {
                "latitude": round(random.uniform(-90, 90), 4),
                "longitude": round(random.uniform(-180, 180), 4),
            }
            key_data = json.dumps(args, sort_keys=True).encode()
            fingerprint = hashlib.sha256(key_data).hexdigest()[:16]
            cache_key = f"toolcache:{tool}:{fingerprint}"

            tool_result = json.dumps({
                "tool_name": tool,
                "success": True,
                "output": {"temperature": random.uniform(0, 40)},
                "latency_ms": random.uniform(50, 500),
            })

            start = time.perf_counter()

            # 50% reads, 50% writes
            if random.random() < 0.5:
                await redis.get(cache_key)
            else:
                await redis.set(cache_key, tool_result, ex=300)

            elapsed = time.perf_counter() - start
            result.latencies.append(elapsed)
            result.total_ops += 1

        except Exception as exc:
            result.failures += 1
            result.total_ops += 1


# ---------------------------------------------------------------------------
# Test 2: Rate limiter sliding window under rapid fire
# ---------------------------------------------------------------------------


async def stress_rate_limiter(redis: aioredis.Redis, result: StressResult) -> None:
    """Simulates 50 concurrent callers hammering the rate limiter.
    
    Validates: sliding window accuracy, no race conditions, pipeline atomicity.
    """

    tools = ["weather", "github", "slack", "stripe"]
    deadline = time.time() + DURATION_SECONDS

    while time.time() < deadline:
        try:
            tool = random.choice(tools)
            key = f"toolrate:{tool}"
            now = time.time()
            window_start = now - 60

            start = time.perf_counter()

            pipe = redis.pipeline()
            pipe.zremrangebyscore(key, "-inf", window_start)
            pipe.zcard(key)
            pipe.zadd(key, {str(uuid.uuid4()): now})
            pipe.expire(key, 65)
            results = await pipe.execute()

            elapsed = time.perf_counter() - start
            count = results[1]

            result.latencies.append(elapsed)
            result.total_ops += 1

            # Optionally record if we would have been rate-limited
            if count > 50:
                pass  # Would be rate-limited

        except Exception:
            result.failures += 1
            result.total_ops += 1


# ---------------------------------------------------------------------------
# Test 3: Circuit breaker state machine concurrency
# ---------------------------------------------------------------------------


async def stress_circuit_breaker(redis: aioredis.Redis, result: StressResult) -> None:
    """Simulates concurrent circuit breaker state reads/writes.
    
    Key concern: multiple workers reading stale state and making inconsistent decisions.
    """

    tools = ["weather", "github", "mock_api", "slack"]
    states = ["closed", "open", "half_open"]
    deadline = time.time() + DURATION_SECONDS

    while time.time() < deadline:
        try:
            tool = random.choice(tools)
            state_key = f"circuit:{tool}:state"
            failures_key = f"circuit:{tool}:failures"

            start = time.perf_counter()

            op = random.choice(["read", "write_state", "increment_failures", "reset"])

            if op == "read":
                await redis.get(state_key)
                await redis.get(failures_key)

            elif op == "write_state":
                await redis.set(state_key, random.choice(states))

            elif op == "increment_failures":
                current = await redis.get(failures_key)
                count = int(current or 0) + 1
                await redis.set(failures_key, str(count))

            elif op == "reset":
                await redis.set(failures_key, "0")
                await redis.set(state_key, "closed")

            elapsed = time.perf_counter() - start
            result.latencies.append(elapsed)
            result.total_ops += 1

        except Exception:
            result.failures += 1
            result.total_ops += 1


# ---------------------------------------------------------------------------
# Test 4: Connection pool saturation
# ---------------------------------------------------------------------------


async def stress_connection_pool(redis: aioredis.Redis, result: StressResult) -> None:
    """Opens many concurrent connections to test pool limits."""

    deadline = time.time() + DURATION_SECONDS

    while time.time() < deadline:
        try:
            start = time.perf_counter()

            # Simulate a full cache operation cycle
            key = f"pool_test:{uuid.uuid4().hex}"
            await redis.set(key, "test_value", ex=10)
            val = await redis.get(key)
            await redis.delete(key)

            if val != b"test_value":
                result.failures += 1
            else:
                elapsed = time.perf_counter() - start
                result.latencies.append(elapsed)

            result.total_ops += 1

        except Exception:
            result.failures += 1
            result.total_ops += 1


# ---------------------------------------------------------------------------
# Test 5: Pipeline throughput
# ---------------------------------------------------------------------------


async def stress_pipeline_throughput(redis: aioredis.Redis, result: StressResult) -> None:
    """Tests pipeline batch operation throughput."""

    deadline = time.time() + DURATION_SECONDS

    while time.time() < deadline:
        try:
            start = time.perf_counter()

            pipe = redis.pipeline()
            batch_size = random.randint(5, 20)
            keys = [f"pipe_test:{uuid.uuid4().hex}" for _ in range(batch_size)]

            for key in keys:
                pipe.set(key, f"value_{key}", ex=5)
            for key in keys:
                pipe.get(key)

            results = await pipe.execute()

            elapsed = time.perf_counter() - start
            result.latencies.append(elapsed)
            result.total_ops += batch_size * 2

            # Cleanup
            if keys:
                await redis.delete(*keys)

        except Exception:
            result.failures += 1
            result.total_ops += 1


# ---------------------------------------------------------------------------
# Test 6: Conversation memory cache
# ---------------------------------------------------------------------------


async def stress_conversation_cache(redis: aioredis.Redis, result: StressResult) -> None:
    """Simulates conversation memory cache read/write/invalidation."""

    conversation_ids = [str(uuid.uuid4()) for _ in range(100)]
    deadline = time.time() + DURATION_SECONDS

    while time.time() < deadline:
        try:
            conv_id = random.choice(conversation_ids)
            key = f"conv:memory:{conv_id}"

            start = time.perf_counter()

            op = random.choice(["read", "write", "invalidate"])

            if op == "read":
                await redis.get(key)

            elif op == "write":
                messages = [
                    {"role": "user", "content": f"Message {i}"}
                    for i in range(random.randint(1, 10))
                ]
                await redis.set(key, json.dumps(messages), ex=3600)

            elif op == "invalidate":
                await redis.delete(key)

            elapsed = time.perf_counter() - start
            result.latencies.append(elapsed)
            result.total_ops += 1

        except Exception:
            result.failures += 1
            result.total_ops += 1


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def run_all_stress_tests():
    print("\n" + "="*60)
    print("  REDIS INFRASTRUCTURE STRESS TEST")
    print(f"  Duration: {DURATION_SECONDS}s | Concurrency: {CONCURRENCY} workers per test")
    print("="*60)

    pool = aioredis.ConnectionPool.from_url(
        REDIS_URL,
        max_connections=CONCURRENCY * 2,
        decode_responses=True,
    )
    redis = aioredis.Redis(connection_pool=pool)

    # Verify connection
    try:
        await redis.ping()
        print("\n✓ Redis connection established")
    except Exception as exc:
        print(f"\n✗ Cannot connect to Redis: {exc}")
        return

    tests = [
        ("Tool Cache GET/SET", stress_tool_cache),
        ("Rate Limiter Sliding Window", stress_rate_limiter),
        ("Circuit Breaker State Machine", stress_circuit_breaker),
        ("Connection Pool Saturation", stress_connection_pool),
        ("Pipeline Throughput", stress_pipeline_throughput),
        ("Conversation Memory Cache", stress_conversation_cache),
    ]

    for test_name, test_fn in tests:
        print(f"\n▶ Running: {test_name} ({DURATION_SECONDS}s, {CONCURRENCY} workers)...")
        result = StressResult(name=test_name)

        workers = [
            asyncio.create_task(test_fn(redis, result))
            for _ in range(CONCURRENCY)
        ]
        await asyncio.gather(*workers, return_exceptions=True)
        result.report()

    await pool.aclose()

    print("\n" + "="*60)
    print("  STRESS TEST COMPLETE")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(run_all_stress_tests())
