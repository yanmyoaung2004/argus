from __future__ import annotations

import json
import logging
from uuid import uuid4

import redis as redis_lib

from argus.services.orchestrator.planner.rules import RuleBasedPlanner
from argus.services.orchestrator.timeout import IdleTimeoutMonitor
from argus.shared.config import settings
from argus.shared.idempotency import generate_idempotency_key
from argus.shared.models import ResearchPlan, ResearchStatus, ResearchTask

logger = logging.getLogger(__name__)


class ResearchManager:
    def __init__(self, redis_client: redis_lib.Redis | None = None) -> None:
        self._redis = redis_client
        self._planner = RuleBasedPlanner()
        self._tasks: dict[str, ResearchTask] = {}
        self._timeouts: dict[str, IdleTimeoutMonitor] = {}
        self._shutdown = False

    def _get_redis(self) -> redis_lib.Redis | None:
        if self._redis is None:
            try:
                self._redis = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
            except Exception:
                return None
        return self._redis

    async def create_task(
        self,
        query: str,
        max_sources: int = 50,
        max_duration_minutes: int = 30,
    ) -> ResearchTask:
        task = ResearchTask(
            task_id=uuid4(),
            query=query,
            max_sources=max_sources,
            max_duration_minutes=max_duration_minutes,
            status=ResearchStatus.PLANNING,
        )
        task_id_str = str(task.task_id)
        self._tasks[task_id_str] = task

        try:
            plan = self._planner.decompose(query)
            task.plan = plan
            task.status = ResearchStatus.RUNNING
            self._push_plan(task_id_str, plan)
            self._timeouts[task_id_str] = IdleTimeoutMonitor(
                task_id=task_id_str,
                idle_timeout_minutes=settings.research_idle_timeout_minutes,
            )
            logger.info(
                "Research planned and queued",
                extra={"task_id": task_id_str, "steps": len(plan.steps)},
            )
        except Exception as exc:
            task.status = ResearchStatus.FAILED
            task.error_message = str(exc)
            logger.error("Planning failed", extra={"task_id": task_id_str, "error": str(exc)})

        return task

    def _push_plan(self, task_id: str, plan: ResearchPlan) -> None:
        r = self._get_redis()
        if r is None:
            logger.warning("No Redis available, skipping plan push", extra={"task_id": task_id})
            return

        for step in plan.steps:
            message = {
                "idempotency_key": generate_idempotency_key(),
                "task_id": task_id,
                "step_id": step.id,
                "type": step.type.value,
                "agent": step.agent.value,
                "goal": step.goal,
                "depends_on": json.dumps(step.depends_on),
            }
            stream = f"tasks:{step.agent.value}"
            r.xadd(stream, message, maxlen=settings.redis_stream_maxlen)  # type: ignore[arg-type]

    def mark_progress(self, task_id: str) -> None:
        monitor = self._timeouts.get(task_id)
        if monitor is not None:
            monitor.mark_activity()

    def complete_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is not None and task.status not in (ResearchStatus.DONE, ResearchStatus.FAILED):
            task.status = ResearchStatus.DONE
            from datetime import datetime
            task.completed_at = datetime.utcnow()
            logger.info("Research completed", extra={"task_id": task_id})
        monitor = self._timeouts.pop(task_id, None)
        if monitor is not None:
            monitor.stop()

    def fail_task(self, task_id: str, error: str) -> None:
        task = self._tasks.get(task_id)
        if task is not None and task.status != ResearchStatus.DONE:
            task.status = ResearchStatus.FAILED
            task.error_message = error
            logger.error("Research failed", extra={"task_id": task_id, "error": error})
        monitor = self._timeouts.pop(task_id, None)
        if monitor is not None:
            monitor.stop()

    async def check_timeouts(self) -> None:
        if self._shutdown:
            return
        expired_ids = [
            tid for tid, mon in self._timeouts.items()
            if mon.is_expired()
        ]
        for tid in expired_ids:
            msg = f"Idle timeout exceeded ({settings.research_idle_timeout_minutes} min)"
            self.fail_task(tid, msg)

    async def shutdown(self) -> None:
        self._shutdown = True
        logger.info("Research manager shutting down")
        for task_id in list(self._timeouts.keys()):
            item = self._timeouts.get(task_id)
            if item is not None:
                item.stop()
        self._timeouts.clear()

    async def get_report(self, task_id: str) -> str | None:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        from argus.ui.report_generator import MarkdownReportGenerator
        gen = MarkdownReportGenerator()
        return gen.generate(task_id)

    async def get_html_report(self, task_id: str) -> str | None:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        from argus.ui.report_generator import HTMLReportGenerator
        gen = HTMLReportGenerator()
        return gen.generate(task_id)

    async def apply_feedback(self, source_id: int, is_correct: bool) -> float:
        import sqlite3

        from argus.services.tools.credibility import SourceCredibilityScorer

        conn = sqlite3.connect(settings.sqlite_path)
        try:
            scorer = SourceCredibilityScorer()
            return scorer.apply_user_feedback(conn, source_id, is_correct)
        finally:
            conn.close()
