from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


class IdleTimeoutMonitor:
    def __init__(
        self,
        task_id: str,
        idle_timeout_minutes: int = 30,
        max_duration_minutes: int | None = None,
    ) -> None:
        self.task_id = task_id
        self._idle_timeout = idle_timeout_minutes * 60
        self._max_duration = max_duration_minutes * 60 if max_duration_minutes else None
        self._last_activity: float = time.time()
        self._start_time: float = time.time()
        self._stopped = False

    def mark_activity(self) -> None:
        self._last_activity = time.time()

    def is_expired(self) -> bool:
        if self._stopped:
            return False
        now = time.time()
        elapsed = now - self._last_activity
        if elapsed > self._idle_timeout:
            logger.info(
                "Task idle timeout exceeded",
                extra={"task_id": self.task_id, "idle_seconds": int(elapsed)},
            )
            return True
        if self._max_duration is not None:
            total_elapsed = now - self._start_time
            if total_elapsed > self._max_duration:
                logger.info(
                    "Task max duration exceeded",
                    extra={
                        "task_id": self.task_id,
                        "elapsed_seconds": int(total_elapsed),
                        "max_seconds": self._max_duration,
                    },
                )
                return True
        return False

    def stop(self) -> None:
        self._stopped = True

    @property
    def idle_seconds(self) -> float:
        return time.time() - self._last_activity
