"""
EC2 Performance Assessment — Remote Load Testing
=================================================
Runs the full performance assessment suite against an EC2-deployed instance.

Pre-requisites:
  Local machine: locust, httpx, redis-py installed
  EC2 instance:  docker compose running, port 8000 open to your IP

Usage:
    # Set your EC2 public IP or domain
    export EC2_HOST=http://54.123.45.67:8000

    # Phase 1: Latency profile (5 min)
    python ec2_assessment.py --phase latency

    # Phase 2: Ramp load test (7 min)
    python ec2_assessment.py --phase ramp

    # Phase 3: Spike test (3 min)
    python ec2_assessment.py --phase spike

    # Phase 4: Soak test (30 min)
    python ec2_assessment.py --phase soak

    # Full assessment (all phases, ~50 min)
    python ec2_assessment.py --phase all
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field

import httpx

EC2_HOST = os.getenv("EC2_HOST", "http://localhost:8000")
TIMEOUT = httpx.Timeout(60.0)


@dataclass
class PhaseResult:
    name: str
    duration_s: float = 0
    total_requests: int = 0
    successful: int = 0
    latencies: list[float] = field(default_factory=list)
    errors: dict[str, int] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        return self.successful / self.total_requests * 100 if self.total_requests else 0

    @property
    def throughput(self) -> float:
        return self.total_requests / self.duration_s if self.duration_s else 0

    def p(self, percentile: float) -> float:
        if not self.latencies:
            return 0
        s = sorted(self.latencies)
        idx = int(len(s) * percentile / 100)
        return s[min(idx, len(s)-1)] * 1000

    def report(self):
        print(f"\n{'='*60}")
        print(f"  PHASE: {self.name}")
        print(f"{'='*60}")
        print(f"  Duration:       {self.duration_s:.0f}s")
        print(f"  Total requests: {self.total_requests:,}")
        print(f"  Successful:     {self.successful:,}")
        print(f"  Success rate:   {self.success_rate:.2f}%")
        print(f"  Throughput:     {self.throughput:.1f} req/s")
        print(f"  Latency p50:    {self.p(50):.0f}ms")
        print(f"  Latency p90:    {self.p(90):.0f}ms")
        print(f"  Latency p95:    {self.p(95):.0f}ms")
        print(f"  Latency p99:    {self.p(99):.0f}ms")
        print(f"  Latency max:    {self.p(100):.0f}ms")
        if self.errors:
            print(f"  Error breakdown:")
            for k, v in sorted(self.errors.items(), key=lambda x: -x[1]):
                print(f"    {k}: {v}")
        verdict = "✓ PASS" if self.success_rate >= 95 else "✗ FAIL"
        print(f"  Verdict: {verdict}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def setup_user(client: httpx.AsyncClient) -> dict:
    email = f"ec2_{uuid.uuid4().hex[:8]}@perf.com"
    pw = "EC2Perf123!"
    await client.post("/api/auth/register", json={"email": email, "password": pw})
    r = await client.post("/api/auth/login", json={"email": email, "password": pw})
    if r.status_code != 200:
        raise RuntimeError(f"Login failed: {r.status_code}")
    token = r.json()["access_token"]
    r2 = await client.post(
        "/api/conversations",
        json={"title": "ec2_perf"},
        headers={"Authorization": f"Bearer {token}"},
    )
    conv_id = r2.json().get("id") if r2.status_code in (200, 201) else str(uuid.uuid4())
    return {"token": token, "conversation_id": conv_id}


async def timed_request(client: httpx.AsyncClient, user: dict, content: str) -> tuple[bool, float, int]:
    start = time.perf_counter()
    try:
        r = await client.post(
            "/api/chat",
            json={"conversation_id": user["conversation_id"], "content": content},
            headers={"Authorization": f"Bearer {user['token']}"},
        )
        elapsed = time.perf_counter() - start
        return r.status_code == 200, elapsed, r.status_code
    except Exception:
        elapsed = time.perf_counter() - start
        return False, elapsed, -1


QUESTIONS = [
    "What is the capital of France?",
    "Explain TCP vs UDP briefly.",
    "What is a REST API?",
    "What is Docker?",
    "What is machine learning?",
]

WEATHER_QUERIES = [
    f"Weather at latitude {lat:.4f} and longitude {lon:.4f}"
    for lat, lon in [(48.8566, 2.3522), (51.5074, -0.1278), (40.7128, -74.0060)]
]


# ---------------------------------------------------------------------------
# Phase 1: Latency profile
# ---------------------------------------------------------------------------


async def phase_latency_profile() -> PhaseResult:
    """
    Single user, serial requests. Pure latency measurement per request type.
    No concurrency — isolates network + processing latency.
    """
    result = PhaseResult(name="Latency Profile")
    start = time.time()

    async with httpx.AsyncClient(base_url=EC2_HOST, timeout=TIMEOUT) as client:
        user = await setup_user(client)

        print("  Warming up (5 requests)...")
        for q in QUESTIONS[:5]:
            await timed_request(client, user, q)

        print("  Measuring latency (50 requests)...")
        for i, q in enumerate(QUESTIONS * 10):
            ok, elapsed, status = await timed_request(client, user, q)
            result.total_requests += 1
            result.latencies.append(elapsed)
            if ok:
                result.successful += 1
            else:
                result.errors[str(status)] = result.errors.get(str(status), 0) + 1
            await asyncio.sleep(0.2)

        # Weather tool separately
        print("  Measuring tool-call latency (10 requests)...")
        for q in WEATHER_QUERIES * 3:
            ok, elapsed, status = await timed_request(client, user, q)
            result.total_requests += 1
            result.latencies.append(elapsed)
            if ok:
                result.successful += 1

    result.duration_s = time.time() - start
    return result


# ---------------------------------------------------------------------------
# Phase 2: Ramp load test
# ---------------------------------------------------------------------------


async def phase_ramp_load() -> PhaseResult:
    """
    Ramps from 1 to 50 concurrent users over 7 minutes.
    Find the concurrency level where latency starts degrading.
    """
    result = PhaseResult(name="Ramp Load (1→50 users, 7min)")
    start = time.time()
    stop_event = asyncio.Event()

    steps = [
        (30, 1), (30, 5), (30, 10), (30, 20),
        (60, 30), (60, 40), (90, 50),
    ]

    async with httpx.AsyncClient(base_url=EC2_HOST, timeout=TIMEOUT) as client:
        for duration, n_users in steps:
            print(f"  → {n_users} concurrent users for {duration}s...")
            users = await asyncio.gather(*[setup_user(client) for _ in range(n_users)])
            phase_start = time.time()

            async def worker(user):
                while time.time() - phase_start < duration:
                    q = QUESTIONS[int(time.time()) % len(QUESTIONS)]
                    ok, elapsed, status = await timed_request(client, user, q)
                    result.total_requests += 1
                    result.latencies.append(elapsed)
                    if ok:
                        result.successful += 1
                    else:
                        result.errors[str(status)] = result.errors.get(str(status), 0) + 1
                    await asyncio.sleep(1)

            await asyncio.gather(*[worker(u) for u in users], return_exceptions=True)

            # Report for this step
            step_lats = result.latencies[-result.total_requests:]
            if step_lats:
                s = sorted(step_lats)
                p95 = s[int(len(s) * 0.95)] * 1000
                sr = result.success_rate
                print(f"    users={n_users} p95={p95:.0f}ms success={sr:.1f}%")

    result.duration_s = time.time() - start
    return result


# ---------------------------------------------------------------------------
# Phase 3: Spike test
# ---------------------------------------------------------------------------


async def phase_spike_test() -> PhaseResult:
    """
    Sudden spike from 5 to 100 users with no ramp.
    Tests auto-recovery and queue behavior.
    """
    result = PhaseResult(name="Spike Test (5→100→5 users, 3min)")
    start_time = time.time()

    async with httpx.AsyncClient(base_url=EC2_HOST, timeout=TIMEOUT) as client:
        # Baseline: 5 users for 30s
        print("  Baseline: 5 users...")
        users_small = await asyncio.gather(*[setup_user(client) for _ in range(5)])
        phase_start = time.time()

        async def worker_timed(user, deadline):
            while time.time() < deadline:
                ok, elapsed, status = await timed_request(client, user, "What is Python?")
                result.total_requests += 1
                result.latencies.append(elapsed)
                if ok:
                    result.successful += 1
                await asyncio.sleep(0.5)

        await asyncio.gather(*[
            worker_timed(u, time.time() + 30) for u in users_small
        ], return_exceptions=True)

        # Spike: 100 users for 60s
        print("  SPIKE: 100 users...")
        users_large = await asyncio.gather(*[setup_user(client) for _ in range(100)])
        await asyncio.gather(*[
            worker_timed(u, time.time() + 60) for u in users_large
        ], return_exceptions=True)

        # Recovery: 5 users for 30s
        print("  Recovery: back to 5 users...")
        await asyncio.gather(*[
            worker_timed(u, time.time() + 30) for u in users_small
        ], return_exceptions=True)

    result.duration_s = time.time() - start_time
    return result


# ---------------------------------------------------------------------------
# Phase 4: Soak test
# ---------------------------------------------------------------------------


async def phase_soak_test(duration_minutes: int = 30) -> PhaseResult:
    """
    Holds 20 concurrent users for the full duration.
    Detects: memory leaks, connection pool exhaustion, performance drift over time.
    """
    result = PhaseResult(name=f"Soak Test (20 users × {duration_minutes}min)")
    duration = duration_minutes * 60
    start_time = time.time()
    stop_event = asyncio.Event()

    # Track latency over time for drift detection
    time_windows: list[tuple[float, float]] = []  # (timestamp, latency)

    async with httpx.AsyncClient(base_url=EC2_HOST, timeout=TIMEOUT) as client:
        users = await asyncio.gather(*[setup_user(client) for _ in range(20)])
        print(f"  Running {duration_minutes} minute soak with 20 users...")
        print(f"  Progress every 60s:")

        async def worker(user):
            while not stop_event.is_set():
                q = QUESTIONS[int(time.time()) % len(QUESTIONS)]
                ok, elapsed, status = await timed_request(client, user, q)
                result.total_requests += 1
                result.latencies.append(elapsed)
                time_windows.append((time.time() - start_time, elapsed * 1000))
                if ok:
                    result.successful += 1
                else:
                    result.errors[str(status)] = result.errors.get(str(status), 0) + 1
                await asyncio.sleep(2)

        tasks = [asyncio.create_task(worker(u)) for u in users]

        # Progress reporter
        for minute in range(1, duration_minutes + 1):
            await asyncio.sleep(60)
            recent = [lat for ts, lat in time_windows if ts > (minute - 1) * 60 and ts <= minute * 60]
            if recent:
                s = sorted(recent)
                p95 = s[int(len(s) * 0.95)]
                print(f"    t={minute}min: {result.successful}/{result.total_requests} success, p95={p95:.0f}ms")

        stop_event.set()
        await asyncio.gather(*tasks, return_exceptions=True)

    # Drift analysis: compare first vs last 5 minutes
    if time_windows:
        early = [lat for ts, lat in time_windows if ts < 300]
        late = [lat for ts, lat in time_windows if ts > (duration - 300)]
        if early and late:
            early_p95 = sorted(early)[int(len(early) * 0.95)]
            late_p95 = sorted(late)[int(len(late) * 0.95)]
            drift = ((late_p95 - early_p95) / early_p95 * 100) if early_p95 else 0
            print(f"\n  Latency drift: {early_p95:.0f}ms → {late_p95:.0f}ms ({drift:+.1f}%)")
            if drift > 50:
                print("  ⚠️  WARNING: >50% latency increase over soak — possible resource leak!")
            else:
                print("  ✓ Latency stable over soak period")

    result.duration_s = time.time() - start_time
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "latency"

    print(f"\n{'='*60}")
    print(f"  EC2 PERFORMANCE ASSESSMENT")
    print(f"  Target: {EC2_HOST}")
    print(f"  Phase:  {phase}")
    print(f"{'='*60}")

    # Verify connectivity
    async with httpx.AsyncClient(base_url=EC2_HOST, timeout=TIMEOUT) as client:
        try:
            r = await client.get("/health")
            print(f"\n✓ Connected to {EC2_HOST} (health: {r.status_code})")
        except Exception as exc:
            print(f"\n✗ Cannot reach {EC2_HOST}: {exc}")
            sys.exit(1)

    results = []

    if phase in ("latency", "all"):
        print("\n▶ Phase 1: Latency Profile...")
        r = await phase_latency_profile()
        r.report()
        results.append(r)

    if phase in ("ramp", "all"):
        print("\n▶ Phase 2: Ramp Load Test...")
        r = await phase_ramp_load()
        r.report()
        results.append(r)

    if phase in ("spike", "all"):
        print("\n▶ Phase 3: Spike Test...")
        r = await phase_spike_test()
        r.report()
        results.append(r)

    if phase in ("soak", "all"):
        print("\n▶ Phase 4: Soak Test...")
        r = await phase_soak_test(30)
        r.report()
        results.append(r)

    # Final summary
    if results:
        print(f"\n{'='*60}")
        print("  ASSESSMENT SUMMARY")
        print(f"{'='*60}")
        for r in results:
            verdict = "✓" if r.success_rate >= 95 else "✗"
            print(
                f"  {verdict} {r.name}: "
                f"{r.success_rate:.1f}% success | "
                f"p95={r.p(95):.0f}ms | "
                f"{r.throughput:.1f} req/s"
            )


if __name__ == "__main__":
    asyncio.run(main())
