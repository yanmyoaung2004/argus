from __future__ import annotations

import json
import time
from typing import Any

import redis as redis_lib
from tenacity import retry, stop_after_attempt, wait_exponential

from argus.shared.config import settings


class BudgetExceededError(Exception):
    def __init__(self, task_id: str, current_cost: float, budget: float) -> None:
        self.task_id = task_id
        self.current_cost = current_cost
        self.budget = budget
        msg = (
            f"Budget exceeded for task '{task_id}': "
            f"${current_cost:.4f} > ${budget:.4f}"
        )
        super().__init__(msg)


class CostTracker:
    """Redis-backed per-research budget enforcer.

    Tracks cumulative cost across LLM calls, search API calls, and scrape operations.
    Exposes approve_call() to reject calls that would exceed the budget.
    """

    REDIS_KEY_PREFIX = "cost:"

    def __init__(self, task_id: str, redis_client: redis_lib.Redis | None = None) -> None:
        self.task_id = task_id
        self._redis = redis_client
        self._budget_limit = settings.budget_per_research

    def _get_redis(self) -> redis_lib.Redis | None:
        if self._redis is None:
            try:
                self._redis = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
            except Exception:
                return None
        return self._redis

    def _redis_key(self) -> str:
        return f"{self.REDIS_KEY_PREFIX}{self.task_id}"

    @retry(
        stop=stop_after_attempt(settings.llm_retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.llm_retry_min_wait_seconds,
            max=settings.llm_retry_max_wait_seconds,
        ),
    )
    def get_total_cost(self) -> float:
        r = self._get_redis()
        if r is None:
            return 0.0
        try:
            data = r.get(self._redis_key())
            if data:
                state_val = json.loads(data)
                return float(state_val.get("total_cost", 0.0))
        except Exception:
            pass
        return 0.0

    @retry(
        stop=stop_after_attempt(settings.llm_retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.llm_retry_min_wait_seconds,
            max=settings.llm_retry_max_wait_seconds,
        ),
    )
    def record_cost(self, amount: float, category: str = "llm") -> float:
        r = self._get_redis()
        if r is None:
            return amount

        raw = r.get(self._redis_key())
        parsed: dict[str, Any] = {}
        if raw:
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {}

        raw_breakdown: Any = parsed.get("breakdown", {})
        breakdown: dict[str, float] = raw_breakdown if isinstance(raw_breakdown, dict) else {}
        breakdown[category] = breakdown.get(category, 0.0) + amount

        raw_total: Any = parsed.get("total_cost", 0.0)
        total = float(raw_total) + amount
        state = {
            "total_cost": total,
            "breakdown": breakdown,
            "updated_at": time.time(),
        }
        r.set(self._redis_key(), json.dumps(state))
        return total

    def approve_call(self, estimated_cost: float) -> bool:
        current_total = self.get_total_cost()
        return (current_total + estimated_cost) <= self._budget_limit

    def check_budget(self) -> None:
        current_total = self.get_total_cost()
        if current_total >= self._budget_limit:
            raise BudgetExceededError(self.task_id, current_total, self._budget_limit)
        if current_total >= self._budget_limit * 0.6:
            import logging
            logging.getLogger(__name__).warning(
                "Soft budget cap reached",
                extra={
                    "task_id": self.task_id,
                    "current_cost": current_total,
                    "budget": self._budget_limit,
                },
            )

    def get_report(self) -> dict[str, Any]:
        r = self._get_redis()
        empty = {
            "task_id": self.task_id,
            "total_cost": 0.0,
            "breakdown": {},
            "budget_limit": self._budget_limit,
        }
        if r is None:
            return empty

        data_str = r.get(self._redis_key())
        if not data_str:
            return empty

        try:
            data: dict[str, Any] = json.loads(data_str)
            return {
                "task_id": self.task_id,
                "total_cost": data.get("total_cost", 0.0),
                "breakdown": data.get("breakdown", {}),
                "budget_limit": self._budget_limit,
            }
        except Exception:
            return empty
