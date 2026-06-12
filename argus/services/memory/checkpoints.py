from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any


class CheckpointManager:
    def __init__(self, db_path: str | None = None) -> None:
        from argus.shared.config import settings as _s
        self._db_path = db_path or _s.sqlite_path
        self._local: threading.local = threading.local()

    def _get_db(self) -> Any:  # noqa: ANN401
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS checkpoints (
                task_id TEXT NOT NULL,
                step_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                data TEXT DEFAULT '{}',
                updated_at REAL NOT NULL,
                PRIMARY KEY (task_id, step_id)
            )"""
        )
        conn.commit()
        self._local.conn = conn
        return conn

    def save_checkpoint(
        self, task_id: str, step_id: int, status: str, data: dict[str, Any] | None = None
    ) -> None:
        conn: sqlite3.Connection = self._get_db()
        conn.execute(
            "INSERT OR REPLACE INTO checkpoints (task_id, step_id, status, data, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (task_id, step_id, status, json.dumps(data or {}), time.time()),
        )
        conn.commit()

    def get_completed_steps(self, task_id: str) -> set[int]:
        conn: sqlite3.Connection = self._get_db()
        cursor = conn.execute(
            "SELECT step_id FROM checkpoints WHERE task_id = ? AND status = 'completed'",
            (task_id,),
        )
        return {row[0] for row in cursor.fetchall()}

    def get_checkpoint(self, task_id: str, step_id: int) -> dict[str, Any] | None:
        conn: sqlite3.Connection = self._get_db()
        cursor = conn.execute(
            "SELECT status, data FROM checkpoints WHERE task_id = ? AND step_id = ?",
            (task_id, step_id),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {"status": row[0], "data": json.loads(row[1])}

    def clear_task(self, task_id: str) -> None:
        conn: sqlite3.Connection = self._get_db()
        conn.execute("DELETE FROM checkpoints WHERE task_id = ?", (task_id,))
        conn.commit()
