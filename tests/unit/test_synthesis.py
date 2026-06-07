from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from argus.services.agents.synthesis import SynthesisAgent
from argus.services.knowledge_graph.schema import init_db


@pytest.fixture
def agent() -> SynthesisAgent:
    return SynthesisAgent(db_path=":memory:")


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = init_db(":memory:")
    conn.execute(
        "INSERT INTO entities (id, name, type, task_id) VALUES (1, 'OpenAI', 'company', 'task-1')"
    )
    conn.execute(
        "INSERT INTO entities (id, name, type, task_id) VALUES (2, 'Anthropic', 'company', 'task-1')"
    )
    conn.commit()
    return conn


class TestFindMatch:
    def test_exact_match(self, agent: SynthesisAgent, db: sqlite3.Connection) -> None:
        from argus.shared.models import Entity
        entity = Entity(name="OpenAI", type="company")
        match = agent._find_match(db, entity)
        assert match is not None
        assert match["id"] == 1
        assert match["similarity"] >= 0.85

    def test_fuzzy_match(self, agent: SynthesisAgent, db: sqlite3.Connection) -> None:
        from argus.shared.models import Entity
        entity = Entity(name="OpenAI Inc.", type="company")
        match = agent._find_match(db, entity)
        assert match is not None
        assert match["similarity"] >= 0.70

    def test_no_match(self, agent: SynthesisAgent, db: sqlite3.Connection) -> None:
        from argus.shared.models import Entity
        entity = Entity(name="Google", type="company")
        match = agent._find_match(db, entity)
        assert match is None

    def test_best_match_selected(self, agent: SynthesisAgent, db: sqlite3.Connection) -> None:
        from argus.shared.models import Entity
        entity = Entity(name="OpenAI", type="company")
        match = agent._find_match(db, entity)
        assert match is not None
        assert match["name"] == "OpenAI"


class TestMergeEntity:
    def test_merges_attributes(self, agent: SynthesisAgent, db: sqlite3.Connection) -> None:
        from argus.shared.models import Entity
        entity = Entity(name="OpenAI", type="company", description="AI company", confidence=0.9)
        agent._merge_entity(db, 1, entity, "task-2")
        row = db.execute("SELECT name, confidence, description FROM entities WHERE id = 1").fetchone()
        assert row is not None
        assert row[1] == 0.9
        assert row[2] == "AI company"

    def test_merge_max_confidence(self, agent: SynthesisAgent, db: sqlite3.Connection) -> None:
        from argus.shared.models import Entity
        entity = Entity(name="OpenAI", type="company", confidence=0.3)
        agent._merge_entity(db, 1, entity, "task-2")
        row = db.execute("SELECT confidence FROM entities WHERE id = 1").fetchone()
        assert row is not None
        assert row[0] == 0.5


class TestInsertEntity:
    def test_inserts_new_entity(self, agent: SynthesisAgent, db: sqlite3.Connection) -> None:
        from argus.shared.models import Entity
        entity = Entity(name="Google", type="company", description="Search giant")
        agent._insert_entity(db, entity, "task-2")
        row = db.execute(
            "SELECT name, type, description FROM entities WHERE name = 'Google'"
        ).fetchone()
        assert row is not None
        assert row[0] == "Google"
        assert row[2] == "Search giant"


class TestAskLLM:
    def test_high_similarity_returns_true(self, agent: SynthesisAgent) -> None:
        assert agent._ask_llm("OpenAI", "OpenAI") is True

    def test_low_similarity_with_mock(self, agent: SynthesisAgent) -> None:
        with patch.object(agent, "_router") as mock_router:
            mock_router.complete.return_value = ("yes", "ollama", 0.0)
            assert agent._ask_llm("OpenAI Inc.", "OpenAI") is True

    def test_llm_says_no(self, agent: SynthesisAgent) -> None:
        with patch.object(agent, "_router") as mock_router:
            mock_router.complete.return_value = ("no", "ollama", 0.0)
            assert agent._ask_llm("Apple Inc.", "Apple Fruit") is False


class TestEnsureRelatedEdges:
    def test_adds_edge_for_cooccurring_entities(self, db: sqlite3.Connection) -> None:
        conn = db
        conn.execute(
            "INSERT INTO claims (id, statement, entity_id, task_id) VALUES "
            "(1, 'Claim about OpenAI', 1, 'task-1'),"
            "(2, 'Claim about Anthropic', 2, 'task-1'),"
            "(3, 'Another about OpenAI', 1, 'task-1'),"
            "(4, 'Another about Anthropic', 2, 'task-1')"
        )
        conn.commit()

        agent = SynthesisAgent(db_path=":memory:")
        agent._ensure_related_edges(conn)

        edges = conn.execute(
            "SELECT source_id, target_id, relation_type FROM edges"
        ).fetchall()
        assert len(edges) == 1
        assert edges[0][2] == "RELATED_TO"

    def test_skips_duplicate_edge(self, db: sqlite3.Connection) -> None:
        conn = db
        conn.execute(
            "INSERT INTO claims (id, statement, entity_id, task_id) VALUES "
            "(1, 'Claim about OpenAI', 1, 'task-1'),"
            "(2, 'Claim about Anthropic', 2, 'task-1')"
        )
        conn.execute(
            "INSERT INTO edges (source_id, target_id, relation_type, weight, task_id) "
            "VALUES (1, 2, 'RELATED_TO', 0.5, 'task-1')"
        )
        conn.commit()

        agent = SynthesisAgent(db_path=":memory:")
        agent._ensure_related_edges(conn)

        count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()
        assert count is not None
        assert count[0] == 1


class TestProcessFactItem:
    def test_processes_entity_fact(self, agent: SynthesisAgent) -> None:
        import os
        import sqlite3
        import tempfile
        db_path = tempfile.mktemp(suffix=".db")
        agent._db_path = db_path
        try:
            fact = {"type": "entity", "name": "Google", "task_id": "task-2"}
            agent._process_fact_item(fact)
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            row = conn.execute(
                "SELECT name FROM entities WHERE name = 'Google'"
            ).fetchone()
            conn.close()
            assert row is not None
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_skips_non_entity_fact(self, agent: SynthesisAgent) -> None:
        fact = {"type": "claim", "statement": "test"}
        agent._process_fact_item(fact)  # should not raise

    def test_skips_unknown_type(self, agent: SynthesisAgent) -> None:
        fact = {"name": "something"}  # has name but no type field
        agent._process_fact_item(fact)  # this has "name" so it would be detected as entity type
        # Let's test a fact without name at all
        fact2 = {"statement": "just a claim"}
        agent._process_fact_item(fact2)  # should not raise
