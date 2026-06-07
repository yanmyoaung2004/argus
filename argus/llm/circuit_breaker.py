from __future__ import annotations

import time
from enum import StrEnum
from typing import Any

import redis as redis_lib

from argus.shared.config import settings
from argus.shared.models import LLMProviderType


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ProviderCircuitBreaker:
    """Redis-backed circuit breaker per LLM provider.

    State stored in Redis under key: circuit:{provider.value}
    Value: JSON with state, failure_count, last_failure_time, opened_at
    """

    REDIS_KEY_PREFIX = "circuit:"

    def __init__(
        self,
        provider: LLMProviderType,
        redis_client: redis_lib.Redis | None = None,
    ) -> None:
        self.provider = provider
        self._redis = redis_client
        self._fail_max = settings.circuit_breaker_fail_max
        self._reset_timeout = settings.circuit_breaker_reset_timeout_seconds

    def _get_redis(self) -> redis_lib.Redis | None:
        if self._redis is None:
            try:
                self._redis = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
            except Exception:
                return None
        return self._redis

    def _redis_key(self) -> str:
        return f"{self.REDIS_KEY_PREFIX}{self.provider.value}"

    def _get_state(self) -> dict[str, Any]:
        r = self._get_redis()
        if r is None:
            return {"state": CircuitState.CLOSED.value, "failure_count": 0}
        try:
            data = r.get(self._redis_key())
            if data:
                import json

                state: dict[str, object] = json.loads(data)
                return state
        except Exception:
            pass
        return {"state": CircuitState.CLOSED.value, "failure_count": 0}

    def _set_state(self, state: dict[str, Any]) -> None:
        r = self._get_redis()
        if r is None:
            return
        import json

        r.set(self._redis_key(), json.dumps(state))

    @property
    def state(self) -> CircuitState:
        data = self._get_state()
        state = CircuitState(data.get("state", CircuitState.CLOSED.value))

        if state == CircuitState.OPEN:
            opened_at = data.get("opened_at", 0)
            if time.time() - opened_at >= self._reset_timeout:
                state = CircuitState.HALF_OPEN
                data["state"] = state.value
                self._set_state(data)

        return state

    def record_success(self) -> None:
        self._set_state({"state": CircuitState.CLOSED.value, "failure_count": 0})

    def record_failure(self) -> None:
        data = self._get_state()
        data["failure_count"] = data.get("failure_count", 0) + 1
        data["last_failure_time"] = time.time()

        if data["failure_count"] >= self._fail_max:
            data["state"] = CircuitState.OPEN.value
            data["opened_at"] = time.time()

        self._set_state(data)

    @property
    def allow_request(self) -> bool:
        return self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)
