from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.task_payload_inspection import (
    redact_sensitive_text,
    safe_key_names,
    sensitive_key_count,
    ticker_count,
    truncate_preview,
)
from app.services.task_failure_diagnostics import (
    run_operation as diagnostic_run_operation,
    run_retry_kind as diagnostic_run_retry_kind,
    run_source as diagnostic_run_source,
    serialized_run_payload as diagnostic_serialized_run_payload,
    task_failure_diagnostic as diagnostic_task_failure_diagnostic,
    task_next_action as diagnostic_task_next_action,
)


def alert_sort_key(alert: dict) -> int:
    severity_order = {"error": 0, "warning": 1, "info": 2}
    return severity_order.get(str(alert.get("severity") or "info"), 3)


def celery_progress(celery_info: Any) -> dict | None:
    if isinstance(celery_info, dict) and isinstance(celery_info.get("progress"), dict):
        return celery_info["progress"]
    return None


def task_execution_context(
    *,
    task_id: str,
    task_status: str,
    ready: bool,
    successful: bool,
    result_payload: Any,
    celery_info: Any,
    serialized_run: dict | None,
) -> dict:
    run_payload = serialized_run_payload(serialized_run or {})
    operation = (
        run_operation(run_payload, serialized_run or {}) if serialized_run else "task_status"
    )
    context = {
        "task_id": task_id,
        "celery_status": str(task_status or "UNKNOWN"),
        "ready": bool(ready),
        "successful": bool(successful),
        "run_id": serialized_run.get("id") if isinstance(serialized_run, dict) else None,
        "run_status": serialized_run.get("status") if isinstance(serialized_run, dict) else None,
        "run_source": serialized_run.get("source") if isinstance(serialized_run, dict) else None,
        "operation": operation,
        "payload_shape": task_payload_shape(run_payload),
        "celery_info_shape": celery_info_shape(celery_info),
    }
    if ready and not successful:
        context.update(exception_summary(result_payload))
    return context


def task_payload_shape(payload: dict) -> dict:
    if not isinstance(payload, dict) or not payload:
        return {
            "present": False,
            "top_level_keys": [],
            "request_keys": [],
            "operation_payload_keys": [],
            "ticker_count": 0,
            "sensitive_key_count": 0,
        }
    request_payload = payload.get("request") if isinstance(payload.get("request"), dict) else {}
    operation_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    return {
        "present": True,
        "top_level_keys": safe_key_names(payload),
        "request_keys": safe_key_names(request_payload),
        "operation_payload_keys": safe_key_names(operation_payload),
        "ticker_count": ticker_count(payload),
        "sensitive_key_count": sensitive_key_count(payload),
    }


def celery_info_shape(celery_info: Any) -> dict:
    if celery_info is None:
        return {
            "present": False,
            "type": None,
            "top_level_keys": [],
            "progress_keys": [],
        }
    if not isinstance(celery_info, dict):
        return {
            "present": True,
            "type": type(celery_info).__name__,
            "top_level_keys": [],
            "progress_keys": [],
        }
    progress = celery_info.get("progress") if isinstance(celery_info.get("progress"), dict) else {}
    return {
        "present": True,
        "type": "dict",
        "top_level_keys": safe_key_names(celery_info),
        "progress_keys": safe_key_names(progress),
        "sensitive_key_count": sensitive_key_count(celery_info),
    }


def exception_summary(value: Any) -> dict:
    if value is None:
        return {
            "exception_type": None,
            "exception_message_preview": None,
            "exception_message_length": 0,
        }
    raw_text = str(value).strip()
    redacted = safe_exception_text(value)
    return {
        "exception_type": type(value).__name__,
        "exception_message_preview": truncate_preview(redacted),
        "exception_message_length": len(raw_text),
    }


def safe_exception_text(value: Any) -> str:
    if value is None:
        return ""
    return redact_sensitive_text(str(value).strip())


def progress_payload(
    serialized_run: dict | None, celery_progress_payload: dict | None = None
) -> dict:
    if celery_progress_payload:
        return celery_progress_payload
    if not serialized_run:
        return {
            "status": "unknown",
            "progress_pct": None,
            "current_step": None,
            "resume_hint": None,
        }
    workflow_summary = serialized_run.get("workflow_summary")
    if isinstance(workflow_summary, dict):
        return {
            "status": workflow_summary.get("status"),
            "progress_pct": workflow_summary.get("progress_pct"),
            "current_step": workflow_summary.get("current_step"),
            "next_incomplete_step": workflow_summary.get("next_incomplete_step"),
            "resume_hint": workflow_summary.get("resume_hint"),
        }
    status = str(serialized_run.get("status") or "unknown")
    return {
        "status": status,
        "progress_pct": 1.0 if status == "success" else 0.0 if status == "running" else None,
        "current_step": None,
        "resume_hint": None,
    }


def celery_status_progress(status: str | None, *, ready: bool) -> dict:
    normalized = str(status or "PENDING").upper()
    if normalized == "SUCCESS":
        return {
            "status": "success",
            "progress_pct": 1.0,
            "current_step": "task_completed",
            "resume_hint": None,
        }
    if normalized == "FAILURE":
        return {
            "status": "failed",
            "progress_pct": None,
            "current_step": "task_failed",
            "resume_hint": "任務失敗；可查看錯誤後使用重試任務。",
        }
    if normalized == "REVOKED":
        return {
            "status": "cancelled",
            "progress_pct": None,
            "current_step": "task_cancelled",
            "resume_hint": "任務已取消。",
        }
    if normalized == "RETRY":
        return {
            "status": "retrying",
            "progress_pct": 0.0,
            "current_step": "task_retrying",
            "resume_hint": "背景任務正在重試，等待背景執行器更新執行紀錄。",
        }
    if normalized == "STARTED":
        return {
            "status": "running",
            "progress_pct": 0.05,
            "current_step": "worker_started",
            "resume_hint": "背景執行器已接手，等待任務執行紀錄。",
        }
    return {
        "status": "queued" if not ready else normalized.casefold(),
        "progress_pct": 0.0 if not ready else None,
        "current_step": "waiting_for_worker",
        "resume_hint": "任務已送出，等待背景執行器建立執行紀錄。",
    }


def run_summary_row(run: dict, *, stale_after_minutes: int, now: datetime) -> dict:
    payload = serialized_run_payload(run)
    started_at = str(run.get("started_at") or "")
    finished_at = str(run.get("finished_at") or "")
    started_dt = parse_datetime(started_at)
    finished_dt = parse_datetime(finished_at)
    status = str(run.get("status") or "unknown")
    task_id = payload.get("celery_task_id")
    persisted_failure = persistent_task_failure_detail(payload)
    operation = str(persisted_failure.get("operation") or run_operation(payload, run))
    retry_kind = (
        persisted_failure.get("retry_kind")
        if "retry_kind" in persisted_failure
        else run_retry_kind(payload, run)
    )
    retryable = bool(
        persisted_failure.get("retryable")
        if "retryable" in persisted_failure
        else task_id and retry_kind
    )
    failure_diagnostic = diagnostic_from_failure_detail(
        persisted_failure
    ) or task_failure_diagnostic(
        status=status,
        error=run.get("error"),
        operation=operation,
        retryable=retryable,
    )
    duration_seconds = None
    if started_dt and finished_dt:
        duration_seconds = max(0.0, (finished_dt - started_dt).total_seconds())
    running_age_seconds = None
    if status == "running" and started_dt:
        running_age_seconds = max(0.0, (now - started_dt).total_seconds())
    return {
        "id": run.get("id"),
        "source": str(run.get("source") or "unknown"),
        "operation": operation,
        "status": status,
        "report_id": run.get("report_id"),
        "task_id": payload.get("celery_task_id"),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": round(duration_seconds, 3) if duration_seconds is not None else None,
        "running_age_seconds": round(running_age_seconds, 3)
        if running_age_seconds is not None
        else None,
        "stale_running": bool(
            running_age_seconds is not None and running_age_seconds >= stale_after_minutes * 60
        ),
        "error": run.get("error"),
        "error_category": failure_diagnostic.get("category"),
        "error_severity": failure_diagnostic.get("severity"),
        "error_summary": failure_diagnostic.get("summary"),
        "next_steps": failure_diagnostic.get("next_steps") or [],
        "retryable": retryable,
        "retry_kind": retry_kind,
        "retry_endpoint": persisted_failure.get("retry_endpoint")
        or (f"POST /tasks/{task_id}/retry" if task_id and retry_kind else None),
        "status_endpoint": persisted_failure.get("status_endpoint")
        or (f"GET /tasks/{task_id}" if task_id else None),
        "run_endpoint": persisted_failure.get("run_endpoint")
        or (f"GET /runs/{run.get('id')}" if run.get("id") else None),
        "next_action": persisted_failure.get("next_action")
        or task_next_action(
            status=status,
            task_id=task_id,
            retry_kind=retry_kind,
            error=run.get("error"),
            diagnostic=failure_diagnostic,
        ),
    }


def persistent_task_failure_detail(payload: dict) -> dict:
    detail = payload.get("task_failure_diagnostic") if isinstance(payload, dict) else None
    if not isinstance(detail, dict):
        return {}
    if str(detail.get("error_category") or "").casefold() == "unknown":
        return {}
    return detail


def diagnostic_from_failure_detail(detail: dict) -> dict | None:
    if not isinstance(detail, dict) or not detail.get("error_category"):
        return None
    return {
        "category": detail.get("error_category"),
        "severity": detail.get("error_severity"),
        "summary": detail.get("error_summary"),
        "next_steps": detail.get("next_steps")
        if isinstance(detail.get("next_steps"), list)
        else [],
    }


def serialized_run_payload(run: dict) -> dict:
    return diagnostic_serialized_run_payload(run)


def run_retry_kind(payload: dict, run: dict | Any) -> str | None:
    return diagnostic_run_retry_kind(payload, run)


def run_source(run: dict | Any) -> str:
    return diagnostic_run_source(run)


def task_next_action(
    *,
    status: str,
    task_id: object,
    retry_kind: str | None,
    error: object,
    diagnostic: dict | None = None,
) -> str:
    return diagnostic_task_next_action(
        status=status,
        task_id=task_id,
        retry_kind=retry_kind,
        error=error,
        diagnostic=diagnostic,
    )


def task_failure_diagnostic(
    *,
    status: str,
    error: object,
    operation: str,
    retryable: bool,
) -> dict:
    return diagnostic_task_failure_diagnostic(
        status=status,
        error=error,
        operation=operation,
        retryable=retryable,
    )


def task_status_failure_detail(
    *,
    task_id: str,
    task_status: str,
    error: object,
    serialized_run: dict | None,
) -> dict:
    run_payload = serialized_run_payload(serialized_run or {})
    persisted_failure = persistent_task_failure_detail(run_payload)
    if persisted_failure:
        return {
            **persisted_failure,
            "status_endpoint": persisted_failure.get("status_endpoint") or f"GET /tasks/{task_id}",
            "run_endpoint": persisted_failure.get("run_endpoint")
            or (
                f"GET /runs/{serialized_run.get('id')}"
                if isinstance(serialized_run, dict) and serialized_run.get("id")
                else None
            ),
        }
    retry_kind = run_retry_kind(run_payload, serialized_run or {}) if serialized_run else None
    retryable = bool(task_id and retry_kind)
    run_status = str((serialized_run or {}).get("status") or task_status or "unknown")
    operation = (
        run_operation(run_payload, serialized_run or {}) if serialized_run else "task_status"
    )
    error_text = error or (serialized_run or {}).get("error")
    diagnostic = task_failure_diagnostic(
        status=run_status,
        error=error_text,
        operation=operation,
        retryable=retryable,
    )
    if not diagnostic.get("category"):
        return {}
    return {
        "operation": operation,
        "error_category": diagnostic.get("category"),
        "error_severity": diagnostic.get("severity"),
        "error_summary": diagnostic.get("summary"),
        "next_steps": diagnostic.get("next_steps") or [],
        "retryable": retryable,
        "retry_kind": retry_kind,
        "retry_endpoint": f"POST /tasks/{task_id}/retry" if retryable else None,
        "status_endpoint": f"GET /tasks/{task_id}",
        "run_endpoint": (
            f"GET /runs/{serialized_run.get('id')}"
            if isinstance(serialized_run, dict) and serialized_run.get("id")
            else None
        ),
        "next_action": task_next_action(
            status=run_status,
            task_id=task_id,
            retry_kind=retry_kind,
            error=error_text,
            diagnostic=diagnostic,
        ),
    }


def run_operation(payload: dict, run: dict) -> str:
    return diagnostic_run_operation(payload, run)


def task_summary_totals(rows: list[dict]) -> dict:
    completed = [
        float(row["duration_seconds"]) for row in rows if row.get("duration_seconds") is not None
    ]
    success_count = sum(1 for row in rows if row.get("status") == "success")
    failed_count = sum(1 for row in rows if row.get("status") == "failed")
    cancelled_count = sum(1 for row in rows if row.get("status") == "cancelled")
    running_count = sum(1 for row in rows if row.get("status") == "running")
    total_count = len(rows)
    return {
        "run_count": total_count,
        "success_count": success_count,
        "failed_count": failed_count,
        "cancelled_count": cancelled_count,
        "running_count": running_count,
        "stale_running_count": sum(1 for row in rows if row.get("stale_running")),
        "success_rate": round(success_count / total_count, 4) if total_count else None,
        "avg_duration_seconds": round(sum(completed) / len(completed), 3) if completed else None,
    }


def count_error_categories(rows: list[dict]) -> list[dict]:
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        category = row.get("error_category")
        if not category:
            continue
        severity = str(row.get("error_severity") or "unknown")
        key = (str(category), severity)
        counts[key] = counts.get(key, 0) + 1
    return [
        {"error_category": category, "severity": severity, "count": count}
        for (category, severity), count in sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0][0], item[0][1]),
        )
    ]


def error_category_daily_rows(rows: list[dict]) -> list[dict]:
    counts: dict[tuple[str, str, str], int] = {}
    for row in rows:
        category = row.get("error_category")
        if not category:
            continue
        started_at = parse_datetime(row.get("started_at"))
        date_value = started_at.date().isoformat() if started_at else "unknown"
        severity = str(row.get("error_severity") or "unknown")
        key = (date_value, str(category), severity)
        counts[key] = counts.get(key, 0) + 1
    return [
        {
            "date": date_value,
            "error_category": category,
            "severity": severity,
            "count": count,
        }
        for (date_value, category, severity), count in sorted(
            counts.items(),
            key=lambda item: (item[0][0], item[0][1], item[0][2]),
        )
    ]


def task_failure_alerts(rows: list[dict], daily_rows: list[dict]) -> list[dict]:
    category_rows: dict[str, list[dict]] = {}
    daily_dates: dict[str, set[str]] = {}
    for row in rows:
        category = row.get("error_category")
        if category:
            category_rows.setdefault(str(category), []).append(row)
    for row in daily_rows:
        category = row.get("error_category")
        date_value = row.get("date")
        if category and date_value:
            daily_dates.setdefault(str(category), set()).add(str(date_value))
    alerts = []
    for category, grouped_rows in sorted(category_rows.items()):
        count = len(grouped_rows)
        days = len(daily_dates.get(category, set()))
        severity = alert_severity_for_category(category, grouped_rows, count=count, days=days)
        if not severity:
            continue
        sample = grouped_rows[0]
        alerts.append(
            {
                "severity": severity,
                "code": f"task_failure_{category}",
                "error_category": category,
                "count": count,
                "days": days,
                "message": task_failure_alert_message(
                    category=category,
                    count=count,
                    days=days,
                    summary=str(sample.get("error_summary") or category),
                ),
                "next_steps": sample.get("next_steps")
                if isinstance(sample.get("next_steps"), list)
                else [],
            }
        )
    stale_count = sum(1 for row in rows if row.get("stale_running"))
    if stale_count:
        alerts.append(
            {
                "severity": "warning",
                "code": "task_stale_running",
                "error_category": "stale_running",
                "count": stale_count,
                "days": 0,
                "message": f"有 {stale_count} 個背景任務疑似卡住，請檢查背景執行器與任務狀態。",
                "next_steps": [
                    "查看背景任務觀測中的疑似卡住任務。",
                    "確認背景執行器是否在線，必要時取消或重試任務。",
                ],
            }
        )
    return sorted(alerts, key=lambda item: (alert_sort_key(item), str(item.get("code") or "")))


def alert_severity_for_category(
    category: str,
    rows: list[dict],
    *,
    count: int,
    days: int,
) -> str | None:
    if category in {"task_queue", "payload_validation"}:
        return "error"
    if count >= 2 or days >= 2:
        return "warning" if any(row.get("error_severity") != "error" for row in rows) else "error"
    return None


def task_failure_alert_message(
    *,
    category: str,
    count: int,
    days: int,
    summary: str,
) -> str:
    if days >= 2:
        return f"{summary} 在 {days} 天內重複出現 {count} 次，建議優先處理。"
    return f"{summary} 近期出現 {count} 次，建議檢查相關設定或外部服務。"


def count_rows(rows: list[dict], key: str) -> list[dict]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row.get(key) or "unknown")] = counts.get(str(row.get(key) or "unknown"), 0) + 1
    return [
        {key: bucket, "count": count}
        for bucket, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


__all__ = [
    "alert_severity_for_category",
    "alert_sort_key",
    "celery_progress",
    "celery_status_progress",
    "count_error_categories",
    "count_rows",
    "diagnostic_from_failure_detail",
    "error_category_daily_rows",
    "exception_summary",
    "parse_datetime",
    "persistent_task_failure_detail",
    "progress_payload",
    "run_operation",
    "run_retry_kind",
    "run_source",
    "safe_exception_text",
    "run_summary_row",
    "serialized_run_payload",
    "task_failure_alert_message",
    "task_failure_alerts",
    "task_failure_diagnostic",
    "task_execution_context",
    "task_payload_shape",
    "task_next_action",
    "task_status_failure_detail",
    "task_summary_totals",
]
