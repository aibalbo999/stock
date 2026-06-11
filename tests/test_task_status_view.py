from __future__ import annotations

from app.ui.task_status_view import (
    task_action_preflight_summary_html,
    task_execution_context_rows,
    task_run_summary_rows,
    task_status_metric_values,
    task_status_progress_caption,
)


def test_task_status_metric_values_use_operator_labels_from_view_helper() -> None:
    rows = task_status_metric_values(
        {
            "status": "SUCCESS",
            "ready": True,
            "successful": True,
            "run": {"id": 42},
        }
    )

    assert rows == [
        {"label": "任務狀態", "value": "成功"},
        {"label": "是否結束", "value": "已結束"},
        {"label": "是否成功", "value": "成功"},
        {"label": "執行紀錄", "value": "#42"},
    ]


def test_task_action_preflight_summary_html_escapes_operator_text() -> None:
    html = task_action_preflight_summary_html(
        {
            "state": "attention",
            "label": "任務操作<摘要>",
            "title": "準備重試 & 消耗額度",
            "detail": "確認 <task> 後再送出。",
            "next_step": "勾選確認。",
            "impact": "可能消耗模型或資料源額度。",
        }
    )

    assert 'class="task-action-preflight-summary is-attention"' in html
    assert "任務操作&lt;摘要&gt;" in html
    assert "準備重試 &amp; 消耗額度" in html
    assert "確認 &lt;task&gt; 後再送出。" in html


def test_task_status_progress_caption_uses_operator_step_labels() -> None:
    caption = task_status_progress_caption(
        {
            "status": "STARTED",
            "progress": {"status": "STARTED", "current_step": "worker_started"},
        }
    )

    assert caption == "進度：執行中｜背景執行器已接手"


def test_task_run_summary_rows_format_run_context() -> None:
    rows = task_run_summary_rows(
        {
            "run": {
                "id": 7,
                "status": "completed",
                "report_id": 15,
                "output_path": "/tmp/report.md",
                "started_at": "2026-06-10T09:00:00",
                "finished_at": "2026-06-10T09:05:00",
            }
        }
    )

    assert rows == [
        {
            "執行紀錄": "#7",
            "狀態": "完成",
            "報告": "#15",
            "輸出檔": "/tmp/report.md",
            "開始": "2026-06-10T09:00:00",
            "結束": "2026-06-10T09:05:00",
        }
    ]


def test_task_execution_context_rows_redact_sensitive_shape_labels() -> None:
    rows = task_execution_context_rows(
        {
            "status": "FAILURE",
            "operation": "market_refresh",
            "execution_context": {
                "celery_status": "FAILURE",
                "ready": True,
                "successful": False,
                "run_id": 99,
                "run_status": "failed",
                "run_source": "celery_data_operation",
                "operation": "market_refresh",
                "payload_shape": {
                    "present": True,
                    "top_level_keys": ["tickers", "<sensitive>"],
                    "ticker_count": 2,
                    "sensitive_key_count": 1,
                },
                "celery_info_shape": {
                    "present": True,
                    "type": "dict",
                    "top_level_keys": ["progress"],
                    "sensitive_key_count": 1,
                },
                "exception_message_preview": "network timeout",
            },
        }
    )

    assert rows[0]["celery_status"] == "失敗"
    assert rows[0]["source"] == "資料補強背景任務"
    assert "已遮蔽敏感欄位" in rows[0]["payload"]
    assert rows[0]["exception"] == "執行錯誤：network timeout"
