from __future__ import annotations


def task_queue_unavailable_detail(exc: Exception, *, operation: str | None = None) -> dict:
    return {
        "code": "task_queue_unavailable",
        "message": str(exc),
        "operation": operation,
        "retryable": True,
        "next_steps": [
            "確認 Redis broker 是否啟動且 API 可連線。",
            "確認 Celery worker/beat 是否正在執行。",
            "服務恢復後重新送出背景任務，或改用同步刷新流程。",
        ],
    }


def task_submission_failed_detail(exc: Exception, *, operation: str | None = None) -> dict:
    return {
        "code": "background_task_submission_failed",
        "message": "背景任務送出時發生未預期錯誤。",
        "operation": operation,
        "retryable": False,
        "error_type": type(exc).__name__,
        "next_steps": [
            "查看 API log 中同一時間的 exception traceback。",
            "確認背景任務 payload、Celery task 匯出與 service wiring 是否一致。",
            "若 Redis/Celery 無法連線，應改回 task_queue_unavailable 並依 503 指引修復。",
        ],
    }
