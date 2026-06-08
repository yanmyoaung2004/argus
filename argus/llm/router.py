from __future__ import annotations

from typing import Any

from argus.llm.circuit_breaker import ProviderCircuitBreaker
from argus.llm.profile import load_profile
from argus.llm.provider_config import load_settings
from argus.llm.providers import (
    AnthropicProvider,
    DeepSeekProvider,
    GoogleAIStudioProvider,
    GroqProvider,
    LiteLLMProvider,
    LLMProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
    OpenRouterProvider,
    TogetherAIProvider,
)
from argus.services.memory.llm_cache import LLMCache
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
    _cache: LLMCache | None = None

    # Task type → ordered list of providers to try
    ROUTING_TABLE: dict[str, list[LLMProviderType]] = {
        "planning": [
            LLMProviderType.OLLAMA,
            LLMProviderType.GROQ,
            LLMProviderType.OPENROUTER,
            LLMProviderType.OPENAI,
            LLMProviderType.ANTHROPIC,
            LLMProviderType.GOOGLE_AI_STUDIO,
            LLMProviderType.DEEPSEEK,
            LLMProviderType.NVIDIA,
            LLMProviderType.TOGETHER_AI,
            LLMProviderType.LITELLM,
        ],
        "scout": [
            LLMProviderType.GROQ,
            LLMProviderType.OLLAMA,
            LLMProviderType.OPENROUTER,
            LLMProviderType.OPENAI,
            LLMProviderType.GOOGLE_AI_STUDIO,
            LLMProviderType.DEEPSEEK,
            LLMProviderType.NVIDIA,
            LLMProviderType.TOGETHER_AI,
        ],
        "deep_dive": [
            LLMProviderType.OLLAMA,
            LLMProviderType.GROQ,
            LLMProviderType.OPENROUTER,
            LLMProviderType.OPENAI,
            LLMProviderType.ANTHROPIC,
            LLMProviderType.GOOGLE_AI_STUDIO,
            LLMProviderType.DEEPSEEK,
            LLMProviderType.NVIDIA,
            LLMProviderType.TOGETHER_AI,
            LLMProviderType.LITELLM,
        ],
        "verification": [
            LLMProviderType.GROQ,
            LLMProviderType.OLLAMA,
            LLMProviderType.OPENROUTER,
            LLMProviderType.OPENAI,
            LLMProviderType.ANTHROPIC,
            LLMProviderType.GOOGLE_AI_STUDIO,
            LLMProviderType.NVIDIA,
            LLMProviderType.DEEPSEEK,
        ],
        "synthesis": [
            LLMProviderType.OLLAMA,
            LLMProviderType.GROQ,
            LLMProviderType.OPENROUTER,
            LLMProviderType.OPENAI,
            LLMProviderType.GOOGLE_AI_STUDIO,
            LLMProviderType.DEEPSEEK,
            LLMProviderType.NVIDIA,
            LLMProviderType.TOGETHER_AI,
            LLMProviderType.LITELLM,
        ],
        "conflict_resolution": [
            LLMProviderType.GROQ,
            LLMProviderType.OPENROUTER,
            LLMProviderType.OPENAI,
            LLMProviderType.ANTHROPIC,
            LLMProviderType.GOOGLE_AI_STUDIO,
            LLMProviderType.DEEPSEEK,
            LLMProviderType.NVIDIA,
            LLMProviderType.CUSTOM_OPENAI,
            LLMProviderType.OPENAI_COMPATIBLE,
        ],
    }

    def _load_provider_settings(self) -> Any:
        if self._provider_settings is None:
            self._provider_settings = load_settings()
        return self._provider_settings

    REMOTE_PROVIDERS = {
        LLMProviderType.GROQ,
        LLMProviderType.OPENROUTER,
        LLMProviderType.OPENAI,
        LLMProviderType.ANTHROPIC,
        LLMProviderType.GOOGLE_AI_STUDIO,
        LLMProviderType.LITELLM,
        LLMProviderType.TOGETHER_AI,
        LLMProviderType.DEEPSEEK,
        LLMProviderType.NVIDIA,
        LLMProviderType.CUSTOM_OPENAI,
        LLMProviderType.OPENAI_COMPATIBLE,
    }

    def _is_provider_enabled(self, provider_type: LLMProviderType) -> bool:
        """Check if a provider is enabled in providers.json (default: enabled)."""
        settings_obj = self._load_provider_settings()
        entry = settings_obj.by_type(provider_type.value)
        if entry is not None:
            if not entry.enabled:
                return False
            # Require api_key for remote providers; local Ollama is always allowed
            if provider_type in self.REMOTE_PROVIDERS:
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
                case LLMProviderType.OPENAI:
                    self._providers[provider_type] = OpenAIProvider(entry=entry)
                case LLMProviderType.ANTHROPIC:
                    self._providers[provider_type] = AnthropicProvider(entry=entry)
                case LLMProviderType.GOOGLE_AI_STUDIO:
                    self._providers[provider_type] = GoogleAIStudioProvider(entry=entry)
                case LLMProviderType.LITELLM:
                    self._providers[provider_type] = LiteLLMProvider(entry=entry)
                case LLMProviderType.TOGETHER_AI:
                    self._providers[provider_type] = TogetherAIProvider(entry=entry)
                case LLMProviderType.DEEPSEEK:
                    self._providers[provider_type] = DeepSeekProvider(entry=entry)
                case LLMProviderType.NVIDIA:
                    self._providers[provider_type] = OpenAICompatibleProvider(entry=entry)
                case LLMProviderType.CUSTOM_OPENAI:
                    self._providers[provider_type] = OpenAICompatibleProvider(entry=entry)
                case LLMProviderType.OPENAI_COMPATIBLE:
                    self._providers[provider_type] = OpenAICompatibleProvider(entry=entry)
        return self._providers[provider_type]

    def _get_circuit_breaker(self, provider_type: LLMProviderType) -> ProviderCircuitBreaker:
        if provider_type not in self._breakers:
            self._breakers[provider_type] = ProviderCircuitBreaker(provider_type)
        return self._breakers[provider_type]

    def _get_assigned_providers(self, task_type: str) -> list[tuple[LLMProviderType, str]]:
        """Return list of (provider_type, model_override) from stage profile.

        If no profile assignment exists for this task_type, returns empty list
        so the caller falls back to the default routing table.
        """
        try:
            profile = load_profile()
            assignment = profile.by_task_type(task_type)
        except Exception:
            return []

        if assignment is None:
            return []

        try:
            pt = LLMProviderType(assignment.provider_type)
        except ValueError:
            return []

        if not self._is_provider_enabled(pt):
            return []

        return [(pt, assignment.model or "")]

    def complete(
        self,
        task_type: str,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> tuple[str, LLMProviderType, float]:
        """Route an LLM call through the fallback chain for the given task type.

        If a stage profile is set for this task_type, the assigned provider
        is tried first (with optional model override). Falls back to the
        default routing table if the assigned provider fails.

        Returns: (content, provider_used, cost)
        Raises: RuntimeError if all providers fail
        """
        # Check stage profile for overrides
        assigned = self._get_assigned_providers(task_type)
        model_override = assigned[0][1] if assigned else ""

        providers_to_try = self.ROUTING_TABLE.get(task_type, [LLMProviderType.OLLAMA])
        providers_to_try = [p for p in providers_to_try if self._is_provider_enabled(p)]

        # If a profile assigns a provider, put it first (deduplicate)
        if assigned:
            pt = assigned[0][0]
            providers_to_try = [pt] + [p for p in providers_to_try if p != pt]

        # LLM cache: skip the call if we have a cached response for this prompt
        model_hint = model_override or (providers_to_try[0].value if providers_to_try else "")
        if model_hint:
            if self._cache is None:
                self._cache = LLMCache()
            cached = self._cache.get(prompt, model_hint)
            if cached is not None:
                return cached, providers_to_try[0], 0.0

        for provider_type in providers_to_try:
            breaker = self._get_circuit_breaker(provider_type)
            if not breaker.allow_request:
                continue

            provider = self._get_provider(provider_type)
            call_kwargs = {**kwargs}
            # Pass model override from profile if this is the assigned provider
            is_assigned = assigned and provider_type == assigned[0][0]
            if is_assigned and model_override:
                call_kwargs["model_override"] = model_override
            try:
                response = provider.complete(prompt, system_prompt=system_prompt, **call_kwargs)
                breaker.record_success()
                if self._cache is not None:
                    try:
                        model_name = response.usage.model or model_hint
                        self._cache.set(prompt, model_name, response.content)
                    except Exception:
                        pass
                return response.content, provider_type, response.usage.cost
            except Exception:
                breaker.record_failure()
                continue

        raise RuntimeError(
            f"All LLM providers failed for task_type='{task_type}'. "
            f"Tried: {[p.value for p in providers_to_try]}"
        )
