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
