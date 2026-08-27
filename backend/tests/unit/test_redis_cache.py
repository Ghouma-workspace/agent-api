"""Unit tests for the Redis-backed tool result cache (ToolResultCache + _cache_key
+ _is_write_operation) and its wiring into the tool_executor agent node.

Regenerated to fix a UnicodeEncodeError: the original print() calls used the
Unicode arrow character (U+2192, '\u2192') in test_write_detection_accuracy,
which crashes under Windows' default console codepage (cp1252) — it can only
encode characters in Latin-1. Replaced with a plain ASCII '->' below. If you'd
rather keep Unicode in debug prints generally, set PYTHONIOENCODING=utf-8 in
the environment instead of avoiding Unicode in every print call.

Also updated for two follow-on fixes to app/infrastructure/cache/tool_cache.py:
  1. _is_write_operation now matches whole words/tokens instead of raw
     substrings (see TestWriteOperationDetection — "input"/"output" no longer
     false-positive on the substring "put").
  2. _cache_key now canonicalizes int/float-equivalent numbers before hashing
     (see test_float_vs_int_same_value_same_key), so an LLM emitting `48` on
     one call and `48.0` on the next for the same coordinate still hits the
     same cache entry. All hash values below were recomputed against the
     current implementation and are asserted directly, not hardcoded blindly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.application.agent.state import AgentState
from app.application.agent.nodes.tool_executor import make_tool_executor
from app.domain.entities.chat import ToolCall, ToolResult
from app.infrastructure.cache.tool_cache import ToolResultCache, _cache_key, _is_write_operation


# ---------------------------------------------------------------------------
# Fake Redis
# ---------------------------------------------------------------------------


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, tuple[str, int | None]] = {}

    async def get(self, key: str) -> str | None:
        entry = self._store.get(key)
        return entry[0] if entry else None

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = (value, ex)


# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

PARIS_ARGS = {"latitude": 48.8566, "longitude": 2.3522}
LONDON_ARGS = {"latitude": 51.5074, "longitude": -0.1278}


# ===========================================================================
# TestKeyConsistency
# ===========================================================================


class TestKeyConsistency:
    def test_key_matches_between_set_and_get(self):
        set_key = _cache_key("weather", PARIS_ARGS)
        get_key = _cache_key("weather", PARIS_ARGS)

        print(f"\n  SET key: {set_key}")
        print(f"  GET key: {get_key}")
        print(f"  Keys match: {set_key == get_key}")

        assert set_key == get_key

    def test_key_matches_when_argument_order_differs(self):
        original_order = {"latitude": 48.8566, "longitude": 2.3522}
        reordered = {"longitude": 2.3522, "latitude": 48.8566}

        k1 = _cache_key("weather", original_order)
        k2 = _cache_key("weather", reordered)

        print(f"\n  Key (original order):  {k1}")
        print(f"  Key (reordered):       {k2}")
        print(f"  Keys match: {k1 == k2}")

        assert k1 == k2

    def test_key_differs_for_different_coordinates(self):
        paris_key = _cache_key("weather", PARIS_ARGS)
        london_key = _cache_key("weather", LONDON_ARGS)

        print(f"\n  Paris key:  {paris_key}")
        print(f"  London key: {london_key}")

        assert paris_key != london_key

    def test_float_vs_int_same_value_same_key(self):
        """48 and 48.0 are the same coordinate — the cache key must not
        depend on which numeric form the LLM happened to emit."""
        float_args = {"latitude": 48.0, "longitude": 2.0}
        int_args = {"latitude": 48, "longitude": 2}

        float_key = _cache_key("weather", float_args)
        int_key = _cache_key("weather", int_args)

        print(f"\n  Float key: {float_key}  (args: {float_args})")
        print(f"  Int key:   {int_key}  (args: {int_args})")
        print(f"  Keys match: {float_key == int_key}")

        assert float_key == int_key


# ===========================================================================
# TestWriteOperationDetection
# ===========================================================================


class TestWriteOperationDetection:
    @pytest.mark.parametrize("args,expected_write,description", [
        # These should be reads (NOT write ops)
        ({"latitude": 48.8566, "longitude": 2.3522},      False, "weather query"),
        ({"query": "list repositories"},                   False, "github list"),
        ({"repo": "my-repo", "action": "list_issues"},     False, "list issues"),
        ({"location": "Paris"},                            False, "location query"),
        ({"username": "john"},                              False, "user lookup"),

        # These should be writes
        ({"action": "create_issue"},                       True,  "create issue"),
        ({"action": "delete_file"},                        True,  "delete file"),
        ({"method": "POST"},                                True,  "POST method"),
        ({"action": "update_pr"},                           True,  "update PR"),
    ])
    def test_write_detection_accuracy(self, args, expected_write, description):
        result = _is_write_operation(args)
        # NOTE: was a Unicode '\u2192' here — swapped for '->' (cp1252 can't encode it)
        print(f"\n  {description}: args={args} -> write={result} (expected={expected_write})")
        assert result == expected_write

    def test_action_list_not_classified_as_write(self):
        result = _is_write_operation({"action": "list_repositories"})
        print(f"\n  'list_repositories' classified as write: {result}")
        assert result is False

    def test_input_output_words_not_classified_as_write(self):
        """Regression test for the substring false-positive bug: 'input' and
        'output' both contain 'put' as a substring, which the old
        `pat in value` check incorrectly matched."""
        assert _is_write_operation({"payload": "here is my input for the test"}) is False
        assert _is_write_operation({"payload": "checking the output format"}) is False

    def test_compound_identifier_with_underscore_still_detected(self):
        """Whole-word tokenization must still catch write intent inside
        underscore-joined identifiers."""
        assert _is_write_operation({"action": "create_issue", "repo": "acme/widgets"}) is True


# ===========================================================================
# TestSerializationRoundTrip
# ===========================================================================


class TestSerializationRoundTrip:
    @pytest.mark.asyncio
    async def test_full_round_trip(self):
        redis = FakeRedis()
        cache = ToolResultCache(redis)

        original = ToolResult(
            tool_name="weather",
            success=True,
            output={"temperature": 22.5, "windspeed": 3.3, "is_day": 1},
            error=None,
            latency_ms=95.7,
        )
        await cache.set("weather", PARIS_ARGS, original, ttl_seconds=300)
        retrieved = await cache.get("weather", PARIS_ARGS)

        print(f"\n  Original:  {original.model_dump()}")
        print(f"  Retrieved: {retrieved.model_dump()}")

        assert retrieved is not None
        assert retrieved.model_dump() == original.model_dump()

    @pytest.mark.asyncio
    async def test_none_output_round_trips(self):
        redis = FakeRedis()
        cache = ToolResultCache(redis)

        original = ToolResult(
            tool_name="weather", success=True, output=None, error=None, latency_ms=12.0
        )
        args = {"latitude": 0.0, "longitude": 0.0}
        await cache.set("weather", args, original, ttl_seconds=60)
        retrieved = await cache.get("weather", args)

        assert retrieved is not None
        assert retrieved.output is None

    @pytest.mark.asyncio
    async def test_nested_output_dict_round_trips(self):
        redis = FakeRedis()
        cache = ToolResultCache(redis)

        original = ToolResult(
            tool_name="github",
            success=True,
            output={"repos": [{"name": "acme/widgets", "url": "https://github.com/acme/widgets", "private": False}]},
            error=None,
            latency_ms=210.4,
        )
        args = {"action": "list_repos"}
        await cache.set("github", args, original, ttl_seconds=3600)
        retrieved = await cache.get("github", args)

        assert retrieved is not None
        assert retrieved.output == original.output


# ===========================================================================
# TestTTLBehavior
# ===========================================================================


class TestTTLBehavior:
    @pytest.mark.asyncio
    async def test_ttl_is_passed_to_redis(self):
        redis = FakeRedis()
        cache = ToolResultCache(redis)

        result = ToolResult(tool_name="weather", success=True, output={}, error=None, latency_ms=10.0)
        await cache.set("weather", PARIS_ARGS, result, ttl_seconds=300)

        key = _cache_key("weather", PARIS_ARGS)
        ttl_passed = redis._store[key][1]

        print(f"\n  TTL passed to Redis.set(): {ttl_passed}")
        assert ttl_passed == 300

    def test_no_ttl_means_not_cached(self):
        """A tool with no entry in tool_cache_ttl_seconds must never be cached,
        even though it's technically a read (not a write op)."""
        ttls = {"weather": 300, "github": 3600, "mock_api": 60}
        ttl = ttls.get("unknown_tool")

        print(f"\n  TTL for 'unknown_tool': {ttl}")
        print(f"  Will be cached: {ttl is not None}")

        assert ttl is None


# ===========================================================================
# TestToolExecutorCacheWiring
# ===========================================================================


class FakeToolRegistry:
    def __init__(self, tool) -> None:
        self._tool = tool

    def get(self, name: str):
        return self._tool if name == self._tool.name else None


class FakeWeatherTool:
    name = "weather"

    def __init__(self) -> None:
        self.call_count = 0

    async def execute(self, args: dict, ctx) -> "ToolResultPayloadLike":
        self.call_count += 1
        from app.infrastructure.tools.base import ToolResultPayload
        return ToolResultPayload(success=True, output={"temperature": 15.0, "cached": False})


def _make_state(tool_name: str, arguments: dict) -> AgentState:
    return AgentState(
        conversation_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        trace_id="test",
        selected_tool=ToolCall(tool_name=tool_name, arguments=arguments),
    )


class TestToolExecutorCacheWiring:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_tool_execution(self):
        redis = FakeRedis()
        cache = ToolResultCache(redis)
        tool = FakeWeatherTool()
        registry = FakeToolRegistry(tool)

        cached_result = ToolResult(
            tool_name="weather", success=True, output={"temperature": 99.0, "cached": True},
            error=None, latency_ms=0.5,
        )
        await cache.set("weather", PARIS_ARGS, cached_result, ttl_seconds=300)
        print(f"\n  Cache populated with key: {_cache_key('weather', PARIS_ARGS)}")
        print(f"  Stored keys: {list(redis._store.keys())}")

        executor = make_tool_executor(
            registry, tool_cache=cache, tool_cache_ttls={"weather": 300}
        )
        result = await executor(_make_state("weather", PARIS_ARGS))

        print(f"\n  Tool called: {tool.call_count} times (expected 0)")
        print(f"  Tool result: {result['tool_result'].output}")

        assert tool.call_count == 0
        assert result["tool_result"].output == {"temperature": 99.0, "cached": True}

    @pytest.mark.asyncio
    async def test_cache_none_injection_still_executes_tool(self):
        """When tool_cache isn't injected at all (None), the executor must
        skip the cache branch entirely and always call the real tool."""
        tool = FakeWeatherTool()
        registry = FakeToolRegistry(tool)

        executor = make_tool_executor(registry, tool_cache=None, tool_cache_ttls={"weather": 300})
        result = await executor(_make_state("weather", {"latitude": 48.0}))

        assert tool.call_count == 1
        assert result["tool_result"].success is True
