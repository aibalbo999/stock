from __future__ import annotations


def task_failure_drilldown_rows(task_summary: dict) -> list[dict]:
    failures = _task_summary_failures(task_summary)
    return [
        {
            "run_id": row.get("id") or "-",
            "operation": row.get("operation") or "-",
            "status": row.get("status") or "-",
            "task_id": row.get("task_id") or "-",
            "category": row.get("error_category") or "-",
            "severity": row.get("error_severity") or "-",
            "summary": row.get("error_summary") or "-",
            "retry": "可重試" if row.get("retryable") else "需人工",
            "retry_kind": row.get("retry_kind") or "-",
            "next_action": row.get("next_action") or _fallback_failure_next_action(row),
            "next_steps": _task_next_steps_text(row),
            "error": row.get("error") or "-",
            "started_at": row.get("started_at") or "-",
        }
        for row in failures
    ]


def task_retry_options(task_summary: dict) -> list[dict]:
    options = []
    for row in _task_summary_failures(task_summary):
        task_id = str(row.get("task_id") or "").strip()
        if not task_id or not row.get("retryable"):
            continue
        options.append(
            {
                "task_id": task_id,
                "label": _task_retry_option_label(row),
                "operation": row.get("operation") or "unknown",
                "run_id": row.get("id"),
                "retry_endpoint": row.get("retry_endpoint") or f"POST /tasks/{task_id}/retry",
            }
        )
    return options


def _task_summary_failures(task_summary: dict) -> list[dict]:
    if not isinstance(task_summary, dict):
        return []
    failures = task_summary.get("recent_failures")
    if not isinstance(failures, list):
        return []
    return [row for row in failures if isinstance(row, dict)]


def _task_retry_option_label(row: dict) -> str:
    task_id = str(row.get("task_id") or "")
    operation = str(row.get("operation") or "unknown")
    run_id = row.get("id") or "-"
    return f"{operation}｜run #{run_id}｜{task_id}"


def _fallback_failure_next_action(row: dict) -> str:
    if row.get("task_id"):
        return "查看任務狀態，確認 payload 是否支援自動重試。"
    return "缺少 task id；請從 run 明細檢查。"


def _task_next_steps_text(row: dict) -> str:
    next_steps = row.get("next_steps")
    if not isinstance(next_steps, list):
        return "-"
    steps = [str(step).strip() for step in next_steps if str(step).strip()]
    return "；".join(steps) if steps else "-"
