from __future__ import annotations

import logging

import redis as redis_lib

from argus.shared.config import settings

logger = logging.getLogger(__name__)


def get_redis(timeout: int = 2) -> redis_lib.Redis | None:
    try:
        return redis_lib.from_url(settings.redis_url, socket_connect_timeout=timeout)
    except Exception as exc:
        logger.warning("Redis connection failed", extra={"error": str(exc)})
        return None


class RedisClient:
    """Holds an optional Redis client, lazily created via get_redis()."""

    def __init__(self, client: redis_lib.Redis | None = None) -> None:
        self._client = client

    @property
    def client(self) -> redis_lib.Redis | None:
        if self._client is None:
            self._client = get_redis()
        return self._client
