from __future__ import annotations

from pathlib import Path


def test_operator_status_reuses_shared_operator_task_state_helpers() -> None:
    source = Path("app/ui/operator_status.py").read_text()

    assert "from app.ui.operator_task_state import (" in source
    assert "def _latest_task(" not in source
    assert "def _task_successful(" not in source
    assert "def _task_running(" not in source
    assert "def _task_failed(" not in source
    assert "def _recent_failures(" not in source
