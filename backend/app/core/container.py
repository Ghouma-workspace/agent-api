"""The composition root. This is the ONLY file in the codebase allowed to import both
a domain interface and its concrete infrastructure implementation and wire them
together. Every other module receives its dependencies through constructor injection.

Swapping an implementation (Groq -> OpenAI, Postgres -> anything else) means editing
exactly this file plus writing the new adapter class.

V2 additions wired here:
  - PromptService       (Section 2)
  - ToolResultCache     (Section 4)
  - ToolRateLimiter     (Section 5)
  - CircuitBreaker      (Section 6)
  All new services are constructed here and injected into build_agent_graph.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.agent.graph import build_agent_graph
from app.application.services.admin_service import AdminService
from app.application.services.auth_service import AuthService
from app.application.services.chat_service import ChatService
from app.application.services.prompt_service import PromptService
from app.application.services.tool_service import ToolService
from app.core.config import Settings
from app.infrastructure.cache.redis_client import (
    RedisConversationMemory,
    RedisRateLimiter,
    create_redis_client,
)
from app.infrastructure.cache.tool_cache import ToolResultCache
from app.infrastructure.cache.tool_rate_limiter import ToolRateLimiter
from app.infrastructure.db.repositories.chat_repository import (
    SqlAlchemyConversationRepository,
    SqlAlchemyLLMUsageRepository,
    SqlAlchemyMessageRepository,
    SqlAlchemyToolExecutionRepository,
)
from app.infrastructure.db.repositories.user_repository import (
    SqlAlchemySessionRepository,
    SqlAlchemyUserRepository,
)
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.llm.groq_provider import GroqProvider
from app.infrastructure.observability.langfuse_client import LangfuseTracker, create_langfuse_client
from app.infrastructure.security.jwt import JWTService, PasswordHasher
from app.infrastructure.tools.base import EnvCredentialProvider
from app.infrastructure.tools.circuit_breaker import CircuitBreaker
from app.infrastructure.tools.registry import ToolRegistry


class Container:
    """Singletons live for the lifetime of the app. Request-scoped services are in
    RequestScope, constructed fresh per request via a middleware/dependency."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        # --- Singletons ---
        self.engine = create_engine(settings)
        self.session_factory = create_session_factory(self.engine)
        self.redis = create_redis_client(settings)
        self.rate_limiter = RedisRateLimiter(self.redis, settings.rate_limit_requests_per_minute)
        self.conversation_memory = RedisConversationMemory(self.redis)

        self.jwt_service = JWTService(settings)
        self.password_hasher = PasswordHasher()

        self.credential_provider = EnvCredentialProvider(settings)
        self.tool_registry = ToolRegistry(self.credential_provider)

        self.llm_provider = GroqProvider(settings)

        _langfuse_client = create_langfuse_client(settings)
        self.langfuse = LangfuseTracker(_langfuse_client)

        # --- V2: Prompt versioning (Section 2) ---
        self.prompt_service = PromptService(
            _langfuse_client,
            enable=settings.langfuse_enable_prompt_management,
        )

        # --- V2: Tool result cache (Section 4) ---
        self.tool_cache = ToolResultCache(self.redis)

        # --- V2: Per-tool rate limiter (Section 5) ---
        self.tool_rate_limiter = ToolRateLimiter(self.redis, settings.tool_rate_limits)

        # --- V2: Circuit breaker (Section 6) —shared instance, one state machine per tool ---
        self.circuit_breaker = CircuitBreaker(
            self.redis,
            failure_threshold=5,
            recovery_timeout=60,
            success_threshold=2,
        )

        # Build the compiled agent graph with all V2 infrastructure injected
        self.agent_graph = build_agent_graph(
            self.llm_provider,
            self.tool_registry,
            self.prompt_service,
            settings,
            tool_cache=self.tool_cache,
            tool_rate_limiter=self.tool_rate_limiter,
            circuit_breaker=self.circuit_breaker,
        )

        self.tool_service = ToolService(self.tool_registry)

    def request_scope(self, session: AsyncSession) -> "RequestScope":
        return RequestScope(self, session)


class RequestScope:
    """Per-request repositories + services that depend on a live DB session.
    Constructed fresh for every request via a middleware/dependency (see api/deps)."""

    def __init__(self, container: Container, session: AsyncSession) -> None:
        self.user_repo = SqlAlchemyUserRepository(session)
        self.session_repo = SqlAlchemySessionRepository(session)
        self.conversation_repo = SqlAlchemyConversationRepository(session)
        self.message_repo = SqlAlchemyMessageRepository(session)
        self.tool_execution_repo = SqlAlchemyToolExecutionRepository(session)
        self.llm_usage_repo = SqlAlchemyLLMUsageRepository(session)

        self.auth_service = AuthService(
            self.user_repo,
            self.session_repo,
            container.jwt_service,
            container.password_hasher,
            container.settings,
        )
        self.chat_service = ChatService(
            container.agent_graph, self.conversation_repo, self.message_repo, container.langfuse
        )
        self.admin_service = AdminService(self.llm_usage_repo, container.tool_registry)
