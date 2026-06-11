from __future__ import annotations

from pathlib import Path

from app.ui.task_status_presenter import (
    task_action_preflight_summary,
    task_run_source_label,
    task_run_status_label,
    task_status_operation_label,
    task_status_poll_caption,
    task_status_poll_interval_seconds,
    task_status_progress_step_label,
    task_status_state_label,
)


def test_task_status_presenter_is_streamlit_free() -> None:
    source = Path("app/ui/task_status_presenter.py").read_text()

    assert "import streamlit" not in source
    assert "st." not in source


def test_task_status_presenter_keeps_retry_preflight_language() -> None:
    summary = task_action_preflight_summary(
        {
            "task_id": "task-quota",
            "status": "FAILURE",
            "operation": "report_generation",
            "retryable": True,
            "retry_kind": "report_generation",
            "error_category": "quota",
        },
        action="retry",
        confirmed=False,
    )

    assert summary["state"] == "attention"
    assert summary["title"] == "準備重試背景任務"
    assert summary["next_step"] == "勾選確認後，再按「重試任務」重新送出背景任務。"
    assert "可能再次消耗模型、外部資料源或 API 額度" in summary["impact"]


def test_task_status_presenter_keeps_poll_caption_logic() -> None:
    queued = {"task_id": "task-queued", "status": "PENDING", "ready": False}
    retrying = {"task_id": "task-retry", "status": "RETRY", "ready": False}
    done = {"task_id": "task-done", "status": "SUCCESS", "ready": True}

    assert task_status_poll_interval_seconds(queued, default_seconds=5) == 8
    assert task_status_poll_interval_seconds(retrying, default_seconds=5) == 15
    assert task_status_poll_caption(
        queued,
        auto_refresh=True,
        fragment_supported=True,
        default_seconds=5,
    ) == "狀態輪詢：約每 8 秒更新，排隊中。"
    assert task_status_poll_caption(
        done,
        auto_refresh=True,
        fragment_supported=True,
        default_seconds=5,
    ) == "狀態輪詢：任務已結束，自動刷新停止。"


def test_task_status_presenter_infers_operation_from_run_payload_and_source() -> None:
    assert (
        task_status_operation_label(
            {
                "run": {
                    "payload_json": '{"workflow_name": "market_data_refresh"}',
                },
            }
        )
        == "市場資料刷新"
    )
    assert (
        task_status_operation_label(
            {
                "execution_context": {
                    "run_source": "celery_report_generation",
                },
            }
        )
        == "報告生成"
    )


def test_task_status_presenter_keeps_operator_context_labels() -> None:
    assert task_status_state_label("STARTED") == "執行中"
    assert task_run_status_label("completed") == "完成"
    assert task_run_source_label("celery_data_operation") == "資料補強背景任務"
    assert task_status_progress_step_label("fetch_market_data") == "抓取市場資料"
