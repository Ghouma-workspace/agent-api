from __future__ import annotations

import time
from collections.abc import AsyncIterator

from groq import AsyncGroq
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings
from app.domain.entities.chat import ChatMessage, LLMChunk, LLMResponse, ToolCall
from app.domain.exceptions.base import LLMProviderError
from app.infrastructure.observability.metrics import (
    LLM_COMPLETION_TOKENS_TOTAL,
    LLM_COST_USD_TOTAL,
    LLM_PROMPT_TOKENS_TOTAL,
    LLM_REQUEST_DURATION_SECONDS,
)

_PRICING_PER_1K_TOKENS = {
    "llama-3.3-70b-versatile": {"prompt": 0.00059, "completion": 0.00079},
    "llama-3.1-8b-instant":    {"prompt": 0.00005, "completion": 0.00008},
}


class GroqProvider:
    def __init__(self, settings: Settings) -> None:
        self._client = AsyncGroq(api_key=settings.groq_api_key.get_secret_value())
        self._model = settings.groq_model
        self._timeout = settings.llm_request_timeout_seconds

    def _to_groq_messages(self, messages: list[ChatMessage]) -> list[dict]:
        return [{"role": m.role.value, "content": m.content} for m in messages]

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        rates = _PRICING_PER_1K_TOKENS.get(self._model, {"prompt": 0.0, "completion": 0.0})
        return (
            (prompt_tokens / 1000) * rates["prompt"]
            + (completion_tokens / 1000) * rates["completion"]
        )

    def _record_metrics(
        self, prompt_tokens: int, completion_tokens: int, duration: float
    ) -> None:
        LLM_REQUEST_DURATION_SECONDS.labels(
            provider="groq", model=self._model
        ).observe(duration)
        LLM_PROMPT_TOKENS_TOTAL.labels(
            provider="groq", model=self._model
        ).inc(prompt_tokens)
        LLM_COMPLETION_TOKENS_TOTAL.labels(
            provider="groq", model=self._model
        ).inc(completion_tokens)
        cost = self._estimate_cost(prompt_tokens, completion_tokens)
        if cost > 0:
            LLM_COST_USD_TOTAL.labels(model=self._model).inc(cost)

    @retry(
        retry=retry_if_exception_type(LLMProviderError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=8),
        reraise=True,
    )
    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        response_format: dict | None = None,
        **kwargs: object,
    ) -> LLMResponse:
        start = time.perf_counter()
        try:
            create_kwargs: dict = dict(
                model=self._model,
                messages=self._to_groq_messages(messages),
                tools=tools or None,
                timeout=self._timeout,
            )
            if response_format is not None:
                create_kwargs["response_format"] = response_format
            response = await self._client.chat.completions.create(**create_kwargs)
        except Exception as exc:
            raise LLMProviderError("groq", str(exc), retryable=True) from exc

        duration = time.perf_counter() - start
        choice = response.choices[0]
        tool_calls = [
            ToolCall(
                tool_name=tc.function.name,
                arguments=_safe_json(tc.function.arguments),
            )
            for tc in (choice.message.tool_calls or [])
        ]
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0

        self._record_metrics(prompt_tokens, completion_tokens, duration)

        return LLMResponse(
            content=choice.message.content or "",
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=self._model,
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        **kwargs: object,
    ) -> AsyncIterator[LLMChunk]:
        start = time.perf_counter()
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
            if finished:
                LLM_REQUEST_DURATION_SECONDS.labels(
                    provider="groq", model=self._model
                ).observe(time.perf_counter() - start)
            yield LLMChunk(delta=delta.content or "", is_final=finished)


def _safe_json(raw: str) -> dict:
    import json
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}