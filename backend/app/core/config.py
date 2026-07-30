"""Centralized application configuration.

All configuration is read from environment variables (12-factor). Nothing in the rest
of the codebase should call `os.environ` directly — inject `Settings` instead.
"""
from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "ai-api-assistant"
    environment: Literal["local", "test", "staging", "production"] = "local"
    debug: bool = False
    api_v1_prefix: str = "/api"

    # --- Auth ---
    jwt_secret_key: SecretStr = Field(default=SecretStr("change-me-in-env"))
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # --- Database ---
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_assistant"
    )
    db_pool_size: int = 10
    db_echo: bool = False

    # --- Redis ---
    redis_url: RedisDsn = Field(default="redis://localhost:6379/0")
    rate_limit_requests_per_minute: int = 60

    # --- LLM ---
    llm_provider: Literal["groq"] = "groq"
    groq_api_key: SecretStr = Field(default=SecretStr(""))
    groq_model: str = "llama-3.3-70b-versatile"
    llm_request_timeout_seconds: float = 30.0

    # --- Agent ---
    agent_max_tool_retries: int = 3
    agent_max_validation_loops: int = 2

    # --- Observability ---
    otel_exporter_otlp_endpoint: str = "http://jaeger:4317"
    otel_service_name: str = "ai-api-assistant-backend"
    prometheus_metrics_path: str = "/metrics"
    langfuse_public_key: SecretStr = Field(default=SecretStr(""))
    langfuse_secret_key: SecretStr = Field(default=SecretStr(""))
    langfuse_host: str = "https://cloud.langfuse.com"
    log_level: str = "INFO"

    # --- Tool credentials (resolved through CredentialProvider, never read directly by tools) ---
    github_token: SecretStr = Field(default=SecretStr(""))
    weather_api_key: SecretStr = Field(default=SecretStr(""))


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton — safe to call repeatedly, reads env once."""
    return Settings()
