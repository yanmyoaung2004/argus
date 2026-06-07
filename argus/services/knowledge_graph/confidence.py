from __future__ import annotations

import json
import sqlite3
from typing import Any


def calculate_confidence(
    source_count: int = 0,
    credibility_scores: list[float] | None = None,
    latest_source_age_days: float | None = None,
    has_conflicts: bool = False,
) -> float:
    base = 0.5
    source_boost = min(0.3, source_count * 0.1)
    creds = credibility_scores or []
    credibility_boost = (sum(creds) / len(creds) * 0.2) if creds else 0.0
    recency_boost = 0.1 if (latest_source_age_days is not None and latest_source_age_days < 30) else 0.0
    conflict_penalty = -0.3 if has_conflicts else 0.0
    return min(1.0, max(0.0, base + source_boost + credibility_boost + recency_boost + conflict_penalty))


def update_claim_confidence(conn: sqlite3.Connection, claim_id: int) -> float:
    row = conn.execute(
        """SELECT c.id, c.statement, c.source_urls, c.entity_id
           FROM claims c WHERE c.id = ?""",
        (claim_id,),
    ).fetchone()
    if row is None:
        return 0.0

    source_urls: list[str] = []
    try:
        source_urls = json.loads(row[2]) if isinstance(row[2], str) else (row[2] or [])
    except (json.JSONDecodeError, TypeError):
        source_urls = []

    credibility_scores: list[float] = []
    for url in source_urls:
        src = conn.execute(
            "SELECT credibility_score FROM sources WHERE url = ? LIMIT 1",
            (url,),
        ).fetchone()
        if src is not None:
            credibility_scores.append(src[0])

    entity_id = row[3]
    has_conflicts = _claim_has_conflicts(conn, claim_id, entity_id)

    confidence = calculate_confidence(
        source_count=len(source_urls),
        credibility_scores=credibility_scores or None,
        has_conflicts=has_conflicts,
    )

    conn.execute("UPDATE claims SET confidence = ? WHERE id = ?", (confidence, claim_id))
    conn.commit()
    return confidence


def update_all_claim_confidences(conn: sqlite3.Connection, task_id: str | None = None) -> dict[int, float]:
    if task_id:
        rows = conn.execute("SELECT id FROM claims WHERE task_id = ?", (task_id,)).fetchall()
    else:
        rows = conn.execute("SELECT id FROM claims").fetchall()

    results: dict[int, float] = {}
    for (claim_id,) in rows:
        conf = update_claim_confidence(conn, claim_id)
        results[claim_id] = conf
    return results


def _claim_has_conflicts(conn: sqlite3.Connection, claim_id: int, entity_id: int | None) -> bool:
    if entity_id is None:
        return False
    row = conn.execute(
        """SELECT COUNT(*) FROM claims c1
           JOIN claims c2 ON c1.entity_id = c2.entity_id
                         AND (c1.attribute = c2.attribute OR (c1.attribute IS NULL AND c2.attribute IS NULL))
                         AND c1.id != c2.id
           WHERE c1.id = ?
             AND c2.confidence >= 0.5
             AND c1.entity_id = ?""",
        (claim_id, entity_id),
    ).fetchone()
    return (row[0] if row else 0) > 0


def get_confidence_report(conn: sqlite3.Connection, task_id: str) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT confidence FROM claims WHERE task_id = ?",
        (task_id,),
    ).fetchall()

    if not rows:
        return {"avg": 0.0, "min": 0.0, "max": 0.0, "count": 0}

    scores = [r[0] for r in rows]
    return {
        "avg": sum(scores) / len(scores),
        "min": min(scores),
        "max": max(scores),
        "count": len(scores),
    }
