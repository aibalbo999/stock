from __future__ import annotations

from app.ui.operator_task_state import (
    latest_task_running,
    latest_task_successful,
    task_row_failed,
    task_summary_failures,
)


def test_latest_task_running_returns_pending_latest_task() -> None:
    task = latest_task_running(
        {"latest": {"task_id": "run-1", "status": "pending", "celery_status": "PENDING"}}
    )

    assert task == {"task_id": "run-1", "status": "pending", "celery_status": "PENDING"}


def test_latest_task_running_ignores_successful_or_failed_rows() -> None:
    assert latest_task_running({"latest": {"task_id": "done-1", "status": "success"}}) == {}
    assert latest_task_running({"latest": {"task_id": "fail-1", "status": "failed"}}) == {}


def test_task_summary_failures_merges_recent_failures_and_failed_recent_rows() -> None:
    failures = task_summary_failures(
        {
            "recent_failures": [
                {"task_id": "known-failure", "status": "failed", "error_category": "source"}
            ],
            "recent": [
                {"task_id": "known-failure", "status": "failed", "error_category": "source"},
                {"task_id": "new-failure", "celery_status": "FAILURE"},
                {"task_id": "ok-task", "status": "success"},
            ],
        }
    )

    assert [failure["task_id"] for failure in failures] == [
        "known-failure",
        "new-failure",
    ]


def test_task_row_state_helpers_normalize_operator_task_statuses() -> None:
    assert task_row_failed({"celery_status": "REVOKED"})
    assert latest_task_successful({"latest_task": {"task_id": "ok", "status": "completed"}})
