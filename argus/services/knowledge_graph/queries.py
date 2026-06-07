from __future__ import annotations

import sqlite3
from typing import Any


def get_entity(conn: sqlite3.Connection, entity_id: int) -> dict[str, Any] | None:
    cursor = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row, strict=False))


def get_claims_for_entity(conn: sqlite3.Connection, entity_id: int) -> list[dict[str, Any]]:
    cursor = conn.execute(
        "SELECT * FROM claims WHERE entity_id = ? ORDER BY confidence DESC",
        (entity_id,),
    )
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]


def get_provenance_chain(conn: sqlite3.Connection, claim_id: int) -> list[dict[str, Any]]:
    query = """
    WITH RECURSIVE provenance AS (
        SELECT id, statement, entity_id, source_urls, task_id, created_at, 0 AS depth
        FROM claims WHERE id = ?
        UNION ALL
        SELECT e.id, e.name, e.id, '{}', e.task_id, e.created_at, p.depth + 1
        FROM provenance p
        JOIN entities e ON e.id = p.entity_id
        WHERE p.depth < 5
    )
    SELECT * FROM provenance ORDER BY depth
    """
    cursor = conn.execute(query, (claim_id,))
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]


def find_conflicts(conn: sqlite3.Connection, entity_id: int) -> list[dict[str, Any]]:
    query = """
    SELECT c1.id AS claim_a_id, c1.statement AS claim_a,
           c2.id AS claim_b_id, c2.statement AS claim_b,
           c1.attribute
    FROM claims c1
    JOIN claims c2 ON c1.entity_id = c2.entity_id
                  AND c1.attribute = c2.attribute
                  AND c1.id < c2.id
    WHERE c1.entity_id = ?
      AND c1.confidence >= 0.5
      AND c2.confidence >= 0.5
    """
    cursor = conn.execute(query, (entity_id,))
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]


def search_claims(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[dict[str, Any]]:
    cursor = conn.execute(
        """SELECT c.* FROM claims c
           JOIN claims_fts fts ON c.id = fts.rowid
           WHERE claims_fts MATCH ?
           LIMIT ?""",
        (query, limit),
    )
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
