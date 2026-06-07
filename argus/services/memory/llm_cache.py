from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from typing import Any


class LLMCache:
    def __init__(self, db_path: str | None = None, ttl: int = 86400) -> None:
        from argus.shared.config import settings as _s
        self._db_path = db_path or _s.sqlite_path
        self._ttl = ttl or _s.llm_cache_ttl
        self._local: threading.local = threading.local()

    def _get_db(self) -> Any:  # noqa: ANN401
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute(
                """CREATE TABLE IF NOT EXISTS llm_cache (
                    prompt_hash TEXT PRIMARY KEY,
                    prompt TEXT NOT NULL,
                    response TEXT NOT NULL,
                    model TEXT NOT NULL,
                    created_at REAL NOT NULL
                )"""
            )
            self._local.conn = conn
        return conn

    def _hash_prompt(self, prompt: str, model: str) -> str:
        return hashlib.sha256(f"{model}:{prompt}".encode()).hexdigest()

    def get(self, prompt: str, model: str) -> str | None:
        conn: sqlite3.Connection = self._get_db()
        prompt_hash = self._hash_prompt(prompt, model)
        cursor = conn.execute(
            "SELECT response, created_at FROM llm_cache WHERE prompt_hash = ?",
            (prompt_hash,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        response_text: Any = row[0]
        created_at: Any = row[1]
        if time.time() - created_at > self._ttl:
            conn.execute("DELETE FROM llm_cache WHERE prompt_hash = ?", (prompt_hash,))
            conn.commit()
            return None

        return str(response_text) if response_text is not None else None

    def set(self, prompt: str, model: str, response: str) -> None:
        conn: sqlite3.Connection = self._get_db()
        prompt_hash = self._hash_prompt(prompt, model)
        conn.execute(
            """INSERT OR REPLACE INTO llm_cache (prompt_hash, prompt, response, model, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (prompt_hash, prompt[:1000], response, model, time.time()),
        )
        conn.commit()

    def clear_expired(self) -> int:
        conn: sqlite3.Connection = self._get_db()
        cutoff = time.time() - self._ttl
        cursor = conn.execute("DELETE FROM llm_cache WHERE created_at < ?", (cutoff,))
        conn.commit()
        return cursor.rowcount
