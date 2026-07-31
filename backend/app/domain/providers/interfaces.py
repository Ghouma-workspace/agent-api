"""Ports for external capabilities the domain depends on but never implements."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from app.domain.entities.chat import ChatMessage, LLMChunk, LLMResponse


@runtime_checkable
class LLMProvider(Protocol):
    """Every LLM vendor integration (Groq, OpenAI, Anthropic, ...) implements this."""

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        **kwargs: object,
    ) -> LLMResponse: ...

    def stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        **kwargs: object,
    ) -> AsyncIterator[LLMChunk]: ...


@runtime_checkable
class CredentialProvider(Protocol):
    """Tools resolve secrets through this instead of reading os.environ directly."""

    def get_secret(self, key: str) -> str: ...


@runtime_checkable
class ToolPlugin(Protocol):
    """Common interface every tool (GitHub, Jira, Notion, ...) must implement."""

    name: str
    description: str
    parameters_schema: dict

    async def execute(self, args: dict, ctx: ToolExecutionContext) -> ToolResultPayload: ...
    async def health_check(self) -> bool: ...


class ToolExecutionContext(Protocol):
    user_id: str
    conversation_id: str
    trace_id: str


class ToolResultPayload(Protocol):
    success: bool
    output: dict | None
    error: str | None


@runtime_checkable
class ToolRegistry(Protocol):
    """Looks up ToolPlugin instances by name and exposes their schemas for LLM
    function-calling. Infrastructure/tools/registry.py provides the concrete impl."""

    def get(self, name: str) -> ToolPlugin | None: ...
    def list_schemas(self) -> list[dict]: ...
