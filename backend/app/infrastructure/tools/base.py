from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class ToolResultPayload:
    success: bool
    output: dict | None = None
    error: str | None = None


@dataclass
class ToolExecutionContext:
    user_id: str
    conversation_id: str
    trace_id: str


class EnvCredentialProvider:
    """Implements domain.providers.interfaces.CredentialProvider. Reads from Settings
    today; swap to Vault/Secrets Manager later without touching any tool plugin."""

    def __init__(self, settings) -> None:
        self._settings = settings

    def get_secret(self, key: str) -> str:
        value = getattr(self._settings, key, None)
        if value is None:
            return ""
        return value.get_secret_value() if hasattr(value, "get_secret_value") else str(value)


class ResilientHTTPClient:
    """Shared outbound HTTP client every tool plugin uses: timeout + retry baked in.
    A circuit breaker (open/half-open/closed per host) would wrap this in production;
    kept as a single retry policy here to keep the tool layer legible."""

    def __init__(self, base_url: str = "", timeout: float = 10.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.3, max=4))
    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        response = await self._client.request(method, url, **kwargs)
        response.raise_for_status()
        return response

    async def aclose(self) -> None:
        await self._client.aclose()


class BaseToolPlugin(ABC):
    """Every concrete tool (GitHubTool, WeatherTool, MockTool, ...) extends this."""

    name: str
    description: str
    parameters_schema: dict

    def __init__(self, credentials: EnvCredentialProvider) -> None:
        self._credentials = credentials

    @abstractmethod
    async def execute(self, args: dict, ctx: ToolExecutionContext) -> ToolResultPayload: ...

    async def health_check(self) -> bool:
        return True

    def to_llm_schema(self) -> dict:
        """OpenAI/Groq-style function-calling schema derived from the plugin metadata."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }
