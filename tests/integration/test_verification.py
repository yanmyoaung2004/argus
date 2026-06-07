from __future__ import annotations

from unittest.mock import patch

import pytest

from argus.services.agents.verification import VerificationAgent
from argus.shared.models import AgentType, TaskStep, TaskStepStatus, TaskType


@pytest.fixture
def agent() -> VerificationAgent:
    return VerificationAgent()


@pytest.fixture
def mock_claims_for_verification() -> list[dict[str, object]]:
    return []


@pytest.mark.asyncio
async def test_verification_no_claims(agent: VerificationAgent) -> None:
    step = TaskStep(id=1, type=TaskType.VERIFY, goal="Verify", agent=AgentType.VERIFICATION, task_id="test-no-claims", status=TaskStepStatus.RUNNING)
    with (
        patch.object(agent, "_get_claims_for_task", return_value=[]),
        patch("time.sleep"),
    ):
        facts = await agent.run(step)
    assert len(facts) == 0


@pytest.mark.asyncio
async def test_verification_detects_conflict(agent: VerificationAgent) -> None:
    step = TaskStep(id=2, type=TaskType.VERIFY, goal="Verify", agent=AgentType.VERIFICATION, task_id="test-conflict", status=TaskStepStatus.RUNNING)

    claims = [
        {"statement": "OpenAI has 1000 employees", "entity_name": "OpenAI", "attribute": "employees", "source_urls": ["https://a.com"]},
        {"statement": "OpenAI has 5000 employees", "entity_name": "OpenAI", "attribute": "employees", "source_urls": ["https://b.com"]},
    ]

    with (
        patch.object(agent, "_get_claims_for_task", return_value=claims),
        patch.object(agent, "_router") as mock_router,
    ):
        mock_router.complete.return_value = (
            '{"relationship": "contradictory", "reason": "Employee counts differ by 4000"}',
            "groq",
            0.0,
        )

        facts = await agent.run(step)
        assert len(facts) == 1
        conflict = facts[0].facts[0]
        assert conflict.relationship == "contradictory"


@pytest.mark.asyncio
async def test_verification_skips_different_attributes(agent: VerificationAgent) -> None:
    step = TaskStep(id=3, type=TaskType.VERIFY, goal="Verify", agent=AgentType.VERIFICATION, task_id="test-skip", status=TaskStepStatus.RUNNING)

    claims = [
        {"statement": "OpenAI has 1000 employees", "entity_name": "OpenAI", "attribute": "employees", "source_urls": []},
        {"statement": "OpenAI raised $10B", "entity_name": "OpenAI", "attribute": "funding", "source_urls": []},
    ]

    with patch.object(agent, "_get_claims_for_task", return_value=claims):
        facts = await agent.run(step)
    assert len(facts) == 0
