from __future__ import annotations

import logging
from typing import Any

from argus.services.agents.base import BaseAgent
from argus.services.tools.search import WebSearch
from argus.shared.models import AgentType, Entity, Fact, Source, TaskStep

logger = logging.getLogger(__name__)


class ScoutAgent(BaseAgent):
    def __init__(
        self,
        router: Any = None,
        idempotency: Any = None,
        cost_tracker: Any = None,
    ) -> None:
        super().__init__(
            AgentType.SCOUT,
            router=router,
            idempotency=idempotency,
            cost_tracker=cost_tracker,
        )
        self._searcher = WebSearch()

    async def run(self, step: TaskStep) -> list[Fact]:
        logger.info("ScoutAgent running", extra={"step_id": step.id, "goal": step.goal})

        search_query = step.goal.replace("Research ", "").strip()
        search_response = self._searcher.search(search_query, max_results=10)

        entities: list[Entity] = []
        sources: list[Source] = []

        for result in search_response.results:
            source = Source(
                url=result.url,
                title=result.title,
                credibility_score=0.5,
            )
            sources.append(source)

            name = result.title
            if " - " in name:
                name = name.split(" - ")[0].strip()
            entity_type = "organization" if any(
                t in result.url for t in [".com", ".org", ".io"]
            ) else "unknown"
            entity = Entity(
                name=name[:80],
                type=entity_type,
                description=result.snippet[:200],
                attributes={"url": result.url, "snippet": result.snippet},
            )

            url_lower = result.url.lower()
            if any(domain in url_lower for domain in ["wikipedia.org", "britannica.com"]):
                entity.attributes["authoritative"] = True

            entities.append(entity)

        logger.info("ScoutAgent complete", extra={
            "step_id": step.id, "sources": len(sources), "entities": len(entities),
        })

        return self._emit_facts(step, [*entities, *sources])
