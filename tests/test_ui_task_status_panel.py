from __future__ import annotations

from app.ui.task_status_panel import task_status_diagnostic_rows


def test_task_status_diagnostic_rows_show_failure_category_and_next_steps() -> None:
    rows = task_status_diagnostic_rows(
        {
            "operation": "report_generation",
            "error_category": "quota",
            "error_severity": "warning",
            "error_summary": "模型/API 額度或速率限制",
            "retryable": True,
            "retry_kind": "report_generation",
            "next_action": "可從維護頁重試，或呼叫 POST /tasks/task-quota/retry",
            "next_steps": [
                "查看 AI 額度與模型路由或資料源額度。",
                "等待額度重置後再重試。",
            ],
        }
    )

    assert rows == [
        {
            "operation": "report_generation",
            "category": "quota",
            "severity": "warning",
            "summary": "模型/API 額度或速率限制",
            "retry": "可重試",
            "retry_kind": "report_generation",
            "next_action": "可從維護頁重試，或呼叫 POST /tasks/task-quota/retry",
            "next_steps": "查看 AI 額度與模型路由或資料源額度。；等待額度重置後再重試。",
        }
    ]


def test_task_status_diagnostic_rows_hide_when_no_failure_category() -> None:
    assert task_status_diagnostic_rows({"status": "SUCCESS"}) == []
