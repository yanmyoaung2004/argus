from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from argus.services.orchestrator.agent_runner import AgentRunner
from argus.shared.models import AgentType


class FakeRedis:
    def __init__(self) -> None:
        self._groups: dict[str, dict[str, Any]] = {}
        self._pending: dict[str, list[Any]] = {}
        self._data: dict[str, Any] = {}

    def xgroup_create(self, stream: str, group: str, id: str = "$", mkstream: bool = True) -> None:  # noqa: A002, ARG002
        key = f"{stream}:{group}"
        if key not in self._groups:
            self._groups[key] = {"stream": stream, "group": group, "pending": []}

    def xreadgroup(
        self,
        group: str,
        consumer: str,
        streams: dict[str, str],
        count: int | None = None,  # noqa: ARG002
        block: int | None = None,  # noqa: ARG002
    ) -> list[tuple[str, list[Any]]]:
        stream_name = next(iter(streams))
        pending = self._pending.get(f"{stream_name}:{group}:{consumer}", [])
        self._pending[f"{stream_name}:{group}:{consumer}"] = []
        return [(stream_name, pending)]

    def xack(self, stream: str, group: str, msg_id: bytes) -> None:
        pass

    def xadd(self, stream: str, data: dict[str, Any], maxlen: int | None = None) -> None:  # noqa: ARG002
        if stream not in self._data:
            self._data[stream] = []
        self._data[stream].append(data)

    def queue_message(self, stream: str, group: str, consumer: str, msg_id: str, data: dict[bytes, bytes]) -> None:
        key = f"{stream}:{group}:{consumer}"
        if key not in self._pending:
            self._pending[key] = []
        self._pending[key].append((msg_id, data))


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.mark.asyncio
async def test_agent_runner_consumes_messages(fake_redis: FakeRedis) -> None:
    runner = AgentRunner(AgentType.SCOUT, redis_client=fake_redis)  # type: ignore[arg-type]

    with patch.object(runner, "_agent") as mock_agent:
        fake_redis.queue_message(
            runner.STREAM, runner.CONSUMER_GROUP, "scout-worker-1",
            "msg-1",
            {
                b"idempotency_key": b"key-1",
                b"task_id": b"task-1",
                b"step_id": b"1",
                b"type": b"discover",
                b"goal": b"Research AI companies",
                b"agent": b"scout",
                b"depends_on": b"[]",
            },
        )

        mock_agent.run.return_value = []

        runner._process_once("scout-worker-1")

        mock_agent.run.assert_called_once()


@pytest.mark.asyncio
async def test_agent_runner_skips_wrong_agent_type(fake_redis: FakeRedis) -> None:
    runner = AgentRunner(AgentType.DEEP_DIVE, redis_client=fake_redis)  # type: ignore[arg-type]

    with patch.object(runner, "_agent") as mock_agent:
        fake_redis.queue_message(
            "tasks", runner.CONSUMER_GROUP, "dive-worker-1",
            "msg-1",
            {
                b"idempotency_key": b"key-1",
                b"task_id": b"task-1",
                b"step_id": b"1",
                b"type": b"discover",
                b"goal": b"Research AI",
                b"agent": b"scout",
                b"depends_on": b"[]",
            },
        )

        runner._process_once("dive-worker-1")
        mock_agent.run.assert_not_called()


@pytest.mark.asyncio
async def test_agent_runner_pushes_to_dlq_on_failure(fake_redis: FakeRedis) -> None:
    runner = AgentRunner(AgentType.VERIFICATION, redis_client=fake_redis)  # type: ignore[arg-type]

    with patch.object(runner, "_agent") as mock_agent:
        mock_agent.run.side_effect = RuntimeError("LLM call failed")

        fake_redis.queue_message(
            runner.STREAM, runner.CONSUMER_GROUP, "verify-worker-1",
            "msg-1",
            {
                b"idempotency_key": b"key-1",
                b"task_id": b"task-1",
                b"step_id": b"1",
                b"type": b"verify",
                b"goal": b"Verify claims",
                b"agent": b"verification",
                b"depends_on": b"[]",
            },
        )

        runner._process_once("verify-worker-1")
        assert "dlq" in fake_redis._data
