from __future__ import annotations

from typing import Any

from argus.llm.circuit_breaker import ProviderCircuitBreaker
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
    """

    _providers: dict[LLMProviderType, LLMProvider] = {}
    _breakers: dict[LLMProviderType, ProviderCircuitBreaker] = {}

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

    def _get_provider(self, provider_type: LLMProviderType) -> LLMProvider:
        if provider_type not in self._providers:
            match provider_type:
                case LLMProviderType.OLLAMA:
                    self._providers[provider_type] = OllamaProvider()
                case LLMProviderType.GROQ:
                    self._providers[provider_type] = GroqProvider()
                case LLMProviderType.OPENROUTER:
                    self._providers[provider_type] = OpenRouterProvider()
                case LLMProviderType.OPENAI_COMPATIBLE:
                    self._providers[provider_type] = OpenAICompatibleProvider()
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
