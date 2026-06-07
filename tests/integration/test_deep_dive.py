from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from argus.services.agents.deep_dive import DeepDiveAgent
from argus.shared.models import AgentType, TaskStep, TaskStepStatus, TaskType


class FakeScrapeResponse:
    class Content:
        def __init__(self, markdown: str, metadata: dict[str, str] | None = None):
            self.markdown = markdown
            self.metadata = metadata or {"title": "Test Page"}
            self.content_type = "text/html"
            self.content_hash = "abc123"

    def __init__(self, markdown: str = "Test content with factual data about AI companies."):
        self.content = self.Content(markdown)
        self.metadata = type("Meta", (), {"provider": "mock", "latency_ms": 1, "cost": 0.0})()


@pytest.fixture
def agent() -> DeepDiveAgent:
    return DeepDiveAgent()


@pytest.mark.asyncio
async def test_deep_dive_no_urls(agent: DeepDiveAgent) -> None:
    step = TaskStep(id=1, type=TaskType.EXTRACT, goal="Extract", agent=AgentType.DEEP_DIVE, task_id="test-no-urls", status=TaskStepStatus.RUNNING)
    with (
        patch.object(agent, "_get_source_urls_for_task", return_value=[]),
        patch("time.sleep"),
    ):
        facts = await agent.run(step)
    assert len(facts) == 0


@pytest.mark.asyncio
async def test_deep_dive_with_urls_and_mock_llm(agent: DeepDiveAgent) -> None:
    step = TaskStep(id=1, type=TaskType.EXTRACT, goal="Extract data", agent=AgentType.DEEP_DIVE, task_id="test-with-urls", status=TaskStepStatus.RUNNING)

    with (
        patch.object(agent, "_get_source_urls_for_task", return_value=["https://example.com/article1"]),
        patch.object(agent, "_scraper") as mock_scraper,
        patch.object(agent, "_get_router") as mock_router,
    ):
        mock_scraper.scrape.return_value = FakeScrapeResponse(
            "OpenAI raised $10B in funding. Microsoft invested $1B in 2023."
        )

        mock_router_instance = MagicMock()
        mock_router.return_value = mock_router_instance
        mock_router_instance.complete.return_value = (
            '[{"statement": "OpenAI raised $10B in funding", "entity_name": "OpenAI", "attribute": "funding", "confidence": "high"}]',
            "ollama",
            0.0,
        )

        facts = await agent.run(step)

        assert len(facts) == 1
        fact = facts[0]
        assert len(fact.facts) == 2  # 1 claim + 1 source
        assert fact.agent == AgentType.DEEP_DIVE


@pytest.mark.asyncio
async def test_deep_dive_llm_fallback_to_single(agent: DeepDiveAgent) -> None:
    step = TaskStep(id=2, type=TaskType.EXTRACT, goal="Extract", agent=AgentType.DEEP_DIVE, task_id="test-fallback", status=TaskStepStatus.RUNNING)

    with (
        patch.object(agent, "_get_source_urls_for_task", return_value=["https://example.com/a", "https://example.com/b"]),
        patch.object(agent, "_scraper") as mock_scraper,
        patch.object(agent, "_get_router") as mock_router,
    ):
        mock_scraper.scrape.side_effect = [
            FakeScrapeResponse("Content A about AI."),
            FakeScrapeResponse("Content B about ML."),
        ]

        router = MagicMock()
        mock_router.return_value = router

        def _mock_complete(*args: Any, **kwargs: Any) -> tuple[str, str, float]:
            import json
            if "Source 2" in kwargs.get("prompt", ""):
                raise RuntimeError("Batch failed")
            return (json.dumps([]), "ollama", 0.0)

        router.complete = _mock_complete

        facts = await agent.run(step)
        assert len(facts) > 0
