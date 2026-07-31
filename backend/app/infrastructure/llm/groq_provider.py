from __future__ import annotations

from collections.abc import AsyncIterator

from groq import AsyncGroq
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings
from app.domain.entities.chat import ChatMessage, LLMChunk, LLMResponse, ToolCall
from app.domain.exceptions.base import LLMProviderError

# Groq's published (approximate) per-token pricing for the default model, in USD/token.
# In production this table would live in config or be fetched from a pricing service.
_PRICING_PER_1K_TOKENS = {"llama-3.3-70b-versatile": {"prompt": 0.00059, "completion": 0.00079}}


class GroqProvider:
    """Implements domain.providers.interfaces.LLMProvider against GroqCloud.
    Swapping to OpenAI/Anthropic later means writing OpenAIProvider/AnthropicProvider
    with this same shape and changing one line in the DI container."""

    def __init__(self, settings: Settings) -> None:
        self._client = AsyncGroq(api_key=settings.groq_api_key.get_secret_value())
        self._model = settings.groq_model
        self._timeout = settings.llm_request_timeout_seconds

    def _to_groq_messages(self, messages: list[ChatMessage]) -> list[dict]:
        return [{"role": m.role.value, "content": m.content} for m in messages]

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        rates = _PRICING_PER_1K_TOKENS.get(self._model, {"prompt": 0.0, "completion": 0.0})
        return (prompt_tokens / 1000) * rates["prompt"] + (completion_tokens / 1000) * rates[
            "completion"
        ]

    @retry(
        retry=retry_if_exception_type(LLMProviderError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=8),
        reraise=True,
    )
    async def complete(
        self, messages: list[ChatMessage], tools: list[dict] | None = None, **kwargs: object
    ) -> LLMResponse:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=self._to_groq_messages(messages),
                tools=tools or None,
                timeout=self._timeout,
            )
        except Exception as exc:  # groq SDK raises various HTTP/transport errors
            raise LLMProviderError("groq", str(exc), retryable=True) from exc

        choice = response.choices[0]
        tool_calls = [
            ToolCall(tool_name=tc.function.name, arguments=_safe_json(tc.function.arguments))
            for tc in (choice.message.tool_calls or [])
        ]
        usage = response.usage
        return LLMResponse(
            content=choice.message.content or "",
            tool_calls=tool_calls,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            model=self._model,
        )

    async def stream(
        self, messages: list[ChatMessage], tools: list[dict] | None = None, **kwargs: object
    ) -> AsyncIterator[LLMChunk]:
        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=self._to_groq_messages(messages),
                tools=tools or None,
                stream=True,
                timeout=self._timeout,
            )
        except Exception as exc:
            raise LLMProviderError("groq", str(exc), retryable=True) from exc

        async for chunk in stream:
            delta = chunk.choices[0].delta
            finished = chunk.choices[0].finish_reason is not None
            yield LLMChunk(delta=delta.content or "", is_final=finished)


def _safe_json(raw: str) -> dict:
    import json

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
