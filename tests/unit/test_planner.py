from __future__ import annotations

from unittest.mock import MagicMock, patch

from argus.services.orchestrator.planner.llm_planner import LLMPlanner
from argus.services.orchestrator.planner.rules import RuleBasedPlanner
from argus.shared.models import ResearchPlan, TaskType


class TestRuleBasedPlanner:
    def test_decompose_returns_plan_with_steps(self) -> None:
        planner = RuleBasedPlanner()
        plan = planner.decompose("top AI startups in 2024")
        assert isinstance(plan, ResearchPlan)
        assert len(plan.steps) >= 3

    def test_decompose_includes_synthesize(self) -> None:
        planner = RuleBasedPlanner()
        plan = planner.decompose("compare Rust and Go")
        types = [s.type for s in plan.steps]
        assert TaskType.SYNTHESIZE in types

    def test_decompose_first_step_is_discover(self) -> None:
        planner = RuleBasedPlanner()
        plan = planner.decompose("quantum computing")
        assert plan.steps[0].type == TaskType.DISCOVER

    def test_decompose_last_step_is_synthesize(self) -> None:
        planner = RuleBasedPlanner()
        plan = planner.decompose("cloud providers")
        assert plan.steps[-1].type == TaskType.SYNTHESIZE

    def test_decompose_dependency_chain(self) -> None:
        planner = RuleBasedPlanner()
        plan = planner.decompose("machine learning trends")
        for i, step in enumerate(plan.steps):
            if i == 0:
                assert step.depends_on == []
            else:
                assert step.depends_on == [i]


class TestLLMPlanner:
    def test_fallback_on_llm_failure(self) -> None:
        router = MagicMock()
        router.complete.side_effect = RuntimeError("LLM down")
        planner = LLMPlanner(router=router)
        plan = planner.decompose("test query")
        assert isinstance(plan, ResearchPlan)
        assert len(plan.steps) >= 2

    def test_fallback_on_bad_json(self) -> None:
        router = MagicMock()
        router.complete.return_value = ("not valid json", "ollama", 0.0)
        planner = LLMPlanner(router=router)
        plan = planner.decompose("test query")
        assert isinstance(plan, ResearchPlan)

    def test_fallback_on_empty_steps(self) -> None:
        router = MagicMock()
        router.complete.return_value = ('{"steps": []}', "ollama", 0.0)
        planner = LLMPlanner(router=router)
        plan = planner.decompose("test query")
        assert isinstance(plan, ResearchPlan)

    @patch("argus.llm.router.CostAwareRouter")
    def test_parses_llm_response(self, _mock_router_cls: MagicMock) -> None:
        router = MagicMock()
        router.complete.return_value = (
            '{"steps": [{"type": "discover", "goal": "Find sources"}, '
            '{"type": "extract", "goal": "Extract facts"}, '
            '{"type": "synthesize", "goal": "Write report"}], '
            '"estimated_sources": 15, "estimated_time_minutes": 10}',
            "ollama",
            0.0,
        )
        planner = LLMPlanner(router=router)
        plan = planner.decompose("test")
        assert len(plan.steps) == 3
        assert plan.estimated_sources == 15
