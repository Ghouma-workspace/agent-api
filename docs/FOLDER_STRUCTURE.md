# Folder Structure (Phase 2)

```
ai-api-assistant/
├── backend/
│   ├── app/
│   │   ├── api/                        # Interface layer — HTTP only, no business logic
│   │   │   ├── v1/
│   │   │   │   ├── routers/            # chat.py, conversations.py, tools.py, users.py, auth.py, admin.py
│   │   │   │   └── schemas/            # Pydantic request/response DTOs (never domain entities directly)
│   │   │   └── deps/                   # FastAPI Depends() providers — pulls from the DI container
│   │   │
│   │   ├── application/                # Use-case orchestration, framework-agnostic-ish
│   │   │   ├── services/               # ChatService, AuthService, ToolService, AdminService
│   │   │   └── agent/                  # LangGraph wiring
│   │   │       ├── graph.py            # StateGraph construction
│   │   │       ├── state.py            # AgentState model
│   │   │       └── nodes/              # planner.py, tool_selector.py, tool_executor.py,
│   │   │                                #   response_generator.py, validator.py, error_handler.py, retry_handler.py
│   │   │
│   │   ├── domain/                     # Pure business logic — zero framework imports
│   │   │   ├── entities/               # User, Conversation, Message, ToolExecution, LLMUsage (dataclasses/pydantic)
│   │   │   ├── repositories/           # Abstract repo interfaces (Protocol/ABC)
│   │   │   ├── providers/              # LLMProvider, CredentialProvider interfaces
│   │   │   └── exceptions/             # Domain-level exceptions (no HTTP status codes here)
│   │   │
│   │   ├── infrastructure/             # Concrete adapters — implements domain interfaces
│   │   │   ├── db/
│   │   │   │   ├── models/             # SQLAlchemy ORM models
│   │   │   │   ├── repositories/       # SQLAlchemy implementations of domain repositories
│   │   │   │   └── migrations/         # Alembic env + versions/
│   │   │   ├── cache/                  # Redis client, RateLimiter, ConversationMemoryCache
│   │   │   ├── llm/                    # GroqProvider (implements LLMProvider)
│   │   │   ├── tools/                  # ToolPlugin implementations + ToolRegistry
│   │   │   ├── observability/          # OTel setup, Prometheus metrics, structlog config, Langfuse client
│   │   │   └── security/               # JWT encode/decode, password hashing
│   │   │
│   │   └── core/                       # Composition root: config.py, container.py (DI), main.py wiring
│   │
│   └── tests/
│       ├── unit/                       # domain + application, no I/O, no DB
│       ├── integration/                # DB + Redis via testcontainers
│       ├── agent/                      # LangGraph node/graph tests with fake LLMProvider
│       └── api/                        # httpx.AsyncClient end-to-end API tests
│
├── frontend/
│   └── src/
│       ├── api/                        # typed API client (fetch wrappers, SSE client)
│       ├── components/
│       │   ├── chat/                   # ChatWindow, MessageList, ToolTimeline, TraceBadge
│       │   ├── admin/                   # UsageChart, ErrorTable, ActiveUsers
│       │   └── layout/                 # Sidebar, ConversationList, TopBar
│       ├── hooks/                      # useChatStream, useConversations (TanStack Query)
│       ├── pages/                      # ChatPage, AdminPage, LoginPage
│       ├── store/                      # lightweight client state (auth token, ui state)
│       └── types/                      # shared TS types mirroring backend schemas
│
├── observability/
│   ├── prometheus/                     # prometheus.yml scrape config
│   └── grafana/
│       ├── dashboards/                 # JSON dashboard definitions
│       └── provisioning/               # datasources.yml, dashboards.yml
│
├── infra/terraform/                    # optional cloud deployment (ECS/Fargate example)
├── .github/workflows/                  # ci.yml (lint, test, coverage, docker build)
└── docs/                               # architecture, diagrams, this file, README, guides
```

## Why this shape

- **`domain/` has no imports from FastAPI, SQLAlchemy, or LangChain.** It's the one folder that
  should compile even if every other folder were deleted. This is what makes the repository
  pattern and provider abstraction real rather than decorative.
- **`infrastructure/` is the only place allowed to import third-party SDKs** (`groq`, `redis`,
  `sqlalchemy`, `langgraph`). Swapping Groq for OpenAI touches only `infrastructure/llm/`.
- **`core/container.py`** is the single composition root — the only file that imports both a
  domain interface and its concrete infrastructure implementation and wires them together.
  Everywhere else uses constructor injection against the interface.
- **Tests mirror the layers**, not the folders 1:1 — `unit/` tests domain+application with fakes,
  `integration/` spins up real Postgres/Redis, `agent/` tests the LangGraph graph in isolation
  with a fake `LLMProvider`, `api/` drives the whole stack through HTTP.
