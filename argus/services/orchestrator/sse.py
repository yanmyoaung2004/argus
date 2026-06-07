from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import redis as redis_lib

from argus.shared.config import settings

logger = logging.getLogger(__name__)


class SSEStreamer:
    def __init__(self, task_id: str, redis_client: redis_lib.Redis | None = None) -> None:
        self.task_id = task_id
        self._redis = redis_client

    def _get_redis(self) -> redis_lib.Redis | None:
        if self._redis is None:
            try:
                self._redis = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
            except Exception:
                return None
        return self._redis

    async def stream(self) -> AsyncGenerator[str, None]:
        r = self._get_redis()
        last_id = "0"

        while True:
            if r is None:
                yield f"event: error\ndata: {json.dumps({'message': 'Redis unavailable'})}\n\n"
                break

            try:
                raw_results: list[Any] = list(
                    r.xread(
                        {f"progress:{self.task_id}": last_id},
                        count=10,
                        block=2000,
                    )
                )
            except Exception:
                logger.warning("SSE stream read error", extra={"task_id": self.task_id})
                yield f"event: error\ndata: {json.dumps({'message': 'Stream read error'})}\n\n"
                break

            for raw_entry in raw_results:
                if not isinstance(raw_entry, (list, tuple)) or len(raw_entry) < 2:
                    continue
                messages = raw_entry[1]
                for msg_entry in messages:
                    if not isinstance(msg_entry, (list, tuple)) or len(msg_entry) < 2:
                        continue
                    msg_id, msg_data = msg_entry
                    last_id = msg_id
                    if not isinstance(msg_data, dict):
                        continue
                    raw_type = msg_data.get(b"type", b"message")
                    if isinstance(raw_type, bytes):
                        event_str = raw_type.decode("utf-8")
                    else:
                        event_str = str(raw_type)
                    data_raw = msg_data.get(b"data", b"{}")
                    if isinstance(data_raw, bytes):
                        payload = data_raw.decode("utf-8")
                    else:
                        payload = json.dumps(data_raw)
                    yield f"event: {event_str}\ndata: {payload}\n\n"

            await asyncio.sleep(0.1)
