# AI API Assistant

A production-shaped AI platform: a LangGraph agent that calls tools (GitHub, Weather,
Jira/Notion/Trello/Slack/Stripe stubs) through GroqCloud, wrapped in clean-architecture
FastAPI backend with full observability (OpenTelemetry → Jaeger, Prometheus → Grafana,
structured logging, Langfuse), JWT auth, Postgres persistence, and a ChatGPT-style
React frontend.

The LLM's job here is intentionally simple (decide tool vs. no tool, pick arguments).
The point of the project is everything around it: layering, DI, observability,
reliability, and deployability.

## Quick start

```bash
cp .env.example .env
# fill in GROQ_API_KEY at minimum (free tier: https://console.groq.com)
make up
```

This brings up: `backend` (FastAPI, :8000), `frontend` (:5173), `postgres` (:5432),
`redis` (:6379), `jaeger` (:16686), `prometheus` (:9090), `grafana` (:3000,
admin/admin), `langfuse` (:3001).

Run migrations (the backend container does this automatically on start, but manually):
```bash
make migrate
```

Run tests:
```bash
make test
```

## Where to look

| Want to understand... | Look at |
|---|---|
| Overall design | `docs/ARCHITECTURE.md` |
| Folder layout rationale | `docs/FOLDER_STRUCTURE.md` |
| The LangGraph agent | `backend/app/application/agent/graph.py` + `nodes/` |
| How a tool is added | `backend/app/infrastructure/tools/` + `registry.py` |
| DI / composition root | `backend/app/core/container.py` |
| Observability wiring | `backend/app/infrastructure/observability/` |
| API surface | `backend/app/api/v1/routers/`, or `GET /docs` once running |
| Frontend chat UI | `frontend/src/pages/ChatPage.tsx` |
| Admin dashboard | `frontend/src/pages/AdminPage.tsx`, Grafana at `:3000` |
| CI pipeline | `.github/workflows/ci.yml` |
| Cloud deployment example | `infra/terraform/main.tf` |

## Adding a new tool

1. Subclass `BaseToolPlugin` in `backend/app/infrastructure/tools/your_tool.py`,
   declaring `name`, `description`, `parameters_schema`, and `execute()`.
2. Add the class to `ToolRegistry._PLUGIN_CLASSES` in `registry.py`.

That's the entire change — no router, service, or agent-node edits required.

## Swapping the LLM provider

Write `OpenAIProvider`/`AnthropicProvider` implementing `domain.providers.interfaces.LLMProvider`
(`complete()` + `stream()`), then change one line in `core/container.py`:
`self.llm_provider = GroqProvider(settings)` → your new class.

## Known simplifications (by design, given the LLM is intentionally the "dumb" part)

- Celery/background task queue was scoped out — the only currently-justified async
  work (conversation summarization) is small enough to run inline; the Redis-backed
  queue slot is there (`infrastructure/cache/`) if that changes.
- Circuit breaker is a single retry policy (`tenacity`) per tool rather than a full
  open/half-open/closed state machine — noted as the natural next step in
  `infrastructure/tools/base.py`.
- Five of the eight tools (Jira, Notion, Trello, Slack, Stripe) are stubs proving the
  extensibility pattern; GitHub and Weather are fully wired to real APIs.

---

## V2 — Production Hardening

V2 adds eleven production-hardening capabilities on top of the V1 foundation. Every change follows the same constraints: clean-architecture layering, a single composition root, and full graceful degradation — the system serves chat requests even if Celery, Langfuse, or any new Redis operation is unavailable.

### Section 1 — Structured LLM outputs (Pydantic validation)

The planner node now uses Groq's JSON mode and validates the response against `PlannerOutput(BaseModel)`. Fields: `needs_tool: bool`, `tool_name: str | None`, `reasoning: str`. The `reasoning` field is the single most important debugging signal — it appears in Langfuse, structlog, and `AgentState`. If the LLM returns malformed JSON or a schema mismatch, a domain `ValidationError` is raised (never a silent fallthrough); the retry handler catches it.

### Section 2 — Prompt versioning via Langfuse

All hardcoded prompt strings are now fetched from Langfuse's prompt management API at runtime. `PromptService.get(name, fallback=CONSTANT)` returns the Langfuse version when available; on any failure (Langfuse unreachable, prompt not found, client not configured), it returns the fallback constant and logs a warning — the system never crashes because Langfuse is unavailable. Set `LANGFUSE_ENABLE_PROMPT_MANAGEMENT=false` in `.env` to always use local fallbacks (recommended for local dev without Langfuse configured).

**Prompt names:** `planner_system`, `tool_selector_system`, `response_generator_system`.

### Section 3 — Conversation summarization (Celery)

Long conversations are automatically compacted to keep token budgets sane. After every 20th message, `ChatService` dispatches a `summarize_conversation` Celery task. The task:
1. Loads the full message history (sync SQLAlchemy session — Celery workers are synchronous).
2. Skips if fewer than 20 messages.
3. Calls `llama-3.1-8b-instant` (hardcoded cheap model) to summarize messages 1 through N-10.
4. Inserts a `[Conversation summary]: …` system message at position 0.
5. Deletes the original early messages.
6. Invalidates the Redis conversation memory cache.

Two new services: `celery-worker` (runs the tasks) and `flower` (monitoring at `:5555`). Celery uses Redis DB index 2 to avoid colliding with the app (index 0) and Langfuse (index 1). If Celery is unavailable, `send_message` continues normally (fire-and-forget dispatch, exception swallowed).

### Section 4 — Tool result caching (Redis)

Identical tool calls within the configured TTL return cached results without hitting external APIs. Cache keys use `sha256[:16]` of sorted-key JSON arguments for determinism. Write operations (keys/values containing `create`, `post`, `delete`, etc.) are never cached. Per-tool TTLs are configurable:

```
TOOL_CACHE_TTL_SECONDS={"weather": 300, "github": 3600, "mock_api": 60}
```

`CACHE_HITS_TOTAL` and `CACHE_MISSES_TOTAL` Prometheus counters are incremented on every cache access.

### Section 5 — Per-tool rate limiting (sliding window)

External APIs have their own rate limits; we enforce them before hitting the network. A Redis sorted-set sliding window (more accurate than fixed window at boundary conditions) tracks calls per tool per 60-second window. Raises `ToolExecutionError(retryable=True)` when exceeded. Fails-open if Redis is unavailable. Configure per-tool limits:

```
TOOL_RATE_LIMITS={"github": 50, "weather": 50, "slack": 20, "stripe": 30}
```

### Section 6 — Circuit breaker per tool

Prevents cascading failures when an external API is consistently down. Three states stored in Redis per tool:
- **CLOSED** (normal) — calls pass through, failures counted.
- **OPEN** (failing fast) — `ToolExecutionError(retryable=False)` raised immediately. After `recovery_timeout=60s`, transitions to HALF_OPEN.
- **HALF_OPEN** (probe) — one call allowed through. Success × 2 → CLOSED; any failure → back to OPEN.

The `/api/tools/circuit-status` endpoint returns current state for every registered tool. A `circuit_breaker_state` Gauge (0=CLOSED, 1=HALF_OPEN, 2=OPEN) is updated on every transition and visible in the Tool Execution Grafana dashboard.

### Section 7 — Content filter (injection detection)

The content filter is the graph's entry point — it runs before the planner on every request. Pure Python string matching (no LLM call) checks for nine prompt-injection patterns case-insensitively. On trigger: sets `draft_response` to a user-friendly refusal, sets `error="content_filter_triggered"`, and routes directly to END. The triggering **pattern** is logged; the full user message is **never** logged (it may contain credentials or PII). A `content_filter_triggers_total` Prometheus counter is incremented.

Patterns detected: `ignore previous instructions`, `ignore all instructions`, `you are now`, `new persona`, `jailbreak`, `disregard your`, `system:`, `###instruction`, `<|im_start|>`.

### Section 8 — JWT hardening

Access and refresh tokens now carry an `aud: "ai-api-assistant"` claim. `JWTService.decode()` validates audience and rejects tokens with wrong or missing `aud`. On login, a `device_id` (UUID) is generated and stored in the `sessions` table. On refresh, the device ID is validated — a refresh token cannot be used from a different device. `last_seen_ip` is updated in `sessions` on every successful refresh.

New DB columns (migration `0002_v2_hardening`): `sessions.device_id`, `sessions.last_seen_ip`, `conversations.summarized_up_to`.

### Section 9 — Secrets redaction in logs

A structlog processor (`redacting_processor`) runs on every log line before JSON rendering. It recursively redacts any key matching `*key*`, `*token*`, `*secret*`, `*password*`, `*auth*`, `*credential*` (case-insensitive) and truncates string values longer than 200 chars to `value[:50] + "...[truncated]"`. Tool executor redacts arguments before passing to OTel span attributes and Langfuse.

### Section 10 — Grafana dashboards

Three new dashboards in `observability/grafana/dashboards/`:

| Dashboard | UID | Key panels |
|---|---|---|
| `tool_execution.json` | `tool-execution-v2` | Executions/min, p50/95/99 latency heatmap, error rate, circuit breaker stat panels (green/yellow/red), cache hit rate gauge |
| `llm_cost.json` | `llm-cost-v2` | Cumulative cost by model, prompt vs completion token ratio, cost/hour bar chart, estimated cache savings |
| `agent_health.json` | `agent-health-v2` | Node p95 latency bar chart, retry rate, validation loop count, error rate by node, content filter trigger rate, active users gauge |


### Environment variables added in V2

| Variable | Default | Description |
|---|---|---|
| `LANGFUSE_ENABLE_PROMPT_MANAGEMENT` | `true` | Set to `false` for local dev without Langfuse |
| `TOOL_CACHE_TTL_SECONDS` | `{"weather":300,...}` | Per-tool cache TTL in seconds |
| `TOOL_RATE_LIMITS` | `{"github":50,...}` | Per-tool sliding-window rate limits (req/min) |
