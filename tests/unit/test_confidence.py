from __future__ import annotations

import sqlite3

import pytest

from argus.services.knowledge_graph.confidence import (
    _claim_has_conflicts,
    calculate_confidence,
    get_confidence_report,
    update_all_claim_confidences,
    update_claim_confidence,
)
from argus.services.knowledge_graph.schema import init_db


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = init_db(":memory:")
    conn.execute(
        "INSERT INTO entities (id, name, type, task_id) VALUES (1, 'OpenAI', 'company', 'task-1')"
    )
    conn.execute(
        "INSERT INTO sources (id, url, title, credibility_score, task_id) VALUES "
        "(1, 'https://a.com', 'Source A', 0.9, 'task-1'),"
        "(2, 'https://b.com', 'Source B', 0.5, 'task-1')"
    )
    conn.execute(
        "INSERT INTO claims (id, statement, confidence, entity_id, source_urls, task_id) VALUES "
        "(1, 'OpenAI has 1000 employees', 0.5, 1, '[\"https://a.com\"]', 'task-1'),"
        "(2, 'OpenAI has 5000 employees', 0.5, 1, '[\"https://b.com\"]', 'task-1')"
    )
    conn.commit()
    return conn


class TestCalculateConfidence:
    def test_base_confidence(self) -> None:
        assert calculate_confidence() == 0.5

    def test_source_boost_increases(self) -> None:
        c = calculate_confidence(source_count=3)
        assert c == pytest.approx(0.8, rel=1e-2)

    def test_source_boost_capped(self) -> None:
        c = calculate_confidence(source_count=10)
        assert c == pytest.approx(0.8, rel=1e-2)

    def test_credibility_boost(self) -> None:
        c = calculate_confidence(source_count=1, credibility_scores=[0.9])
        assert c == pytest.approx(0.78, rel=1e-2)

    def test_recency_boost(self) -> None:
        c = calculate_confidence(latest_source_age_days=10)
        assert c == pytest.approx(0.6, rel=1e-2)

    def test_no_recency_boost_old_source(self) -> None:
        c = calculate_confidence(latest_source_age_days=60)
        assert c == 0.5

    def test_conflict_penalty(self) -> None:
        c = calculate_confidence(has_conflicts=True)
        assert c == pytest.approx(0.2, rel=1e-2)

    def test_max_confidence(self) -> None:
        c = calculate_confidence(
            source_count=5, credibility_scores=[0.9, 1.0], latest_source_age_days=5,
        )
        assert c == 1.0

    def test_min_confidence(self) -> None:
        c = calculate_confidence(has_conflicts=True)
        assert c == 0.2

    def test_all_factors_together(self) -> None:
        c = calculate_confidence(
            source_count=3,
            credibility_scores=[0.8, 0.9],
            latest_source_age_days=10,
            has_conflicts=True,
        )
        expected = 0.5 + 0.3 + ((0.8 + 0.9) / 2 * 0.2) + 0.1 - 0.3
        assert c == pytest.approx(expected, rel=1e-2)


class TestUpdateClaimConfidence:
    def test_updates_confidence_in_db(self, db: sqlite3.Connection) -> None:
        new_conf = update_claim_confidence(db, 1)
        row = db.execute("SELECT confidence FROM claims WHERE id = 1").fetchone()
        assert row is not None
        assert row[0] == new_conf

    def test_unknown_claim_returns_zero(self, db: sqlite3.Connection) -> None:
        assert update_claim_confidence(db, 999) == 0.0

    def test_missing_source_uses_default(self, db: sqlite3.Connection) -> None:
        conn = init_db(":memory:")
        conn.execute(
            "INSERT INTO entities (id, name, type, task_id) VALUES (1, 'Test', 'test', 't')"
        )
        conn.execute(
            "INSERT INTO claims (id, statement, confidence, entity_id, source_urls, task_id) "
            "VALUES (1, 'Test claim', 0.5, 1, '[\"https://unknown.com\"]', 't')"
        )
        conn.commit()
        conf = update_claim_confidence(conn, 1)
        assert conf == pytest.approx(0.6, rel=1e-2)


class TestUpdateAllClaimConfidences:
    def test_updates_all_claims(self, db: sqlite3.Connection) -> None:
        results = update_all_claim_confidences(db)
        assert len(results) == 2

    def test_updates_by_task_id(self, db: sqlite3.Connection) -> None:
        results = update_all_claim_confidences(db, task_id="task-1")
        assert len(results) == 2


class TestClaimHasConflicts:
    def test_detects_conflict(self, db: sqlite3.Connection) -> None:
        assert _claim_has_conflicts(db, 1, 1) is True

    def test_no_conflict_different_entity(self, db: sqlite3.Connection) -> None:
        conn = init_db(":memory:")
        conn.execute(
            "INSERT INTO entities (id, name, type, task_id) VALUES "
            "(1, 'A', 'test', 't'), (2, 'B', 'test', 't')"
        )
        conn.execute(
            "INSERT INTO claims (id, statement, entity_id, attribute, confidence, task_id) VALUES "
            "(1, 'Claim A', 1, 'attr', 0.8, 't'),"
            "(2, 'Claim B', 2, 'attr', 0.8, 't')"
        )
        conn.commit()
        assert _claim_has_conflicts(conn, 1, 1) is False


class TestGetConfidenceReport:
    def test_with_claims(self, db: sqlite3.Connection) -> None:
        report = get_confidence_report(db, "task-1")
        assert report["count"] == 2
        assert 0 <= report["avg"] <= 1
        assert 0 <= report["min"] <= report["max"] <= 1

    def test_no_claims(self, db: sqlite3.Connection) -> None:
        report = get_confidence_report(db, "nonexistent")
        assert report["count"] == 0
