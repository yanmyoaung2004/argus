from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest

from argus.shared.idempotency import IdempotencyChecker


@pytest.fixture
def temp_db_path(tmp_path: pytest.TempPathFactory) -> Generator[str, None, None]:
    db_path = str(tmp_path / "idempotency.db")
    yield db_path


@pytest.fixture
def idempotency_checker(temp_db_path: str) -> Generator[IdempotencyChecker, None, None]:
    checker = IdempotencyChecker(db_path=temp_db_path)
    yield checker
    checker.close()


@pytest.fixture
def mock_redis() -> Generator[MagicMock, None, None]:
    redis_mock = MagicMock()
    redis_mock.xadd.return_value = b"mock-stream-id"
    redis_mock.xreadgroup.return_value = []
    yield redis_mock


@pytest.fixture
def sample_query() -> str:
    return "Top 10 YC companies by valuation in 2024"
