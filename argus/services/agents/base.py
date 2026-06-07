from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from argus.llm.circuit_breaker import ProviderCircuitBreaker
from argus.llm.router import CostAwareRouter
from argus.services.tools.cost_tracker import CostTracker
from argus.shared.idempotency import IdempotencyChecker
from argus.shared.models import AgentType, Fact, LLMProviderType, TaskStep

logger = logging.getLogger(__name__)


class BudgetError(Exception):
    ...


class BaseAgent(ABC):
    def __init__(
        self,
        agent_type: AgentType,
        router: CostAwareRouter | None = None,
        idempotency: IdempotencyChecker | None = None,
        cost_tracker: CostTracker | None = None,
    ) -> None:
        self.agent_type = agent_type
        self._router = router or CostAwareRouter()
        self._idempotency = idempotency
        self._cost_tracker = cost_tracker

    @abstractmethod
    async def run(self, step: TaskStep) -> list[Fact]:
        ...

    def _check_budget(self, estimated_cost: float = 0.0) -> None:
        if self._cost_tracker is None:
            return
        if not self._cost_tracker.approve_call(estimated_cost):
            budget = self._cost_tracker._budget_limit
            raise BudgetError(
                f"Budget would be exceeded: +${estimated_cost:.4f} would exceed ${budget:.4f}"
            )
        self._cost_tracker.check_budget()

    def _check_circuit_breaker(self, provider: LLMProviderType) -> bool:
        cb = ProviderCircuitBreaker(provider)
        return cb.allow_request

    def _record_cost(self, amount: float, category: str = "llm") -> None:
        if self._cost_tracker is not None:
            self._cost_tracker.record_cost(amount, category=category)
            self._cost_tracker.check_budget()

    def _emit_facts(
        self,
        step: TaskStep,
        facts: list[Any],
    ) -> list[Fact]:
        from argus.shared.idempotency import generate_idempotency_key

        if self._idempotency:
            key = f"{step.task_id}:{step.id}:emit"
            if self._idempotency.is_processed(key):
                return []

        fact_batch = Fact(
            idempotency_key=generate_idempotency_key(),
            task_id=step.task_id,
            step_id=step.id,
            agent=self.agent_type,
            facts=facts,
        )
        return [fact_batch]
