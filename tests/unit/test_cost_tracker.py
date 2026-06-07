from __future__ import annotations

import pytest

from argus.services.tools.cost_tracker import BudgetExceededError, CostTracker


class FakeRedis:
    """In-memory Redis mock."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def tracker(fake_redis: FakeRedis) -> CostTracker:
    return CostTracker(task_id="test-task-1", redis_client=fake_redis)  # type: ignore[arg-type]


class TestCostTracker:
    def test_initial_cost_is_zero(self, tracker: CostTracker) -> None:
        assert tracker.get_total_cost() == 0.0

    def test_record_cost_accumulates(self, tracker: CostTracker) -> None:
        tracker.record_cost(0.10, category="llm")
        tracker.record_cost(0.05, category="search")
        assert tracker.get_total_cost() == pytest.approx(0.15)

    def test_record_cost_returns_new_total(self, tracker: CostTracker) -> None:
        total = tracker.record_cost(0.20)
        assert total == pytest.approx(0.20)

    def test_approve_call_under_budget(self, tracker: CostTracker) -> None:
        assert tracker.approve_call(0.10) is True

    def test_approve_call_over_budget(self, tracker: CostTracker) -> None:
        tracker.record_cost(0.49)
        assert tracker.approve_call(0.02) is False

    def test_approve_call_at_exact_budget(self, tracker: CostTracker) -> None:
        tracker.record_cost(0.50)
        assert tracker.approve_call(0.01) is False

    def test_check_budget_raises_when_exceeded(self, tracker: CostTracker) -> None:
        tracker.record_cost(0.60)
        with pytest.raises(BudgetExceededError) as exc:
            tracker.check_budget()
        assert exc.value.task_id == "test-task-1"
        assert exc.value.budget == 0.50

    def test_approve_call_just_under_budget(self, tracker: CostTracker) -> None:
        tracker.record_cost(0.49)
        assert tracker.approve_call(0.01) is True

    def test_get_report_returns_breakdown(self, tracker: CostTracker) -> None:
        tracker.record_cost(0.10, category="llm")
        tracker.record_cost(0.05, category="search")
        report = tracker.get_report()
        assert report["total_cost"] == pytest.approx(0.15)
        assert report["breakdown"]["llm"] == pytest.approx(0.10)
        assert report["breakdown"]["search"] == pytest.approx(0.05)
        assert report["budget_limit"] == 0.50
        assert report["task_id"] == "test-task-1"

    def test_get_report_empty_when_no_costs(self, tracker: CostTracker) -> None:
        report = tracker.get_report()
        assert report["total_cost"] == 0.0
        assert report["breakdown"] == {}

    def test_multiple_tasks_isolated(self, fake_redis: FakeRedis) -> None:
        t1 = CostTracker(task_id="task-1", redis_client=fake_redis)  # type: ignore[arg-type]
        t2 = CostTracker(task_id="task-2", redis_client=fake_redis)  # type: ignore[arg-type]
        t1.record_cost(0.30)
        t2.record_cost(0.20)
        assert t1.get_total_cost() == pytest.approx(0.30)
        assert t2.get_total_cost() == pytest.approx(0.20)

    def test_record_cost_negative_amount(self, tracker: CostTracker) -> None:
        tracker.record_cost(0.10)
        tracker.record_cost(-0.05)
        assert tracker.get_total_cost() == pytest.approx(0.05)

    def test_check_budget_does_not_raise_under_soft_cap(self, tracker: CostTracker) -> None:
        tracker.record_cost(0.10)
        tracker.check_budget()

    def test_costs_persist_across_tracker_instances(self, fake_redis: FakeRedis) -> None:
        t1 = CostTracker(task_id="persist-test", redis_client=fake_redis)  # type: ignore[arg-type]
        t1.record_cost(0.25)

        t2 = CostTracker(task_id="persist-test", redis_client=fake_redis)  # type: ignore[arg-type]
        assert t2.get_total_cost() == pytest.approx(0.25)
