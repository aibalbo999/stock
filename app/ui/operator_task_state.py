from __future__ import annotations

from typing import Any


def task_summary_failures(task_summary: dict | None) -> list[dict]:
    if not isinstance(task_summary, dict):
        return []
    failures = [row for row in task_summary.get("recent_failures") or [] if isinstance(row, dict)]
    seen = {task_failure_identity(row) for row in failures}
    for row in task_summary.get("recent") or []:
        if not isinstance(row, dict) or not task_row_failed(row):
            continue
        identity = task_failure_identity(row)
        if identity in seen:
            continue
        seen.add(identity)
        failures.append(row)
    return failures


def task_row_failed(row: dict) -> bool:
    status = _text(row.get("status")).casefold()
    celery_status = _text(row.get("celery_status")).casefold()
    return bool(
        status in {"failed", "failure", "cancelled", "error"}
        or celery_status in {"failed", "failure", "revoked"}
        or row.get("error")
        or row.get("error_category")
    )


def latest_task_successful(task_summary: dict | None) -> bool:
    return task_row_successful(latest_task_row(task_summary))


def latest_task_running(task_summary: dict | None) -> dict:
    task = latest_task_row(task_summary)
    return task if task_row_running(task) else {}


def latest_task_row(task_summary: dict | None) -> dict:
    if not isinstance(task_summary, dict):
        return {}
    for key in ("latest", "latest_task"):
        row = task_summary.get(key)
        if isinstance(row, dict):
            return row
    recent = task_summary.get("recent")
    if isinstance(recent, list):
        for row in recent:
            if isinstance(row, dict):
                return row
    return {}


def task_row_successful(row: dict) -> bool:
    if row.get("successful") is True:
        return True
    status = _text(row.get("status")).casefold()
    celery_status = _text(row.get("celery_status")).casefold()
    return status in {"success", "successful", "succeeded", "completed", "done"} or (
        celery_status in {"success", "successful", "succeeded"}
    )


def task_row_running(row: dict) -> bool:
    if task_row_successful(row) or task_row_failed(row):
        return False
    if row.get("running") is True:
        return True
    status = _text(row.get("status")).casefold()
    celery_status = _text(row.get("celery_status")).casefold()
    return status in {
        "pending",
        "queued",
        "received",
        "retry",
        "running",
        "started",
        "in_progress",
        "processing",
        "submitted",
        "scheduled",
    } or celery_status in {
        "pending",
        "queued",
        "received",
        "retry",
        "running",
        "started",
    }


def task_failure_identity(row: dict) -> str:
    for key in ("task_id", "id"):
        value = _text(row.get(key))
        if value:
            return f"{key}:{value}"
    return ":".join(
        [
            _text(row.get("operation"), default="task"),
            _text(row.get("error_category"), default="unknown"),
            _text(row.get("finished_at") or row.get("created_at")),
        ]
    )


def _text(value: Any, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default
