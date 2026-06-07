from __future__ import annotations

from collections.abc import Generator

import pytest

from argus.services.memory.checkpoints import CheckpointManager


@pytest.fixture
def cp_manager(tmp_path: pytest.TempPathFactory) -> Generator[CheckpointManager, None, None]:
    db_path = str(tmp_path / "checkpoints.db")
    mgr = CheckpointManager(db_path=db_path)
    yield mgr


class TestCheckpointManager:
    def test_initial_state_empty(self, cp_manager: CheckpointManager) -> None:
        assert cp_manager.get_completed_steps("task-1") == set()

    def test_save_and_retrieve_checkpoint(self, cp_manager: CheckpointManager) -> None:
        cp_manager.save_checkpoint("task-1", 1, "completed", {"result": "ok"})
        result = cp_manager.get_checkpoint("task-1", 1)
        assert result is not None
        assert result["status"] == "completed"
        assert result["data"]["result"] == "ok"

    def test_list_completed_steps(self, cp_manager: CheckpointManager) -> None:
        cp_manager.save_checkpoint("task-1", 1, "completed")
        cp_manager.save_checkpoint("task-1", 2, "completed")
        cp_manager.save_checkpoint("task-1", 3, "failed")
        completed = cp_manager.get_completed_steps("task-1")
        assert completed == {1, 2}

    def test_not_found_returns_none(self, cp_manager: CheckpointManager) -> None:
        assert cp_manager.get_checkpoint("ghost-task", 99) is None

    def test_overwrite_existing(self, cp_manager: CheckpointManager) -> None:
        cp_manager.save_checkpoint("task-1", 1, "running")
        cp_manager.save_checkpoint("task-1", 1, "completed")
        result = cp_manager.get_checkpoint("task-1", 1)
        assert result is not None
        assert result["status"] == "completed"

    def test_clear_task(self, cp_manager: CheckpointManager) -> None:
        cp_manager.save_checkpoint("task-1", 1, "completed")
        cp_manager.save_checkpoint("task-1", 2, "completed")
        cp_manager.clear_task("task-1")
        assert cp_manager.get_completed_steps("task-1") == set()

    def test_multiple_tasks_isolated(self, cp_manager: CheckpointManager) -> None:
        cp_manager.save_checkpoint("task-a", 1, "completed")
        cp_manager.save_checkpoint("task-b", 1, "completed")
        assert cp_manager.get_completed_steps("task-a") == {1}
        assert cp_manager.get_completed_steps("task-b") == {1}

    def test_empty_data_defaults(self, cp_manager: CheckpointManager) -> None:
        cp_manager.save_checkpoint("task-1", 1, "completed")
        result = cp_manager.get_checkpoint("task-1", 1)
        assert result is not None
        assert result["data"] == {}

    def test_data_with_none(self, cp_manager: CheckpointManager) -> None:
        cp_manager.save_checkpoint("task-1", 1, "completed", data={"progress": 0.5})
        result = cp_manager.get_checkpoint("task-1", 1)
        assert result is not None
        assert result["data"]["progress"] == 0.5

    def test_round_trip_preserves_types(self, cp_manager: CheckpointManager) -> None:
        data = {"count": 42, "items": ["a", "b"], "nested": {"x": 1.5}}
        cp_manager.save_checkpoint("task-1", 1, "completed", data=data)
        result = cp_manager.get_checkpoint("task-1", 1)
        assert result is not None
        assert result["data"] == data
