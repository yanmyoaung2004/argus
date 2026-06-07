from __future__ import annotations

import time
from typing import Any

import pytest

from argus.services.heartbeat import HeartbeatWriter, get_alive_agents


class FakeRedis:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._expiry: dict[str, float] = {}

    def setex(self, key: str, ttl: int, value: str) -> None:  # noqa: ARG002
        key = self._normalize(key)
        self._data[key] = value
        self._expiry[key] = time.time() + ttl

    def get(self, key: str | bytes) -> str | None:  # type: ignore[override]
        key = self._normalize(key)
        if key in self._expiry and time.time() > self._expiry[key]:
            del self._data[key]
            del self._expiry[key]
            return None
        return self._data.get(key)

    def ttl(self, key: str | bytes) -> int:  # type: ignore[override]
        key = self._normalize(key)
        if key not in self._expiry:
            return -2
        remaining = int(self._expiry[key] - time.time())
        return max(-2, remaining)

    def scan(  # type: ignore[override]
        self, cursor: int = 0, match: str = "*", count: int = 100
    ) -> tuple[int, list[bytes]]:
        keys = [k.encode() for k in self._data if self._match_pattern(match, k)]
        return (0, keys)

    def delete(self, key: str | bytes) -> int:  # type: ignore[override]
        key = self._normalize(key)
        return 1 if self._data.pop(key, None) is not None else 0

    def close(self) -> None:
        pass

    @staticmethod
    def _normalize(key: str | bytes) -> str:
        return key.decode("utf-8") if isinstance(key, bytes) else key

    @staticmethod
    def _match_pattern(pattern: str, key: str) -> bool:
        if pattern == "*":
            return True
        if pattern.endswith("*"):
            return key.startswith(pattern[:-1])
        return key == pattern


class TestHeartbeatWriter:
    def test_start_stop(self) -> None:
        writer = HeartbeatWriter("test-agent", redis_client=FakeRedis())  # type: ignore[arg-type]
        writer.start()
        assert writer._running
        writer.stop()
        assert not writer._running

    def test_writes_heartbeat(self) -> None:
        fake = FakeRedis()
        writer = HeartbeatWriter("test-agent", redis_client=fake)  # type: ignore[arg-type]
        r = writer._get_redis()
        assert r is not None
        key = "heartbeat:test-agent"
        r.setex(key, 30, "test_value")
        assert key in fake._data

    def test_no_redis_does_not_crash(self) -> None:
        writer = HeartbeatWriter("test-agent")
        writer._loop()  # should not raise


class TestGetAliveAgents:
    def test_returns_alive_agents(self) -> None:
        fake = FakeRedis()
        fake.setex("heartbeat:scout-1", 30, str(time.time()))
        result = get_alive_agents(fake)  # type: ignore[arg-type]
        assert "scout-1" in result
        assert result["scout-1"]["alive"] is True

    def test_empty_when_no_heartbeats(self) -> None:
        fake = FakeRedis()
        result = get_alive_agents(fake)  # type: ignore[arg-type]
        assert result == {}

    def test_expired_heartbeat_shows_dead(self) -> None:
        fake = FakeRedis()
        fake._data["heartbeat:dead-agent"] = str(time.time() - 60)
        result = get_alive_agents(fake)  # type: ignore[arg-type]
        assert "dead-agent" in result
