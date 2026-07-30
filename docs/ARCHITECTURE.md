# AI API Assistant — Architecture Design (Phase 1)

## 1. Design Philosophy

This system is a backend/platform engineering showcase wrapped around an intentionally
simple LLM agent. The agent's job is to decide *which tool to call*; the engineering's
job is to make that decision observable, reliable, testable, and swappable at every layer.

Guiding principles:

- **Clean / Hexagonal Architecture** — domain logic has zero knowledge of FastAPI,
  SQLAlchemy, Groq, or Redis. Everything talks to the domain through ports (interfaces).
- **Dependency Inversion everywhere** — routers depend on service interfaces, services
  depend on repository interfaces, agent nodes depend on `LLMProvider` and `ToolRegistry`
  interfaces. Concrete implementations are wired at the composition root only.
- **Replaceability** — swapping Groq → OpenAI, Postgres → any SQL DB, or Redis → in-memory
  cache should touch only one adapter file plus one line of DI wiring.
- **Everything is observable** — no code path executes without a span, a structured log
  line, and (where relevant) a Prometheus metric.

## 2. Layered Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Interface Layer          FastAPI routers, WebSocket/SSE, deps   │
│  (api/)                   Pydantic request/response schemas      │
├─────────────────────────────────────────────────────────────────┤
│  Application Layer        Use cases / services                   │
│  (application/)           ChatService, AuthService, ToolService   │
│                           AgentOrchestrator (wraps LangGraph)     │
├─────────────────────────────────────────────────────────────────┤
│  Domain Layer             Entities, value objects, domain events  │
│  (domain/)                Repository & Provider *interfaces*      │
│                           No external deps (framework-free)       │
├─────────────────────────────────────────────────────────────────┤
│  Infrastructure Layer     SQLAlchemy repos, Redis cache, Groq     │
│  (infrastructure/)        client, tool plugin implementations,    │
│                           OTel exporters, Langfuse client         │
└─────────────────────────────────────────────────────────────────┘
```

Dependency rule: arrows only point **inward**. Infrastructure depends on Domain
interfaces; Domain depends on nothing.

## 3. Component Map

```
                                   ┌────────────────────┐
                                   │   React Frontend    │
                                   │ (chat, timeline,    │
                                   │  admin dashboard)   │
                                   └──────────┬──────────┘
                                              │ REST + SSE
                                   ┌──────────▼──────────┐
                                   │     FastAPI App      │
                                   │  (api/ routers, DI)  │
                                   └───┬───────────────┬──┘
                    ┌──────────────────┘               └───────────────────┐
          ┌─────────▼─────────┐                              ┌────────────▼───────────┐
          │   AuthService       │                              │     ChatService          │
          │  (JWT, refresh,     │                              │  orchestrates a turn:    │
          │   sessions)         │                              │  persists msg, invokes   │
          └─────────┬───────────┘                              │  AgentOrchestrator,      │
                    │                                          │  streams response        │
          ┌─────────▼─────────┐                              └────────────┬───────────┘
          │  UserRepository     │                                           │
          │  (Postgres)         │                              ┌────────────▼───────────┐
          └─────────────────────┘                              │   AgentOrchestrator      │
                                                                 │   (LangGraph graph)      │
                                                                 └────────────┬───────────┘
                     ┌───────────────────────┬───────────────────────────────┼───────────────────┐
             ┌───────▼───────┐      ┌────────▼────────┐          ┌──────────▼─────────┐  ┌────────▼────────┐
             │  Planner node  │      │ Tool Selector    │          │  Tool Executor       │  │ Response Gen /   │
             │                │      │ node             │          │  node                │  │ Validator /      │
             │                │      │                  │          │                      │  │ Error+Retry node │
             └───────┬────────┘      └────────┬─────────┘          └──────────┬───────────┘  └────────┬─────────┘
                     │                        │                               │                        │
             ┌───────▼────────┐      ┌────────▼─────────┐          ┌──────────▼───────────┐            │
             │ LLMProvider     │      │  ToolRegistry     │          │  ToolPlugin(s)        │            │
             │ interface       │      │  (plugin lookup)  │          │  GitHub / Weather /   │            │
             │ → GroqProvider  │      └───────────────────┘          │  Mock / Jira / ...    │            │
             └────────┬────────┘                                    └──────────┬────────────┘            │
                      │                                                        │                          │
             ┌────────▼─────────────────────────────────────────────────────────▼──────────────────────────▼────────┐
             │                          Cross-cutting: OTel tracer, Prometheus metrics, structured logger,           │
             │                          Langfuse tracker — injected into every node via middleware/decorators        │
             └───────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 4. Request Lifecycle (Sequence)

```
Client                FastAPI            AuthMiddleware      ChatService        AgentOrchestrator      LLM/Tools           DB/Redis
  │  POST /api/chat      │                     │                  │                    │                    │                  │
  │─────────────────────▶│                     │                  │                    │                    │                  │
  │                      │── verify JWT ──────▶│                  │                    │                    │                  │
  │                      │◀── user_id ──────────│                  │                    │                    │                  │
  │                      │── span:http ─────────────────────────────────────────────────────────────────────────────────────────▶│ (trace start)
  │                      │── save user msg ────────────────────────────────────────────────────────────────────────────────────▶│
  │                      │── invoke() ─────────▶│                  │                    │                    │                  │
  │                      │                      │── run graph ────▶│                    │                    │                  │
  │                      │                      │                  │── Planner ────────▶│                    │                  │
  │                      │                      │                  │── Tool Selector ──▶│                    │                  │
  │                      │                      │                  │── Tool Executor ──────────────────────▶│ (call GitHub API)│
  │                      │                      │                  │◀── tool result ─────────────────────────│                  │
  │                      │                      │                  │── Response Gen ───▶│── Groq call ──────▶│                  │
  │                      │                      │                  │◀── completion ──────────────────────────│                  │
  │                      │                      │                  │── Validator ──────▶│                    │                  │
  │◀── SSE stream tokens ─────────────────────────────────────────────────────────────────────────────────────                  │
  │                      │── persist assistant msg + trace + cost ─────────────────────────────────────────────────────────────▶│
  │◀── final payload (trace_id, tokens, cost) ──│                  │                    │                    │                  │
```

Every hop above emits: one OTel span, one structured JSON log line, and (where applicable)
a Prometheus metric observation. Trace context (`trace_id`, `span_id`) is propagated via
`contextvars` through the whole async call chain and attached to every log line and to the
API response so the frontend can deep-link into Jaeger/Langfuse.

## 5. LangGraph Agent Design

State object (`AgentState`, a `TypedDict`/pydantic model) flows through the graph:

```python
class AgentState(BaseModel):
    conversation_id: UUID
    user_id: UUID
    messages: list[ChatMessage]
    plan: Plan | None = None
    selected_tool: ToolCall | None = None
    tool_result: ToolResult | None = None
    draft_response: str | None = None
    validation_errors: list[str] = []
    retry_count: int = 0
    trace_id: str
```

Graph topology:

```
        ┌─────────┐
        │ Planner │  decides: "needs tool" vs "direct answer"
        └────┬────┘
             │
       needs_tool? ──No──▶ ┌──────────────────┐
             │              │ Response Generator│──▶ Validator ──▶ END
            Yes             └──────────────────┘
             ▼
     ┌───────────────┐
     │ Tool Selector  │  picks tool + extracts args via LLM function-calling
     └───────┬────────┘
             ▼
     ┌───────────────┐        failure       ┌───────────────┐
     │ Tool Executor  │──────────────────────▶ Error Handler  │
     └───────┬────────┘                     └───────┬────────┘
        success │                                    │ retryable?
                ▼                              yes ◀──┴──▶ no
        ┌──────────────────┐                    │            │
        │ Response Generator│                    ▼            ▼
        └───────┬───────────┘            ┌──────────────┐  ┌─────────────────┐
                 ▼                        │ Retry Handler │  │ user-friendly    │
           ┌───────────┐                  │ (backoff,     │  │ error response   │
           │ Validator  │                  │  max 3 tries) │  └─────────────────┘
           └─────┬──────┘                  └──────┬────────┘
             valid? │                              │
           yes ◀────┴────▶ no (loop back to        ▼
            │              Tool Selector,    back to Tool Executor
            ▼              max 2 loops)
           END
```

Each node is a small async function registered on the `StateGraph`, wrapped by a
`@traced_node("planner")` decorator that:
1. opens an OTel span named `agent.node.<name>`
2. logs structured entry/exit with latency
3. records a Prometheus histogram `agent_node_duration_seconds{node=...}`
4. pushes the node's input/output to Langfuse as a generation/span

## 6. Tool Plugin Framework

```python
class ToolPlugin(Protocol):
    name: str
    description: str
    parameters_schema: dict  # JSON schema for LLM function-calling

    async def execute(self, args: dict, ctx: ToolExecutionContext) -> ToolResult: ...
    async def health_check(self) -> bool: ...
```

- `ToolRegistry` discovers plugins via entry points / explicit registration list —
  adding a tool = drop a new class in `infrastructure/tools/` + one line in the registry.
- Each plugin wraps outbound HTTP calls with a shared `ResilientHTTPClient`
  (timeout + retry + circuit breaker via `tenacity`/`purgatory` or hand-rolled).
- Secrets (API keys) are resolved through a `CredentialProvider` port, so tools never read
  `os.environ` directly — keeps them testable and swappable (env vars now, vault later).

## 7. LLM Provider Abstraction

```python
class LLMProvider(Protocol):
    async def complete(self, messages, tools, **kwargs) -> LLMResponse: ...
    async def stream(self, messages, tools, **kwargs) -> AsyncIterator[LLMChunk]: ...

class GroqProvider(LLMProvider): ...
```

`AgentOrchestrator` and every node depend only on `LLMProvider`. Provider is chosen by
config (`LLM_PROVIDER=groq`) and constructed once in the DI container.

## 8. Data Model (ER Overview)

```
users ──< conversations ──< messages
  │                              │
  │                              └──< tool_executions >── tool_definitions
  │
  └──< sessions (refresh tokens)

messages ──< llm_usage (tokens, cost, model, latency)
conversations ──< execution_traces (trace_id, span tree summary, duration)
```

Full DDL comes in Phase 5 (Database). Every domain-relevant write also emits a
`llm_usage` and/or `tool_executions` row so cost/latency dashboards need no external
system beyond Postgres + Prometheus.

## 9. Observability Architecture

```
FastAPI (OTel instrumentation) ──▶ OTLP exporter ──▶ Jaeger (traces)
Prometheus client middleware   ──▶ /metrics        ──▶ Prometheus ──▶ Grafana
structlog JSON processor       ──▶ stdout          ──▶ (docker logs / any log shipper)
Langfuse SDK (per agent node)  ──▶ Langfuse server ──▶ Langfuse UI (prompt/cost/feedback)
```

A single `trace_id` (W3C traceparent) ties together the Jaeger trace, the Langfuse trace,
and the `request_id` in every log line — that's the thread the frontend's "Trace ID" link
follows.

## 10. Error Handling Strategy

| Layer | Mechanism |
|---|---|
| HTTP boundary | typed exception → `ProblemDetail` JSON, correct status code |
| Tool calls | `tenacity` retry (exponential backoff, 3 attempts) + circuit breaker per tool |
| LLM calls | retry on 429/5xx, fallback message on exhaustion |
| Agent graph | dedicated `Error Handler` + `Retry Handler` nodes, capped retry_count |
| Global | FastAPI exception handlers → structured log + Prometheus `errors_total` counter |

## 11. Security & Auth

- JWT access tokens (short-lived, 15 min) + refresh tokens (rotating, stored hashed in
  `sessions` table, revocable).
- Passwords hashed with argon2.
- Per-user rate limiting via Redis token bucket, enforced in middleware before hitting
  the agent (protects LLM spend).

## 12. What Ships in Which Phase

This document is Phase 1. Phases 2–10 will implement, in order: folder structure →
backend foundation (FastAPI app, DI container, config) → auth → database/migrations →
LangGraph agent → tool framework (2–3 real tools + stubs) → observability stack →
frontend → docker-compose deployment. CI/CD, Terraform, and the full test/doc suite are
layered in alongside their related phases rather than as one final phase, so each phase
lands in a runnable state.
