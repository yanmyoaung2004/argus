from __future__ import annotations

import re

from argus.shared.models import AgentType, ResearchPlan, TaskStep, TaskStepStatus, TaskType


class RuleBasedPlanner:
    COMPETITIVE_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"(?i)(top|leading|biggest|largest|best)\s+\d*\s*(companies|startups|firms|brands)"),
        re.compile(r"(?i)(competitive|competitor|compete|rivalry|market\s*share)"),
        re.compile(r"(?i)compare\s+(and\s+)?contrast"),
    ]

    TECH_COMPARISON_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"(?i)(compared?|comparison|difference|versus|vs\.?|alternative)"),
        re.compile(r"(?i)(technology|tech|framework|library|tool|platform|language)\s+compar"),
        re.compile(r"(?i)which\s+(is\s+)?better"),
    ]

    ACADEMIC_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"(?i)(survey|literature review|academic|research paper|publication|citation)"),
        re.compile(r"(?i)(state.of.the.art|soa|recent advances|latest research)"),
    ]

    def decompose(self, query: str) -> ResearchPlan:
        query_lower = query.lower()

        steps: list[TaskStep] = []
        step_id = 0

        step_id += 1
        steps.append(TaskStep(
            id=step_id,
            type=TaskType.DISCOVER,
            goal=f"Research {query_lower[:60]}{'...' if len(query_lower) > 60 else ''}",
            agent=AgentType.SCOUT,
            status=TaskStepStatus.PENDING,
            depends_on=[],
        ))

        step_id += 1
        steps.append(TaskStep(
            id=step_id,
            type=TaskType.EXTRACT,
            goal=f"Deep-dive into sources for: {query_lower[:60]}",
            agent=AgentType.DEEP_DIVE,
            status=TaskStepStatus.PENDING,
            depends_on=[step_id - 1],
        ))

        step_id += 1
        steps.append(TaskStep(
            id=step_id,
            type=TaskType.VERIFY,
            goal=f"Verify claims about: {query_lower[:60]}",
            agent=AgentType.VERIFICATION,
            status=TaskStepStatus.PENDING,
            depends_on=[step_id - 1],
        ))

        step_id += 1
        steps.append(TaskStep(
            id=step_id,
            type=TaskType.SYNTHESIZE,
            goal=f"Synthesize findings for: {query_lower[:60]}",
            agent=AgentType.SYNTHESIS,
            status=TaskStepStatus.PENDING,
            depends_on=[step_id - 1],
        ))

        return ResearchPlan(
            steps=steps,
            estimated_sources=len(steps) * 10,
            estimated_time_minutes=len(steps) * 5,
        )

    @staticmethod
    def _matches_any(text: str, patterns: list[re.Pattern[str]]) -> bool:
        return any(p.search(text) for p in patterns)
