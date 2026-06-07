from __future__ import annotations

import logging
import threading
import time
from typing import Any

import redis as redis_lib

from argus.shared.config import settings

logger = logging.getLogger(__name__)

HEARTBEAT_PREFIX = "heartbeat"
HEARTBEAT_TTL = settings.agent_heartbeat_ttl
HEARTBEAT_INTERVAL = max(1, HEARTBEAT_TTL // 3)


class HeartbeatWriter:
    def __init__(self, agent_id: str, redis_client: redis_lib.Redis | None = None) -> None:
        self._agent_id = agent_id
        self._redis = redis_client
        self._running = False
        self._thread: threading.Thread | None = None

    def _get_redis(self) -> redis_lib.Redis | None:
        if self._redis is None:
            try:
                self._redis = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
            except Exception:
                return None
        return self._redis

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Heartbeat writer started", extra={"agent_id": self._agent_id})

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5)
        logger.info("Heartbeat writer stopped", extra={"agent_id": self._agent_id})

    def _loop(self) -> None:
        while self._running:
            r = self._get_redis()
            if r is not None:
                try:
                    key = f"{HEARTBEAT_PREFIX}:{self._agent_id}"
                    r.setex(key, HEARTBEAT_TTL, str(time.time()))
                except Exception as exc:
                    logger.warning("Heartbeat write failed", extra={"agent_id": self._agent_id, "error": str(exc)})
            for _ in range(HEARTBEAT_INTERVAL):
                if not self._running:
                    return
                time.sleep(1)


def get_alive_agents(redis_client: redis_lib.Redis) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    try:
        cursor: Any = 0
        while True:
            cursor, keys = redis_client.scan(cursor, match=f"{HEARTBEAT_PREFIX}:*", count=100)
            for key in keys:
                key_str = key.decode("utf-8") if isinstance(key, bytes) else str(key)
                agent_id = key_str[len(HEARTBEAT_PREFIX) + 1:]
                ttl = redis_client.ttl(key)
                last_seen_raw = redis_client.get(key)
                last_seen = float(last_seen_raw) if last_seen_raw else 0.0
                age = time.time() - last_seen if last_seen else 0.0
                result[agent_id] = {
                    "alive": ttl is not None and ttl > 0,
                    "ttl_remaining": ttl if ttl and ttl > 0 else 0,
                    "last_seen": last_seen,
                    "age_seconds": age,
                }
            if cursor == 0:
                break
    except Exception as exc:
        logger.warning("Failed to read heartbeats", extra={"error": str(exc)})
    return result
