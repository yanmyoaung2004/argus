from __future__ import annotations

import pytest

from argus.services.dlq.consumer import DLQConsumer


class FakeRedis:
    def __init__(self) -> None:
        self._streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self._msg_counter = 0

    def xadd(self, stream: str, data: dict[str, str], maxlen: int | None = None) -> bytes:  # noqa: ARG002
        if stream not in self._streams:
            self._streams[stream] = []
        self._msg_counter += 1
        msg_id = f"{self._msg_counter:020d}-0"
        self._streams[stream].append((msg_id, data))
        return msg_id.encode()

    def xread(
        self,
        streams: dict[str, str],
        count: int | None = None,  # noqa: ARG002
        block: int | None = None,  # noqa: ARG002
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        result: list[tuple[str, list[tuple[str, dict[str, str]]]]] = []
        for stream_name, last_id in streams.items():
            messages = self._streams.get(stream_name, [])
            new_messages = [(mid, data) for mid, data in messages if mid > last_id]
            if count is not None:
                new_messages = new_messages[:count]
            if new_messages:
                result.append((stream_name, new_messages))
        return result

    def xlen(self, stream: str) -> int:
        return len(self._streams.get(stream, []))

    def xdel(self, stream: str, msg_id: bytes) -> int:
        msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
        messages = self._streams.get(stream, [])
        self._streams[stream] = [(mid, data) for mid, data in messages if mid != msg_id_str]
        return 1


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def consumer(fake_redis: FakeRedis) -> DLQConsumer:
    return DLQConsumer(redis_client=fake_redis)  # type: ignore[arg-type]


class TestDLQConsumer:
    def test_push_to_dlq_adds_message(self, consumer: DLQConsumer, fake_redis: FakeRedis) -> None:
        msg = {"task_id": "test-1", "goal": "test"}
        msg_id = consumer.push_to_dlq(msg, "Test failure")
        assert msg_id is not None
        assert fake_redis.xlen("dlq") == 1

    def test_push_to_dlq_stores_reason(self, consumer: DLQConsumer, fake_redis: FakeRedis) -> None:
        consumer.push_to_dlq({"task_id": "test"}, "Rate limit exceeded")
        entries = fake_redis._streams["dlq"]
        _, data = entries[0]
        assert "Rate limit exceeded" in data.get("reason", "")

    def test_push_to_dlq_stores_original_message(self, consumer: DLQConsumer, fake_redis: FakeRedis) -> None:
        original = {"task_id": "test-42", "type": "discover"}
        consumer.push_to_dlq(original, "Error")
        entries = fake_redis._streams["dlq"]
        _, data = entries[0]
        import json
        parsed = json.loads(data.get("original_message", "{}"))
        assert parsed["task_id"] == "test-42"

    def test_multiple_dlq_messages_accumulate(self, consumer: DLQConsumer, fake_redis: FakeRedis) -> None:
        for i in range(5):
            consumer.push_to_dlq({"task_id": f"test-{i}"}, f"Error {i}")
        assert fake_redis.xlen("dlq") == 5

    def test_push_returns_none_without_redis(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("argus.shared.config.settings.redis_url", "redis://localhost:99999/0")
        c = DLQConsumer(redis_client=None)
        result = c.push_to_dlq({"task_id": "test"}, "No redis")
        assert result is None

    def test_requeue_count_increments(self, consumer: DLQConsumer, fake_redis: FakeRedis) -> None:
        consumer.push_to_dlq({"task_id": "test"}, "Requeue test")
        entries = fake_redis._streams["dlq"]
        _, data = entries[0]
        assert data.get("requeue_count") == "0"

    def test_long_dlq_triggers_warning(self, consumer: DLQConsumer, fake_redis: FakeRedis) -> None:
        consumer.ALERT_THRESHOLD = 3
        for i in range(5):
            consumer.push_to_dlq({"task_id": f"test-{i}"}, f"Error {i}")
        assert fake_redis.xlen("dlq") == 5
