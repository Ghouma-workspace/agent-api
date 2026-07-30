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
