from __future__ import annotations

import time

from argus.services.orchestrator.timeout import IdleTimeoutMonitor


class TestIdleTimeoutMonitor:
    def test_not_expired_initially(self) -> None:
        monitor = IdleTimeoutMonitor("test-task", idle_timeout_minutes=30)
        assert not monitor.is_expired()

    def test_expired_after_timeout(self) -> None:
        monitor = IdleTimeoutMonitor("test-task", idle_timeout_minutes=0.001)
        time.sleep(0.1)
        assert monitor.is_expired()

    def test_activity_resets_timeout(self) -> None:
        monitor = IdleTimeoutMonitor("test-task", idle_timeout_minutes=0.1)
        time.sleep(0.02)
        monitor.mark_activity()
        assert not monitor.is_expired()

    def test_stop_prevents_expiry(self) -> None:
        monitor = IdleTimeoutMonitor("test-task", idle_timeout_minutes=0.001)
        monitor.stop()
        time.sleep(0.1)
        assert not monitor.is_expired()

    def test_idle_seconds_increases(self) -> None:
        monitor = IdleTimeoutMonitor("test-task", idle_timeout_minutes=30)
        initial = monitor.idle_seconds
        time.sleep(0.02)
        assert monitor.idle_seconds > initial

    def test_idle_seconds_resets_on_activity(self) -> None:
        monitor = IdleTimeoutMonitor("test-task", idle_timeout_minutes=30)
        time.sleep(0.02)
        monitor.mark_activity()
        assert monitor.idle_seconds < 0.01

    def test_custom_timeout(self) -> None:
        monitor = IdleTimeoutMonitor("test-task", idle_timeout_minutes=0.0005)
        time.sleep(0.1)
        assert monitor.is_expired()

    def test_not_expired_under_timeout(self) -> None:
        monitor = IdleTimeoutMonitor("test-task", idle_timeout_minutes=60)
        assert not monitor.is_expired()
