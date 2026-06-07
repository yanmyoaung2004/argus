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
        model = kwargs.pop("model_override", "") or self._get_model_name()

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


class OpenAIProvider(LLMProvider):
    """OpenAI API — paid, high-quality models."""

    def __init__(self, entry: ProviderEntry | None = None) -> None:
        super().__init__(LLMProviderType.OPENAI, entry=entry)

    def _create_client(self) -> OpenAI:
        api_key = self._entry_or_settings("api_key") or settings.openai_api_key
        base_url = self._entry_or_settings("base_url") or settings.openai_base_url
        return OpenAI(base_url=base_url, api_key=api_key, max_retries=0)

    def _get_model_name(self) -> str:
        return self._entry_or_settings("selected_model") or settings.openai_model

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * 2.50 + completion_tokens * 10.00) / 1_000_000


class AnthropicProvider(LLMProvider):
    """Anthropic Claude — uses httpx (no SDK dependency)."""

    def __init__(self, entry: ProviderEntry | None = None) -> None:
        super().__init__(LLMProviderType.ANTHROPIC, entry=entry)

    def _create_client(self) -> dict:  # noqa: PLR6301
        return {}

    def _get_model_name(self) -> str:
        return self._entry_or_settings("selected_model") or settings.anthropic_model

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * 3.00 + completion_tokens * 15.00) / 1_000_000

    def complete(
        self, prompt: str, system_prompt: str | None = None, **_kwargs: Any
    ) -> LLMResponse:
        import httpx

        start = time.monotonic()
        api_key = self._entry_or_settings("api_key") or settings.anthropic_api_key
        base_url = self._entry_or_settings("base_url") or settings.anthropic_base_url
        model = self._get_model_name()

        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": 1024,
        }
        if system_prompt:
            body["system"] = system_prompt

        resp = httpx.post(
            base_url.rstrip("/") + "/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
            timeout=settings.anthropic_timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        elapsed_ms = int((time.monotonic() - start) * 1000)

        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")

        usage_data = data.get("usage", {})
        usage = LLMUsage(
            provider=self.provider_type,
            model=model,
            prompt_tokens=usage_data.get("input_tokens", 0),
            completion_tokens=usage_data.get("output_tokens", 0),
            cost=self._estimate_cost(
                usage_data.get("input_tokens", 0),
                usage_data.get("output_tokens", 0),
            ),
            latency_ms=elapsed_ms,
        )

        return LLMResponse(
            content=content,
            provider_used=self.provider_type,
            usage=usage,
        )


class GoogleAIStudioProvider(LLMProvider):
    """Google AI Studio / Gemini API — uses httpx (no SDK dependency)."""

    def __init__(self, entry: ProviderEntry | None = None) -> None:
        super().__init__(LLMProviderType.GOOGLE_AI_STUDIO, entry=entry)

    def _create_client(self) -> dict:  # noqa: PLR6301
        return {}

    def _get_model_name(self) -> str:
        return self._entry_or_settings("selected_model") or settings.google_ai_studio_model

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * 0.10 + completion_tokens * 0.40) / 1_000_000

    def complete(
        self, prompt: str, system_prompt: str | None = None, **_kwargs: Any
    ) -> LLMResponse:
        import httpx

        start = time.monotonic()
        api_key = self._entry_or_settings("api_key") or settings.google_ai_studio_api_key
        base_url = self._entry_or_settings("base_url") or settings.google_ai_studio_base_url
        model = self._get_model_name()

        contents: list[dict[str, Any]] = [{"parts": [{"text": prompt}]}]
        body: dict[str, Any] = {"contents": contents}
        if system_prompt:
            body["system_instruction"] = {"parts": [{"text": system_prompt}]}

        resp = httpx.post(
            f"{base_url.rstrip('/')}/models/{model}:generateContent",
            params={"key": api_key},
            json=body,
            timeout=settings.google_ai_studio_timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        elapsed_ms = int((time.monotonic() - start) * 1000)

        content = ""
        candidates = data.get("candidates", [])
        if candidates:
            candidate = candidates[0]
            for part in candidate.get("content", {}).get("parts", []):
                if "text" in part:
                    content += part["text"]

        usage_data = data.get("usageMetadata", {})
        usage = LLMUsage(
            provider=self.provider_type,
            model=model,
            prompt_tokens=usage_data.get("promptTokenCount", 0),
            completion_tokens=usage_data.get("candidatesTokenCount", 0),
            cost=self._estimate_cost(
                usage_data.get("promptTokenCount", 0),
                usage_data.get("candidatesTokenCount", 0),
            ),
            latency_ms=elapsed_ms,
        )

        return LLMResponse(
            content=content,
            provider_used=self.provider_type,
            usage=usage,
        )


class LiteLLMProvider(LLMProvider):
    """LiteLLM proxy — OpenAI-compatible, user-hosted."""

    def __init__(self, entry: ProviderEntry | None = None) -> None:
        super().__init__(LLMProviderType.LITELLM, entry=entry)

    def _create_client(self) -> OpenAI:
        api_key = self._entry_or_settings("api_key") or settings.litellm_api_key
        base_url = self._entry_or_settings("base_url") or settings.litellm_base_url
        return OpenAI(base_url=base_url, api_key=api_key, max_retries=0)

    def _get_model_name(self) -> str:
        return self._entry_or_settings("selected_model") or settings.litellm_model

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:  # noqa: ARG002
        return 0.0


class TogetherAIProvider(LLMProvider):
    """Together AI — OpenAI-compatible, paid."""

    def __init__(self, entry: ProviderEntry | None = None) -> None:
        super().__init__(LLMProviderType.TOGETHER_AI, entry=entry)

    def _create_client(self) -> OpenAI:
        api_key = self._entry_or_settings("api_key") or settings.together_ai_api_key
        base_url = self._entry_or_settings("base_url") or settings.together_ai_base_url
        return OpenAI(base_url=base_url, api_key=api_key, max_retries=0)

    def _get_model_name(self) -> str:
        return self._entry_or_settings("selected_model") or settings.together_ai_model

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * 0.88 + completion_tokens * 0.88) / 1_000_000


class DeepSeekProvider(LLMProvider):
    """DeepSeek — OpenAI-compatible, paid."""

    def __init__(self, entry: ProviderEntry | None = None) -> None:
        super().__init__(LLMProviderType.DEEPSEEK, entry=entry)

    def _create_client(self) -> OpenAI:
        api_key = self._entry_or_settings("api_key") or settings.deepseek_api_key
        base_url = self._entry_or_settings("base_url") or settings.deepseek_base_url
        return OpenAI(base_url=base_url, api_key=api_key, max_retries=0)

    def _get_model_name(self) -> str:
        return self._entry_or_settings("selected_model") or settings.deepseek_model

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * 0.27 + completion_tokens * 1.10) / 1_000_000


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
