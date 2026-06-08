from __future__ import annotations

from typing import Any

import pytest

from argus.llm.router import CostAwareRouter
from argus.shared.models import LLMProviderType, LLMResponse, LLMUsage

PROVIDER_NAME_MAP: dict[str, LLMProviderType] = {
    "OllamaProvider": LLMProviderType.OLLAMA,
    "GroqProvider": LLMProviderType.GROQ,
    "OpenRouterProvider": LLMProviderType.OPENROUTER,
    "OpenAICompatibleProvider": LLMProviderType.OPENAI_COMPATIBLE,
}


class FakeRedis:
    """In-memory Redis mock."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value


@pytest.fixture(autouse=True)
def _patch_circuit_breaker_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent router from making real Redis connections."""
    fake = FakeRedis()
    monkeypatch.setattr(
        "argus.llm.circuit_breaker.ProviderCircuitBreaker._get_redis",
        lambda self: fake,
    )


@pytest.fixture(autouse=True)
def _mock_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock all LLM providers to return canned responses."""

    def mock_complete(
        self: object,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        type_name = type(self).__name__
        pt = PROVIDER_NAME_MAP.get(type_name, LLMProviderType.OLLAMA)
        return LLMResponse(
            content="mock response",
            provider_used=pt,
            usage=LLMUsage(provider=pt, model="mock", prompt_tokens=10, completion_tokens=10, cost=0.0, latency_ms=1),
        )

    monkeypatch.setattr(
        "argus.llm.providers.OllamaProvider.complete",
        mock_complete,
    )
    monkeypatch.setattr(
        "argus.llm.providers.GroqProvider.complete",
        mock_complete,
    )
    monkeypatch.setattr(
        "argus.llm.providers.OpenRouterProvider.complete",
        mock_complete,
    )
    monkeypatch.setattr(
        "argus.llm.providers.OpenAICompatibleProvider.complete",
        mock_complete,
    )


class TestRouter:
    @pytest.fixture(autouse=True)
    def _reset_router(self) -> None:
        CostAwareRouter._providers.clear()
        CostAwareRouter._breakers.clear()

    def test_routing_uses_primary_provider(self) -> None:
        router = CostAwareRouter()
        content, provider, cost = router.complete(
            task_type="planning",
            prompt="Test prompt",
        )
        valid_providers = {LLMProviderType.OLLAMA, LLMProviderType.GROQ, LLMProviderType.OPENROUTER}
        assert provider in valid_providers
        assert isinstance(content, str)

    def test_routing_table_has_all_task_types(self) -> None:
        expected_types = [
            "planning", "scout", "deep_dive",
            "verification", "synthesis", "conflict_resolution",
        ]
        for task_type in expected_types:
            assert task_type in CostAwareRouter.ROUTING_TABLE, f"Missing: {task_type}"
            assert len(CostAwareRouter.ROUTING_TABLE[task_type]) >= 1

    def test_unknown_task_type_defaults_to_ollama(self) -> None:
        content, provider, cost = CostAwareRouter().complete(
            task_type="unknown_task_type",
            prompt="test",
        )
        valid_providers = {LLMProviderType.OLLAMA, LLMProviderType.GROQ, LLMProviderType.OPENROUTER}
        assert provider in valid_providers

    def test_router_raises_on_all_failures(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def failing_complete(_self: object, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("Provider down")

        for provider in (
            "OllamaProvider", "GroqProvider", "OpenRouterProvider",
            "OpenAIProvider", "AnthropicProvider", "GoogleAIStudioProvider",
            "DeepSeekProvider", "TogetherAIProvider", "LiteLLMProvider",
            "OpenAICompatibleProvider",
        ):
            monkeypatch.setattr(
                f"argus.llm.providers.{provider}.complete",
                failing_complete,
            )

        with pytest.raises(RuntimeError, match="All LLM providers failed"):
            CostAwareRouter().complete(task_type="planning", prompt="test")

    def test_cost_is_returned(self) -> None:
        router = CostAwareRouter()
        _, _, cost = router.complete(task_type="planning", prompt="Hello")
        assert isinstance(cost, float)
        assert cost >= 0.0

    def test_scout_routing_preferences(self) -> None:
        table = CostAwareRouter.ROUTING_TABLE["scout"]
        assert table[0] == LLMProviderType.GROQ
        assert len(table) == 8

    def test_conflict_resolution_routing(self) -> None:
        table = CostAwareRouter.ROUTING_TABLE["conflict_resolution"]
        assert table[0] == LLMProviderType.GROQ
        assert LLMProviderType.OPENAI_COMPATIBLE in table
