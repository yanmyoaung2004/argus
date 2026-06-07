from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from argus.shared.config import settings
from argus.shared.models import LLMProviderType, LLMResponse, LLMUsage


class LLMProvider(ABC):
    """Abstract base for all LLM providers."""

    def __init__(self, provider_type: LLMProviderType) -> None:
        self.provider_type = provider_type
        self._client: Any = None

    @abstractmethod
    def _create_client(self) -> Any:
        ...

    @abstractmethod
    def _get_model_name(self) -> str:
        ...

    @abstractmethod
    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        ...

    @retry(
        stop=stop_after_attempt(settings.llm_retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.llm_retry_min_wait_seconds,
            max=settings.llm_retry_max_wait_seconds,
        ),
    )
    def complete(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> LLMResponse:
        start = time.monotonic()
        client = self._get_client()
        model = self._get_model_name()

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(model=model, messages=messages, **kwargs)

        elapsed_ms = int((time.monotonic() - start) * 1000)

        usage = LLMUsage(
            provider=self.provider_type,
            model=model,
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
            cost=self._estimate_cost(
                response.usage.prompt_tokens if response.usage else 0,
                response.usage.completion_tokens if response.usage else 0,
            ),
            latency_ms=elapsed_ms,
        )

        return LLMResponse(
            content=response.choices[0].message.content or "",
            provider_used=self.provider_type,
            usage=usage,
        )

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._create_client()
        return self._client


class OllamaProvider(LLMProvider):
    """Local Ollama — free, runs on own hardware."""

    def __init__(self) -> None:
        super().__init__(LLMProviderType.OLLAMA)

    def _create_client(self) -> OpenAI:
        return OpenAI(base_url=settings.ollama_base_url + "/v1", api_key="ollama", max_retries=0)

    def _get_model_name(self) -> str:
        return settings.ollama_model

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:  # noqa: ARG002
        return 0.0


class GroqProvider(LLMProvider):
    """Groq free tier — fast, rate-limited."""

    def __init__(self) -> None:
        super().__init__(LLMProviderType.GROQ)

    def _create_client(self) -> OpenAI:
        return OpenAI(base_url=settings.groq_base_url, api_key=settings.groq_api_key, max_retries=0)

    def _get_model_name(self) -> str:
        return settings.groq_model

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:  # noqa: ARG002
        return 0.0


class OpenRouterProvider(LLMProvider):
    """OpenRouter — cheap paid models as last fallback."""

    def __init__(self) -> None:
        super().__init__(LLMProviderType.OPENROUTER)

    def _create_client(self) -> OpenAI:
        return OpenAI(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
            max_retries=0,
            default_headers={"HTTP-Referer": "https://argus.local"},
        )

    def _get_model_name(self) -> str:
        return settings.openrouter_model

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        # Mixtral 8x7B: ~$0.27/M input, ~$0.27/M output
        return (prompt_tokens * 0.27 + completion_tokens * 0.27) / 1_000_000


class OpenAICompatibleProvider(LLMProvider):
    """Generic OpenAI-compatible endpoint."""

    def __init__(self) -> None:
        super().__init__(LLMProviderType.OPENAI_COMPATIBLE)

    def _create_client(self) -> OpenAI:
        return OpenAI(
            base_url=settings.openai_compatible_base_url,
            api_key=settings.openai_compatible_api_key,
            max_retries=0,
        )

    def _get_model_name(self) -> str:
        return settings.openai_compatible_model

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        # GPT-4o-mini: ~$0.15/M input, ~$0.60/M output
        return (prompt_tokens * 0.15 + completion_tokens * 0.60) / 1_000_000
