from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


class IdleTimeoutMonitor:
    def __init__(self, task_id: str, idle_timeout_minutes: int = 30) -> None:
        self.task_id = task_id
        self._idle_timeout = idle_timeout_minutes * 60
        self._last_activity: float = time.time()
        self._stopped = False

    def mark_activity(self) -> None:
        self._last_activity = time.time()

    def is_expired(self) -> bool:
        if self._stopped:
            return False
        elapsed = time.time() - self._last_activity
        return elapsed > self._idle_timeout

    def stop(self) -> None:
        self._stopped = True

    @property
    def idle_seconds(self) -> float:
        return time.time() - self._last_activity
