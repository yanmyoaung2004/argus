from __future__ import annotations

import json
import logging
from typing import Any

from argus.llm.router import CostAwareRouter
from argus.services.agents.base import BaseAgent
from argus.services.tools.parser import DocumentParser
from argus.services.tools.scraper import WebScraper
from argus.shared.models import AgentType, Claim, Fact, Source, TaskStep

logger = logging.getLogger(__name__)

BATCH_SIZE = 5


def _build_extraction_prompt(sources: list[dict[str, str]]) -> str:
    lines: list[str] = [
        "Extract factual claims from the following sources. "
        "For each claim, identify: the statement, the entity it refers to, "
        "and a confidence level (high/medium/low). "
        "Return the results as a JSON list of objects with keys: "
        "statement, entity_name, attribute, confidence.",
        "",
    ]
    for i, src in enumerate(sources, start=1):
        lines.append(f"--- Source {i} ---")
        lines.append(f"URL: {src.get('url', 'unknown')}")
        lines.append(f"Title: {src.get('title', '')}")
        lines.append(f"Content:\n{src.get('content', '')[:2000]}")
        lines.append("")
    return "\n".join(lines)


class DeepDiveAgent(BaseAgent):
    def __init__(
        self,
        router: Any = None,
        idempotency: Any = None,
        cost_tracker: Any = None,
    ) -> None:
        super().__init__(
            AgentType.DEEP_DIVE,
            router=router,
            idempotency=idempotency,
            cost_tracker=cost_tracker,
        )
        self._scraper = WebScraper()
        self._parser = DocumentParser()
        self._batch_router: CostAwareRouter | None = None

    def _get_router(self) -> CostAwareRouter:
        if self._batch_router is None:
            self._batch_router = CostAwareRouter()
        return self._batch_router

    async def run(self, step: TaskStep) -> list[Fact]:
        logger.info("DeepDiveAgent running", extra={"step_id": step.id, "goal": step.goal})

        task_id = step.task_id
        urls = self._get_source_urls_for_task(task_id)
        if not urls:
            import time
            for attempt in range(5):
                logger.info(
                    "Waiting for sources to appear in KG",
                    extra={"step_id": step.id, "attempt": attempt + 1},
                )
                time.sleep(2)
                urls = self._get_source_urls_for_task(task_id)
                if urls:
                    break
            if not urls:
                logger.info("No sources to deep-dive after waiting", extra={"step_id": step.id})
                return []

        sources_data: list[dict[str, str]] = []
        for url in urls:
            try:
                response = self._scraper.scrape(url)
                if response.content and response.content.markdown.strip():
                    sources_data.append({
                        "url": url,
                        "title": response.content.metadata.get("title", url),
                        "content": response.content.markdown,
                    })
            except Exception as exc:
                logger.warning("Scrape failed", extra={"url": url, "error": str(exc)})

        if not sources_data:
            return []

        all_claims: list[Claim] = []
        all_sources: list[Source] = []

        for i in range(0, len(sources_data), BATCH_SIZE):
            batch = sources_data[i:i + BATCH_SIZE]
            claims, sources = self._extract_batch(batch, str(step.id))
            all_claims.extend(claims)
            all_sources.extend(sources)

        logger.info(
            "DeepDiveAgent complete",
            extra={"step_id": step.id, "claims": len(all_claims), "sources": len(all_sources)},
        )

        return self._emit_facts(step, [*all_claims, *all_sources])

    def _get_source_urls_for_task(self, task_id: str) -> list[str]:
        import sqlite3
        try:
            from argus.shared.config import settings
            conn = sqlite3.connect(settings.sqlite_path)
            rows = conn.execute(
                "SELECT url FROM sources WHERE task_id = ? ORDER BY rowid",
                (task_id,),
            ).fetchall()
            conn.close()
            return [r[0] for r in rows]
        except sqlite3.Error as exc:
            logger.warning("Failed to query sources for deep-dive", extra={"error": str(exc)})
            return []

    def _extract_batch(
        self,
        batch: list[dict[str, str]],
        task_id: str,
    ) -> tuple[list[Claim], list[Source]]:
        prompt = _build_extraction_prompt(batch)
        sources_list: list[Source] = []

        for src in batch:
            sources_list.append(Source(
                url=src["url"],
                title=src.get("title", ""),
                credibility_score=0.5,
            ))

        try:
            response_text, provider, cost = self._get_router().complete(
                task_type="deep_dive",
                prompt=prompt,
            )
            self._record_cost(cost, category="llm")
        except RuntimeError:
            logger.warning("Batch extraction failed, falling back to single-source")
            return self._extract_single(batch, task_id)

        from argus.services.agents._parse import extract_json_array

        try:
            raw_claims: list[dict[str, Any]] = extract_json_array(response_text)
            if isinstance(raw_claims, dict):
                raw_claims = raw_claims.get("claims", [raw_claims])
            claims = [
                Claim(
                    statement=c.get("statement", ""),
                    confidence={"high": 0.9, "medium": 0.6, "low": 0.3}.get(
                        c.get("confidence", "medium"), 0.5
                    ),
                    source_urls=[src["url"] for src in batch],
                    entity_name=c.get("entity_name"),
                    attribute=c.get("attribute"),
                )
                for c in raw_claims
                if c.get("statement")
            ]
            return claims, sources_list
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning("Failed to parse batch extraction", extra={"error": str(exc)})
            return self._extract_single(batch, task_id)

    def _extract_single(
        self,
        batch: list[dict[str, str]],
        _task_id: str,
    ) -> tuple[list[Claim], list[Source]]:
        all_claims: list[Claim] = []
        all_sources: list[Source] = []

        for src in batch:
            all_sources.append(Source(
                url=src["url"],
                title=src.get("title", ""),
                credibility_score=0.5,
            ))

            single_prompt = (
                f"Extract factual claims from this source.\n"
                f"URL: {src['url']}\n"
                f"Content:\n{src['content'][:2000]}\n\n"
                f"Return a JSON list of objects with keys: statement, entity_name, attribute."
            )

            try:
                text, provider, cost = self._get_router().complete(
                    task_type="deep_dive",
                    prompt=single_prompt,
                )
                self._record_cost(cost, category="llm")

                from argus.services.agents._parse import extract_json_array

                raw = extract_json_array(text)
                if isinstance(raw, dict):
                    raw = raw.get("claims", [raw])
                for c in raw:
                    if c.get("statement"):
                        all_claims.append(Claim(
                            statement=c["statement"],
                            confidence=0.5,
                            source_urls=[src["url"]],
                            entity_name=c.get("entity_name"),
                            attribute=c.get("attribute"),
                        ))
            except (RuntimeError, json.JSONDecodeError, TypeError):
                logger.warning("Single extraction failed", extra={"url": src["url"]})

        return all_claims, all_sources
