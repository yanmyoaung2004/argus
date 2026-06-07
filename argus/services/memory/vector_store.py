from __future__ import annotations

import json
import sqlite3
from typing import Any

import sqlite_vec

EMBEDDING_DIM = 384


def load_vec(conn: sqlite3.Connection) -> None:
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


def ensure_vec_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_entities "
        f"USING vec0(embedding float[{EMBEDDING_DIM}])"
    )


def ensure_claim_vec_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_claims "
        f"USING vec0(embedding float[{EMBEDDING_DIM}])"
    )


def ensure_all_tables(conn: sqlite3.Connection) -> None:
    ensure_vec_table(conn)
    ensure_claim_vec_table(conn)


def upsert_entity_embedding(
    conn: sqlite3.Connection,
    entity_id: int,
    embedding: list[float],
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO vec_entities(rowid, embedding) VALUES (?, ?)",
        (entity_id, json.dumps(embedding)),
    )
    conn.commit()


def upsert_claim_embedding(
    conn: sqlite3.Connection,
    claim_id: int,
    embedding: list[float],
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO vec_claims(rowid, embedding) VALUES (?, ?)",
        (claim_id, json.dumps(embedding)),
    )
    conn.commit()


def find_similar_entities(
    conn: sqlite3.Connection,
    embedding: list[float],
    k: int = 10,
) -> list[dict[str, Any]]:
    cursor = conn.execute(
        "SELECT rowid, distance FROM vec_entities WHERE embedding MATCH ? AND k = ?",
        (json.dumps(embedding), k),
    )
    return [
        {"entity_id": row[0], "distance": row[1]}
        for row in cursor.fetchall()
    ]


def find_similar_claims(
    conn: sqlite3.Connection,
    embedding: list[float],
    k: int = 10,
) -> list[dict[str, Any]]:
    cursor = conn.execute(
        "SELECT rowid, distance FROM vec_claims WHERE embedding MATCH ? AND k = ?",
        (json.dumps(embedding), k),
    )
    return [
        {"claim_id": row[0], "distance": row[1]}
        for row in cursor.fetchall()
    ]


def reindex_entity_embeddings(
    conn: sqlite3.Connection,
    embedding_fn: Any = None,
) -> int:
    rows = conn.execute("SELECT id, name, COALESCE(description, '') FROM entities").fetchall()
    if not rows:
        return 0

    count = 0
    for entity_id, name, description in rows:
        text = f"{name} {description}".strip()
        if not text:
            continue
        embedding = _mock_embedding(text) if embedding_fn is None else embedding_fn(text)
        upsert_entity_embedding(conn, entity_id, embedding)
        count += 1
    return count


def _mock_embedding(text: str) -> list[float]:
    dim = EMBEDDING_DIM
    h = hash(text)
    return [((h >> (i % 31)) & 0xFF) / 255.0 for i in range(dim)]
