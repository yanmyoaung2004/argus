from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from argus.services.agents.base import BaseAgent
from argus.shared.models import AgentType, Fact, TaskStep

logger = logging.getLogger(__name__)


class VerificationAgent(BaseAgent):
    def __init__(
        self,
        router: Any = None,
        idempotency: Any = None,
        cost_tracker: Any = None,
    ) -> None:
        super().__init__(
            AgentType.VERIFICATION,
            router=router,
            idempotency=idempotency,
            cost_tracker=cost_tracker,
        )

    async def run(self, step: TaskStep) -> list[Fact]:
        logger.info("VerificationAgent running", extra={"step_id": step.id, "goal": step.goal})

        claims = self._get_claims_for_task(step.task_id)
        if not claims:
            import time
            delays = [5, 10, 20, 40, 60]
            for attempt, delay in enumerate(delays, start=1):
                logger.info(
                    "Waiting for claims to appear in KG",
                    extra={"step_id": step.id, "attempt": attempt, "wait_seconds": delay},
                )
                time.sleep(delay)
                claims = self._get_claims_for_task(step.task_id)
                if claims:
                    logger.info(
                        "Claims found after waiting",
                        extra={"step_id": step.id, "attempt": attempt, "count": len(claims)},
                    )
                    break
            if not claims:
                logger.info("No claims to verify after waiting", extra={"step_id": step.id})
                return []

        grouped: dict[str, list[dict[str, Any]]] = {}
        for claim in claims:
            entity_name = claim.get("entity_name", "unknown")
            if entity_name not in grouped:
                grouped[entity_name] = []
            grouped[entity_name].append(claim)

        conflict_facts: list[dict[str, Any]] = []

        for _entity_name, entity_claims in grouped.items():
            if len(entity_claims) < 2:
                continue

            for i in range(len(entity_claims)):
                for j in range(i + 1, len(entity_claims)):
                    a = entity_claims[i]
                    b = entity_claims[j]

                    if a.get("attribute") != b.get("attribute"):
                        continue

                    result = self._check_conflict(a, b)
                    if result is not None:
                        conflict_facts.append(result)

        if not conflict_facts:
            return []

        return self._emit_facts(step, conflict_facts)

    def _get_claims_for_task(self, task_id: str) -> list[dict[str, Any]]:
        try:
            from argus.shared.config import settings
            conn = sqlite3.connect(settings.sqlite_path)
            rows = conn.execute(
                "SELECT statement, confidence, source_urls, entity_name, attribute "
                "FROM claims WHERE task_id = ? ORDER BY rowid",
                (task_id,),
            ).fetchall()
            conn.close()
            results: list[dict[str, Any]] = []
            for row in rows:
                source_urls_raw = row[2]
                source_urls: list[str] = []
                if isinstance(source_urls_raw, str):
                    try:
                        source_urls = json.loads(source_urls_raw)
                    except (json.JSONDecodeError, TypeError):
                        source_urls = []
                results.append({
                    "statement": row[0],
                    "confidence": row[1],
                    "source_urls": source_urls,
                    "entity_name": row[3],
                    "attribute": row[4],
                })
            return results
        except sqlite3.Error as exc:
            logger.warning("Failed to query claims for verification", extra={"error": str(exc)})
            return []

    def _check_conflict(
        self,
        claim_a: dict[str, Any],
        claim_b: dict[str, Any],
    ) -> dict[str, Any] | None:
        prompt = (
            f"Determine if the following two claims are contradictory, "
            f"supportive, or unrelated. Return a JSON object with keys: "
            f"relationship (contradictory/supportive/unrelated), reason.\n\n"
            f"Claim A: {claim_a.get('statement', '')}\n"
            f"Source A: {claim_a.get('source_urls', [])}\n\n"
            f"Claim B: {claim_b.get('statement', '')}\n"
            f"Source B: {claim_b.get('source_urls', [])}"
        )

        try:
            text, provider, cost = self._router.complete(
                task_type="verification",
                prompt=prompt,
            )
            self._record_cost(cost, category="llm")

            from argus.services.agents._parse import extract_json_object
            result: dict[str, Any] = extract_json_object(text)
            relationship = result.get("relationship", "unrelated")
            reason = result.get("reason", "")

            return {
                "claim_a": claim_a.get("statement", ""),
                "claim_b": claim_b.get("statement", ""),
                "relationship": relationship,
                "reason": reason,
                "confidence_delta": -0.2 if relationship == "contradictory" else 0.1,
            }
        except (RuntimeError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("Conflict check failed", extra={"error": str(exc)})
            return None
