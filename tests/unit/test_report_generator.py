from __future__ import annotations

import sqlite3

import pytest

from argus.ui.report_generator import HTMLReportGenerator, MarkdownReportGenerator


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS entities ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL DEFAULT 'unknown', "
        "description TEXT, confidence REAL NOT NULL DEFAULT 0.5, attributes TEXT DEFAULT '{}', "
        "task_id TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')), "
        "updated_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS claims ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, statement TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 0.5, "
        "entity_id INTEGER REFERENCES entities(id), attribute TEXT, source_urls TEXT DEFAULT '[]', "
        "task_id TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sources ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL, title TEXT, content_hash TEXT, "
        "credibility_score REAL NOT NULL DEFAULT 0.5, task_id TEXT NOT NULL, "
        "fetched_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS edges ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, source_id INTEGER NOT NULL, target_id INTEGER NOT NULL, "
        "relation_type TEXT NOT NULL, weight REAL NOT NULL DEFAULT 1.0, "
        "task_id TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute(
        "INSERT INTO entities (id, name, type, confidence, task_id) VALUES "
        "(1, 'OpenAI', 'company', 0.9, 'task-1'),"
        "(2, 'Anthropic', 'company', 0.8, 'task-1')"
    )
    conn.execute(
        "INSERT INTO sources (id, url, title, credibility_score, task_id) VALUES "
        "(1, 'https://openai.com', 'OpenAI Website', 0.8, 'task-1')"
    )
    conn.execute(
        "INSERT INTO claims (id, statement, confidence, entity_id, source_urls, task_id) VALUES "
        "(1, 'OpenAI is a leading AI company', 0.9, 1, '[\"https://openai.com\"]', 'task-1'),"
        "(2, 'Anthropic develops safe AI', 0.7, 2, '[]', 'task-1')"
    )
    conn.execute(
        "INSERT INTO edges (id, source_id, target_id, relation_type, weight, task_id) VALUES "
        "(1, 1, 2, 'RELATED_TO', 0.8, 'task-1')"
    )
    conn.commit()
    return conn


class TestMarkdownReportGenerator:
    def test_generates_report(self, db: sqlite3.Connection) -> None:
        gen = MarkdownReportGenerator(db_path=":memory:")
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(gen, "_get_db", lambda: db)
            report = gen.generate("task-1")
        assert "# Research Report: task-1" in report
        assert "OpenAI" in report
        assert "Anthropic" in report
        assert "OpenAI is a leading AI company" in report

    def test_includes_cost_report(self, db: sqlite3.Connection) -> None:
        gen = MarkdownReportGenerator(db_path=":memory:")
        cost = {"total_cost": 0.12, "budget_limit": 0.50, "breakdown": {"llm": 0.10, "search": 0.02}}
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(gen, "_get_db", lambda: db)
            report = gen.generate("task-1", cost_report=cost)
        assert "Cost Breakdown" in report
        assert "$0.1200" in report

    def test_empty_report(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE entities (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, type TEXT, "
            "description TEXT, confidence REAL, attributes TEXT, task_id TEXT, "
            "created_at TEXT, updated_at TEXT)"
        )
        conn.execute(
            "CREATE TABLE claims (id INTEGER PRIMARY KEY AUTOINCREMENT, statement TEXT, confidence REAL, "
            "entity_id INTEGER, attribute TEXT, source_urls TEXT, task_id TEXT, created_at TEXT)"
        )
        conn.execute(
            "CREATE TABLE sources (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT, title TEXT, "
            "content_hash TEXT, credibility_score REAL, task_id TEXT, fetched_at TEXT)"
        )
        conn.commit()

        gen = MarkdownReportGenerator(db_path=":memory:")
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(gen, "_get_db", lambda: conn)
            report = gen.generate("empty-task")
        assert "# Research Report: empty-task" in report


class TestHTMLReportGenerator:
    def test_generates_html(self, db: sqlite3.Connection) -> None:
        gen = HTMLReportGenerator(db_path=":memory:")
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(gen, "_get_db", lambda: db)
            html = gen.generate("task-1")
        assert "<html" in html or "<!DOCTYPE html>" in html
        assert "OpenAI" in html
        assert "Research Report" in html

    def test_contains_graph_data(self, db: sqlite3.Connection) -> None:
        gen = HTMLReportGenerator(db_path=":memory:")
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(gen, "_get_db", lambda: db)
            html = gen.generate("task-1")
        assert "graphData" in html or "graph_data" in html
        assert "nodes" in html

    def test_with_cost_report(self, db: sqlite3.Connection) -> None:
        gen = HTMLReportGenerator(db_path=":memory:")
        cost = {"total_cost": 0.08, "budget_limit": 0.50, "breakdown": {"llm": 0.08}}
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(gen, "_get_db", lambda: db)
            html = gen.generate("task-1", cost_report=cost)
        assert "$0.0800" in html
