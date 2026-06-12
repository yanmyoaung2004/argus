from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from uuid import uuid7  # type: ignore[attr-defined]

from argus.shared.config import settings


def generate_idempotency_key() -> str:
    return str(uuid7())


class IdempotencyChecker:
    """SQLite-backed idempotency check.

    Stores processed idempotency keys with a TTL and auto-cleanup on insert.
    Thread-safe via per-thread connections + write lock.
    Uses UUID v7 for time-ordered keys (reduces index fragmentation).
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or settings.sqlite_path
        self._lock = threading.Lock()
        self._local: threading.local = threading.local()

    def _get_conn(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        self._ensure_table(conn)
        self._local.conn = conn
        return conn

    def _ensure_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS processed_keys ("
            "  key_hash TEXT PRIMARY KEY,"
            "  created_at REAL NOT NULL,"
            "  ttl_seconds REAL NOT NULL DEFAULT 86400"
            ") WITHOUT ROWID"
        )
        conn.commit()

    def is_processed(self, key: str) -> bool:
        key_hash = self._hash(key)
        conn = self._get_conn()
        row = conn.execute(
            "SELECT created_at, ttl_seconds FROM processed_keys WHERE key_hash = ?", (key_hash,)
        ).fetchone()
        if row is None:
            return False
        created_at, ttl = row
        if time.time() - float(created_at) >= ttl:
            with self._lock:
                conn.execute("DELETE FROM processed_keys WHERE key_hash = ?", (key_hash,))
                conn.commit()
            return False
        return True

    def mark_processed(self, key: str, ttl_seconds: float = 86400.0) -> None:
        key_hash = self._hash(key)
        now = time.time()
        with self._lock:
            conn = self._get_conn()
            stmt = (
                "INSERT OR REPLACE INTO processed_keys (key_hash, created_at, ttl_seconds)"
                " VALUES (?, ?, ?)"
            )
            conn.execute(stmt, (key_hash, now, ttl_seconds))
            conn.commit()

    def cleanup_expired(self) -> int:
        now = time.time()
        with self._lock:
            conn = self._get_conn()
            cursor = conn.execute(
                "DELETE FROM processed_keys WHERE created_at + ttl_seconds < ?", (now,)
            )
            conn.commit()
            return cursor.rowcount

    def close(self) -> None:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    @staticmethod
    def _hash(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()
