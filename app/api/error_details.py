from __future__ import annotations

from app.services.task_failure_diagnostics import task_failure_diagnostic


def task_queue_unavailable_detail(
    exc: Exception,
    *,
    operation: str | None = None,
    context: dict | None = None,
) -> dict:
    diagnostic = task_failure_diagnostic(
        status="failed",
        error=exc,
        operation=operation or "task_queue",
        retryable=True,
    )
    detail = {
        "code": "task_queue_unavailable",
        "message": str(exc),
        "operation": operation,
        "retryable": True,
        "error_type": type(exc).__name__,
        "error_category": diagnostic.get("category") or "task_queue",
        "error_severity": diagnostic.get("severity") or "error",
        "error_summary": diagnostic.get("summary") or "Redis/Celery queue 或 worker 異常",
        "next_steps": [
            "確認 Redis broker 是否啟動且 API 可連線。",
            "確認 Celery worker/beat 是否正在執行。",
            "服務恢復後重新送出背景任務，或改用同步刷新流程。",
        ],
    }
    if context:
        detail["context"] = context
    return detail


def task_submission_failed_detail(
    exc: Exception,
    *,
    operation: str | None = None,
    context: dict | None = None,
) -> dict:
    diagnostic = task_failure_diagnostic(
        status="failed",
        error=exc,
        operation=operation or "task_submission",
        retryable=False,
    )
    detail = {
        "code": "background_task_submission_failed",
        "message": "背景任務送出時發生未預期錯誤。",
        "operation": operation,
        "retryable": False,
        "error_type": type(exc).__name__,
        "error_category": diagnostic.get("category") or "unknown",
        "error_severity": diagnostic.get("severity") or "error",
        "error_summary": diagnostic.get("summary") or "未分類任務失敗",
        "next_steps": [
            "查看 API log 中同一時間的 exception traceback。",
            "確認背景任務 payload、Celery task 匯出與 service wiring 是否一致。",
            "若 Redis/Celery 無法連線，應改回 task_queue_unavailable 並依 503 指引修復。",
        ],
    }
    if context:
        detail["context"] = context
    return detail
