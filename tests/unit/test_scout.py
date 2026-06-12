from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from argus.services.agents.scout import ScoutAgent
from argus.services.tools.search import SearchResponse, SearchResult
from argus.shared.models import AgentType, Fact, TaskStep, TaskStepStatus, TaskType


@pytest.fixture
def scout() -> ScoutAgent:
    return ScoutAgent(router=MagicMock())


@pytest.fixture
def sample_step() -> TaskStep:
    return TaskStep(
        id=1,
        type=TaskType.DISCOVER,
        goal="Research AI startups",
        agent=AgentType.SCOUT,
        status=TaskStepStatus.RUNNING,
        task_id="test-123",
        query="top AI startups 2024",
    )


class TestScoutAgent:
    async def test_empty_search_returns_empty(self, scout: ScoutAgent, sample_step: TaskStep) -> None:
        scout._searcher.search = MagicMock(return_value=SearchResponse(results=[]))
        result = await scout.run(sample_step)
        assert result == []

    async def test_search_returns_facts(self, scout: ScoutAgent, sample_step: TaskStep) -> None:
        scout._searcher.search = MagicMock(return_value=SearchResponse(
            results=[SearchResult(url="https://example.com", title="Example", snippet="test")],
        ))
        scout._analyze_results = MagicMock(return_value=[])
        result = await scout.run(sample_step)
        assert len(result) == 1
        fact = result[0]
        assert isinstance(fact, Fact)
        assert fact.agent == AgentType.SCOUT
        assert fact.task_id == "test-123"

    async def test_analyze_results_called(self, scout: ScoutAgent, sample_step: TaskStep) -> None:
        scout._searcher.search = MagicMock(return_value=SearchResponse(
            results=[SearchResult(url="https://a.com", title="A", snippet="a")],
        ))
        scout._analyze_results = MagicMock(return_value=[])
        await scout.run(sample_step)
        scout._analyze_results.assert_called_once()

    async def test_analyze_results_llm_failure_falls_back(self, scout: ScoutAgent, sample_step: TaskStep) -> None:
        scout._searcher.search = MagicMock(return_value=SearchResponse(
            results=[SearchResult(url="https://fallback.com", title="Fallback", snippet="data")],
        ))
        scout._router.complete.side_effect = RuntimeError("LLM failed")
        scout._analyze_results = scout._analyze_results  # use real implementation
        result = await scout.run(sample_step)
        assert len(result) == 1
        fact = result[0]
        assert fact.agent == AgentType.SCOUT

    async def test_no_router_skips_analysis(self) -> None:
        agent = ScoutAgent(router=None)
        agent._searcher.search = MagicMock(return_value=SearchResponse(
            results=[SearchResult(url="https://x.com", title="X", snippet="x")],
        ))
        result = await agent.run(TaskStep(
            id=1, type=TaskType.DISCOVER, goal="test", agent=AgentType.SCOUT,
            status=TaskStepStatus.RUNNING, task_id="t", query="q",
        ))
        assert len(result) == 1

    async def test_analyze_results_filters_low_relevance(self, scout: ScoutAgent, sample_step: TaskStep) -> None:
        scout._searcher.search = MagicMock(return_value=SearchResponse(
            results=[SearchResult(url="https://rel.com", title="Relevant", snippet="data")],
        ))
        scout._router.complete.return_value = (
            '[{"url": "https://rel.com", "title": "Relevant", "relevance": "high", '
            '"extracted_entities": [{"name": "Entity1", "type": "org", "description": "desc"}]}]',
            "ollama",
            0.0,
        )
        result = await scout.run(sample_step)
        assert len(result) == 1
