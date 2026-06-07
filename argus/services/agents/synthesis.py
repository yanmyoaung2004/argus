from __future__ import annotations

import json
import logging
import sqlite3
import time
from difflib import SequenceMatcher
from typing import Any

import redis as redis_lib

from argus.llm.router import CostAwareRouter
from argus.services.knowledge_graph.schema import init_db
from argus.services.tools.cost_tracker import CostTracker
from argus.shared.config import settings
from argus.shared.models import Entity

logger = logging.getLogger(__name__)


class SynthesisAgent:
    SIMILARITY_THRESHOLD_MERGE = 0.85
    SIMILARITY_THRESHOLD_LLM = 0.70
    EDGE_COOCCUR_THRESHOLD = 2

    def __init__(
        self,
        db_path: str | None = None,
        redis_client: redis_lib.Redis | None = None,
        router: CostAwareRouter | None = None,
        cost_tracker: CostTracker | None = None,
    ) -> None:
        self._db_path = db_path or settings.sqlite_path
        self._redis = redis_client
        self._router = router or CostAwareRouter()
        self._cost_tracker = cost_tracker
        self._running = False
        self._edge_check_counter = 0

    def _get_redis(self) -> redis_lib.Redis | None:
        if self._redis is None:
            try:
                self._redis = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
            except Exception:
                return None
        return self._redis

    def _get_db(self) -> sqlite3.Connection:
        return init_db(self._db_path)

    def start(self) -> None:
        self._running = True
        self._consume_loop()

    def stop(self) -> None:
        self._running = False

    def _consume_loop(self) -> None:
        r = self._get_redis()
        if r is None:
            logger.error("No Redis available for synthesis agent")
            return

        last_id = "0"
        while self._running:
            try:
                raw: list[Any] = list(r.xread({"facts": last_id}, count=10, block=2000))
            except Exception:
                time.sleep(1)
                continue

            for entry in raw:
                if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                    continue
                messages = entry[1]
                for msg_entry in messages:
                    if not isinstance(msg_entry, (list, tuple)) or len(msg_entry) < 2:
                        continue
                    msg_id, msg_data = msg_entry
                    last_id = msg_id
                    if isinstance(msg_data, dict):
                        self._process_fact(msg_data)

            self._edge_check_counter += 1
            if self._edge_check_counter >= 50:
                self._edge_check_counter = 0
                conn = self._get_db()
                try:
                    self._ensure_related_edges(conn)
                finally:
                    conn.close()

    def _process_fact(self, msg_data: dict[bytes, bytes]) -> None:
        try:
            raw_data = msg_data.get(b"data", b"{}")
            data = json.loads(raw_data) if isinstance(raw_data, (bytes, str)) else {}
            facts = data.get("facts", [data]) if isinstance(data, dict) else []
            for fact in facts:
                if isinstance(fact, dict):
                    self._process_fact_item(fact)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Invalid fact in synthesis", extra={"error": str(exc)})

    def _process_fact_item(self, fact: dict[str, Any]) -> None:
        fact_type = fact.get("type", fact.get("__type__", ""))
        if not fact_type and "name" in fact:
            fact_type = "entity"
        if fact_type != "entity":
            return

        entity = Entity(
            name=fact.get("name", "unknown"),
            type=fact.get("type", "unknown"),
            description=fact.get("description"),
            confidence=fact.get("confidence", 0.5),
            attributes=fact.get("attributes", {}),
        )
        task_id = fact.get("task_id", "unknown")

        conn = self._get_db()
        try:
            match = self._find_match(conn, entity)
            if match is None:
                self._insert_entity(conn, entity, task_id)
            elif match["similarity"] >= self.SIMILARITY_THRESHOLD_MERGE:
                self._merge_entity(conn, match["id"], entity, task_id)
            elif match["similarity"] >= self.SIMILARITY_THRESHOLD_LLM:
                should_merge = self._ask_llm(entity.name, match["name"])
                if should_merge:
                    self._merge_entity(conn, match["id"], entity, task_id)
                else:
                    self._insert_entity(conn, entity, task_id)
            else:
                self._insert_entity(conn, entity, task_id)
        finally:
            conn.close()

    def _find_match(self, conn: sqlite3.Connection, entity: Entity) -> dict[str, Any] | None:
        candidates = conn.execute(
            "SELECT id, name FROM entities ORDER BY id"
        ).fetchall()

        best: dict[str, Any] | None = None
        best_score = 0.0

        for row in candidates:
            score = SequenceMatcher(None, entity.name.lower(), row[1].lower()).ratio()
            if score > best_score and score >= self.SIMILARITY_THRESHOLD_LLM:
                best_score = score
                best = {"id": row[0], "name": row[1], "similarity": score}

        return best

    def _merge_entity(self, conn: sqlite3.Connection, target_id: int, entity: Entity, task_id: str) -> None:
        existing = conn.execute(
            "SELECT name, type, description, confidence, attributes FROM entities WHERE id = ?",
            (target_id,),
        ).fetchone()
        if existing is None:
            return

        existing_attrs: dict[str, Any] = {}
        try:
            existing_attrs = json.loads(existing[4]) if existing[4] else {}
        except (json.JSONDecodeError, TypeError):
            existing_attrs = {}

        merged_attrs = {**existing_attrs, **entity.attributes}
        merged_confidence = max(existing[3], entity.confidence)
        merged_description = entity.description or existing[2]

        conn.execute(
            "UPDATE entities SET type = CASE WHEN ? != 'unknown' THEN ? ELSE ? END, "
            "description = ?, confidence = ?, "
            "attributes = ?, updated_at = datetime('now') WHERE id = ?",
            (
                entity.type, entity.type, existing[1],
                merged_description,
                merged_confidence,
                json.dumps(merged_attrs),
                target_id,
            ),
        )
        conn.commit()
        logger.info(
            "Merged entity",
            extra={"target_id": target_id, "source_name": entity.name, "task_id": task_id},
        )

    def _insert_entity(self, conn: sqlite3.Connection, entity: Entity, task_id: str) -> None:
        conn.execute(
            "INSERT INTO entities (name, type, description, confidence, attributes, task_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                entity.name,
                entity.type,
                entity.description,
                entity.confidence,
                json.dumps(entity.attributes),
                task_id,
            ),
        )
        conn.commit()

    def _ask_llm(self, name_a: str, name_b: str) -> bool:
        score = SequenceMatcher(None, name_a.lower(), name_b.lower()).ratio()
        if score >= self.SIMILARITY_THRESHOLD_MERGE:
            return True
        try:
            prompt = (
                f"Do these two entity names refer to the same real-world entity?\n"
                f"Entity A: '{name_a}'\nEntity B: '{name_b}'\n"
                f"Answer ONLY with 'yes' or 'no'."
            )
            text, provider, cost = self._router.complete(
                task_type="synthesis",
                prompt=prompt,
            )
            if self._cost_tracker is not None:
                self._cost_tracker.record_cost(cost, category="llm")
            return text.strip().lower().startswith("yes")
        except (RuntimeError, Exception):
            return score >= (self.SIMILARITY_THRESHOLD_MERGE + self.SIMILARITY_THRESHOLD_LLM) / 2

    def _ensure_related_edges(self, conn: sqlite3.Connection) -> None:
        cursor = conn.execute(
            """SELECT c1.entity_id AS a, c2.entity_id AS b, COUNT(*) AS cooccur
               FROM claims c1
               JOIN claims c2 ON c1.task_id = c2.task_id AND c1.id < c2.id
               WHERE c1.entity_id IS NOT NULL AND c2.entity_id IS NOT NULL
                 AND c1.entity_id != c2.entity_id
               GROUP BY c1.entity_id, c2.entity_id
               HAVING cooccur >= ?""",
            (self.EDGE_COOCCUR_THRESHOLD,),
        )
        added = 0
        for row in cursor.fetchall():
            a_id, b_id, cooccur = row
            existing = conn.execute(
                "SELECT id FROM edges WHERE source_id = ? AND target_id = ? AND relation_type = 'RELATED_TO'",
                (a_id, b_id),
            ).fetchone()
            if existing is None:
                weight = min(cooccur / 10.0, 1.0)
                conn.execute(
                    "INSERT INTO edges (source_id, target_id, relation_type, weight, task_id) "
                    "VALUES (?, ?, 'RELATED_TO', ?, (SELECT task_id FROM entities WHERE id = ?))",
                    (a_id, b_id, weight, a_id),
                )
                added += 1
        if added:
            conn.commit()
            logger.info("Added RELATED_TO edges", extra={"count": added})
