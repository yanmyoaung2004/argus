from __future__ import annotations

from typing import Any

from argus.llm.circuit_breaker import ProviderCircuitBreaker
from argus.llm.provider_config import load_settings
from argus.llm.providers import (
    GroqProvider,
    LLMProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    OpenRouterProvider,
)
from argus.shared.models import LLMProviderType


class CostAwareRouter:
    """Routes LLM calls to the cheapest available provider based on task type.

    Fallback chain (defined per task type):
      1. Try primary provider (cheapest)
      2. If circuit is open or call fails, try fallback 1
      3. If fallback 1 fails, try fallback 2
      4. If all fail, raise RuntimeError

    Provider configuration is loaded from ~/.argus/providers.json.
    If the file does not exist, defaults from settings.py are used.
    """

    _providers: dict[LLMProviderType, LLMProvider] = {}
    _breakers: dict[LLMProviderType, ProviderCircuitBreaker] = {}
    _provider_settings: Any = None

    # Task type → ordered list of providers to try
    ROUTING_TABLE: dict[str, list[LLMProviderType]] = {
        "planning": [LLMProviderType.OLLAMA, LLMProviderType.GROQ, LLMProviderType.OPENROUTER],
        "scout": [LLMProviderType.GROQ, LLMProviderType.OLLAMA, LLMProviderType.OPENROUTER],
        "deep_dive": [LLMProviderType.OLLAMA, LLMProviderType.GROQ, LLMProviderType.OPENROUTER],
        "verification": [LLMProviderType.GROQ, LLMProviderType.OLLAMA, LLMProviderType.OPENROUTER],
        "synthesis": [LLMProviderType.OLLAMA, LLMProviderType.GROQ, LLMProviderType.OPENROUTER],
        "conflict_resolution": [
            LLMProviderType.GROQ,
            LLMProviderType.OPENROUTER,
            LLMProviderType.OPENAI_COMPATIBLE,
        ],
    }

    def _load_provider_settings(self) -> Any:
        if self._provider_settings is None:
            self._provider_settings = load_settings()
        return self._provider_settings

    def _is_provider_enabled(self, provider_type: LLMProviderType) -> bool:
        """Check if a provider is enabled in providers.json (default: enabled)."""
        settings_obj = self._load_provider_settings()
        entry = settings_obj.by_type(provider_type.value)
        if entry is not None:
            if not entry.enabled:
                return False
            # Require api_key for remote providers; local Ollama is always allowed
            if provider_type in (LLMProviderType.GROQ, LLMProviderType.OPENROUTER, LLMProviderType.OPENAI_COMPATIBLE):
                return bool(entry.api_key)
        return True

    def _get_entry(self, provider_type: LLMProviderType) -> Any | None:
        return self._load_provider_settings().by_type(provider_type.value)

    def _get_provider(self, provider_type: LLMProviderType) -> LLMProvider:
        if provider_type not in self._providers:
            entry = self._get_entry(provider_type)
            match provider_type:
                case LLMProviderType.OLLAMA:
                    self._providers[provider_type] = OllamaProvider(entry=entry)
                case LLMProviderType.GROQ:
                    self._providers[provider_type] = GroqProvider(entry=entry)
                case LLMProviderType.OPENROUTER:
                    self._providers[provider_type] = OpenRouterProvider(entry=entry)
                case LLMProviderType.OPENAI_COMPATIBLE:
                    self._providers[provider_type] = OpenAICompatibleProvider(entry=entry)
        return self._providers[provider_type]

    def _get_circuit_breaker(self, provider_type: LLMProviderType) -> ProviderCircuitBreaker:
        if provider_type not in self._breakers:
            self._breakers[provider_type] = ProviderCircuitBreaker(provider_type)
        return self._breakers[provider_type]

    def complete(
        self,
        task_type: str,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> tuple[str, LLMProviderType, float]:
        """Route an LLM call through the fallback chain for the given task type.

        Returns: (content, provider_used, cost)
        Raises: RuntimeError if all providers fail
        """
        providers_to_try = self.ROUTING_TABLE.get(task_type, [LLMProviderType.OLLAMA])

        # Filter to only enabled providers from providers.json
        providers_to_try = [p for p in providers_to_try if self._is_provider_enabled(p)]

        for provider_type in providers_to_try:
            breaker = self._get_circuit_breaker(provider_type)
            if not breaker.allow_request:
                continue

            provider = self._get_provider(provider_type)
            try:
                response = provider.complete(prompt, system_prompt=system_prompt, **kwargs)
                breaker.record_success()
                return response.content, provider_type, response.usage.cost
            except Exception:
                breaker.record_failure()
                continue

        raise RuntimeError(
            f"All LLM providers failed for task_type='{task_type}'. "
            f"Tried: {[p.value for p in providers_to_try]}"
        )
