from __future__ import annotations

import pytest

from argus.llm.circuit_breaker import CircuitState, ProviderCircuitBreaker
from argus.shared.models import LLMProviderType


class FakeRedis:
    """In-memory Redis mock that actually stores values."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


class TestCircuitBreaker:
    def test_initial_state_is_closed(self, fake_redis: FakeRedis) -> None:
        cb = ProviderCircuitBreaker(LLMProviderType.OLLAMA, redis_client=fake_redis)
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request is True

    def test_record_failure_accumulates(self, fake_redis: FakeRedis) -> None:
        cb = ProviderCircuitBreaker(LLMProviderType.OLLAMA, redis_client=fake_redis)
        for _ in range(3):
            cb.record_failure()
            assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_trip_after_max_failures(self, fake_redis: FakeRedis) -> None:
        cb = ProviderCircuitBreaker(LLMProviderType.OLLAMA, redis_client=fake_redis)
        cb._fail_max = 3
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request is False

    def test_half_open_after_reset_timeout(self, fake_redis: FakeRedis) -> None:
        cb = ProviderCircuitBreaker(LLMProviderType.OLLAMA, redis_client=fake_redis)
        cb._fail_max = 3
        cb._reset_timeout = 60

        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request is False

        cb._reset_timeout = 0
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request is True

    def test_success_closes_circuit(self, fake_redis: FakeRedis) -> None:
        cb = ProviderCircuitBreaker(LLMProviderType.OLLAMA, redis_client=fake_redis)
        cb._fail_max = 2
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        cb._reset_timeout = 0
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request is True

    def test_state_persistence(self, fake_redis: FakeRedis) -> None:
        cb = ProviderCircuitBreaker(LLMProviderType.OLLAMA, redis_client=fake_redis)
        cb._fail_max = 2
        cb.record_failure()
        cb.record_failure()

        assert cb.state == CircuitState.OPEN

        cb2 = ProviderCircuitBreaker(LLMProviderType.OLLAMA, redis_client=fake_redis)
        cb2._fail_max = 2
        assert cb2.state == CircuitState.OPEN

    def test_allow_request_open(self, fake_redis: FakeRedis) -> None:
        cb = ProviderCircuitBreaker(LLMProviderType.OLLAMA, redis_client=fake_redis)
        cb._fail_max = 1
        cb.record_failure()
        assert cb.allow_request is False

    def test_allow_request_closed(self, fake_redis: FakeRedis) -> None:
        cb = ProviderCircuitBreaker(LLMProviderType.OLLAMA, redis_client=fake_redis)
        assert cb.allow_request is True


class TestCircuitBreakerNoRedis:
    def test_without_redis_falls_back_to_closed(self) -> None:
        cb = ProviderCircuitBreaker(LLMProviderType.OLLAMA, redis_client=None)
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request is True
