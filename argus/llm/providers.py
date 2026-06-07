from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from argus.llm.provider_config import ProviderEntry
from argus.shared.config import settings
from argus.shared.models import LLMProviderType, LLMResponse, LLMUsage


class LLMProvider(ABC):
    """Abstract base for all LLM providers."""

    def __init__(self, provider_type: LLMProviderType, entry: ProviderEntry | None = None) -> None:
        self.provider_type = provider_type
        self._entry = entry
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

    # Maps ProviderEntry attribute names to settings suffix (after provider prefix)
    _ATTR_TO_SETTINGS_SUFFIX: dict[str, str] = {
        "api_key": "api_key",
        "base_url": "base_url",
        "selected_model": "model",
    }

    def _entry_or_settings(self, attr: str) -> str:
        """Return entry value if set, otherwise fall back to settings."""
        entry_val = getattr(self._entry, attr, "") if self._entry else ""
        if entry_val:
            return entry_val
        settings_suffix = self._ATTR_TO_SETTINGS_SUFFIX.get(attr, attr)
        settings_key = f"{self.provider_type.value}_{settings_suffix}"
        return getattr(settings, settings_key, "")

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

    def __init__(self, entry: ProviderEntry | None = None) -> None:
        super().__init__(LLMProviderType.OLLAMA, entry=entry)

    def complete(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> LLMResponse:
        """Override: fast-fail if Ollama is not running, skip retry for connection errors."""
        self._check_available()
        return super().complete(prompt, system_prompt=system_prompt, **kwargs)

    def _check_available(self) -> None:
        """Lightweight check — raises immediately if Ollama is not reachable."""
        import httpx
        base_url = self._entry_or_settings("base_url") or settings.ollama_base_url
        try:
            resp = httpx.get(f"{base_url}/api/tags", timeout=2.0)
            resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Ollama is not available at {base_url}. "
                "Make sure Ollama is running or configure a different provider."
            ) from exc

    def _create_client(self) -> OpenAI:
        base_url = self._entry_or_settings("base_url") or settings.ollama_base_url
        return OpenAI(base_url=base_url.rstrip("/") + "/v1", api_key="ollama", max_retries=0)

    def _get_model_name(self) -> str:
        return self._entry_or_settings("selected_model") or settings.ollama_model

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:  # noqa: ARG002
        return 0.0


class GroqProvider(LLMProvider):
    """Groq free tier — fast, rate-limited."""

    def __init__(self, entry: ProviderEntry | None = None) -> None:
        super().__init__(LLMProviderType.GROQ, entry=entry)

    def _create_client(self) -> OpenAI:
        api_key = self._entry_or_settings("api_key") or settings.groq_api_key
        base_url = self._entry_or_settings("base_url") or settings.groq_base_url
        return OpenAI(base_url=base_url, api_key=api_key, max_retries=0)

    def _get_model_name(self) -> str:
        return self._entry_or_settings("selected_model") or settings.groq_model

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:  # noqa: ARG002
        return 0.0


class OpenRouterProvider(LLMProvider):
    """OpenRouter — cheap paid models as last fallback."""

    def __init__(self, entry: ProviderEntry | None = None) -> None:
        super().__init__(LLMProviderType.OPENROUTER, entry=entry)

    def _create_client(self) -> OpenAI:
        api_key = self._entry_or_settings("api_key") or settings.openrouter_api_key
        base_url = self._entry_or_settings("base_url") or settings.openrouter_base_url
        return OpenAI(
            base_url=base_url,
            api_key=api_key,
            max_retries=0,
            default_headers={"HTTP-Referer": "https://argus.local"},
        )

    def _get_model_name(self) -> str:
        return self._entry_or_settings("selected_model") or settings.openrouter_model

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * 0.27 + completion_tokens * 0.27) / 1_000_000


class OpenAICompatibleProvider(LLMProvider):
    """Generic OpenAI-compatible endpoint."""

    def __init__(self, entry: ProviderEntry | None = None) -> None:
        super().__init__(LLMProviderType.OPENAI_COMPATIBLE, entry=entry)

    def _create_client(self) -> OpenAI:
        api_key = self._entry_or_settings("api_key") or settings.openai_compatible_api_key
        base_url = self._entry_or_settings("base_url") or settings.openai_compatible_base_url
        return OpenAI(
            base_url=base_url,
            api_key=api_key,
            max_retries=0,
        )

    def _get_model_name(self) -> str:
        return self._entry_or_settings("selected_model") or settings.openai_compatible_model

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * 0.15 + completion_tokens * 0.60) / 1_000_000
