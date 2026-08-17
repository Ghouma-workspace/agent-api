"""Prompt versioning via Langfuse prompt management API.

All hardcoded prompt strings are kept as fallback constants in their originating files.
This service wraps the Langfuse prompt fetch with full graceful degradation: if Langfuse
is unreachable, not configured, or a prompt is missing, the fallback is returned and the
system continues without interruption. Never raises. Never crashes the server.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()


class PromptService:
    """Fetches versioned prompt text from Langfuse; falls back to the supplied constant
    on any failure (Langfuse down, prompt not found, misconfiguration).

    Injected into every agent node that has a system prompt.
    """

    def __init__(self, langfuse_client, *, enable: bool = True) -> None:
        """
        Args:
            langfuse_client: A ``langfuse.Langfuse`` instance, or ``None`` when Langfuse
                is not configured (local dev without credentials).
            enable: When ``False`` (``langfuse_enable_prompt_management=False`` in
                Settings), always returns the fallback without attempting a network call.
                Makes local dev with no Langfuse identical to prod behaviour.
        """
        self._client = langfuse_client
        self._enable = enable
        self._prompt_objects: dict[str, object] = {}

    def get(self, name: str, fallback: str) -> str:
        """Return the compiled prompt text for ``name`` from Langfuse.

        Falls back to ``fallback`` on *any* failure — network errors, missing prompts,
        SDK exceptions, or when Langfuse is disabled. Logs a warning so the on-call
        engineer knows which prompt fell back and why.
        """
        if not self._enable or self._client is None:
            return fallback

        try:
            prompt = self._client.get_prompt(name, label="latest")
            self._prompt_objects[name] = prompt
            compiled = prompt.compile()
            return compiled.replace("{tool_names}", "{tool_names}")  # keep placeholder intact
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "prompt_service_fallback",
                prompt_name=name,
                reason=str(exc),
            )
            return fallback

    def get_prompt_object(self, name: str) -> object | None:
        """Return the raw Langfuse prompt object for linking to generations."""
        return self._prompt_objects.get(name)
