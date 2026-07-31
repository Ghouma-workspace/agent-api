"""The composition root. This is the ONLY file in the codebase allowed to import both
a domain interface and its concrete infrastructure implementation and wire them
together. Every other module receives its dependencies through constructor injection.

Swapping an implementation (Groq -> OpenAI, Postgres -> anything else) means editing
exactly this file plus writing the new adapter class."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.agent.graph import build_agent_graph
from app.application.services.admin_service import AdminService
from app.application.services.auth_service import AuthService
from app.application.services.chat_service import ChatService
from app.application.services.tool_service import ToolService
from app.core.config import Settings
from app.infrastructure.cache.redis_client import (
    RedisConversationMemory,
    RedisRateLimiter,
    create_redis_client,
)
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
from app.infrastructure.tools.registry import ToolRegistry


class Container:
    """Request-scoped services (repositories) are constructed per-request via
    `for_request(session)`; singletons (LLM provider, tool registry, JWT service,
    Redis, the compiled agent graph) live for the lifetime of the app."""

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

        self.llm_provider = GroqProvider(settings)  # swap here for OpenAIProvider/AnthropicProvider
        self.langfuse = LangfuseTracker(create_langfuse_client(settings))

        self.agent_graph = build_agent_graph(self.llm_provider, self.tool_registry, settings)

        self.tool_service = ToolService(self.tool_registry)

    def request_scope(self, session: AsyncSession) -> RequestScope:
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
