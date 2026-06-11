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
        "error_summary": diagnostic.get("summary") or "背景任務佇列或背景執行器異常",
        "next_steps": diagnostic.get("next_steps")
        or [
            "到系統設定 > 維護 > 背景任務觀測確認提交、佇列與背景執行器狀態。",
            "服務恢復後重新送出背景任務。",
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
            "查看系統日誌中同一時間的錯誤明細。",
            "確認背景任務輸入內容、任務註冊與後端服務設定是否一致。",
            "若背景任務服務無法連線，請依 503 佇列未就緒指引修復。",
        ],
    }
    if context:
        detail["context"] = context
    return detail
