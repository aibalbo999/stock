from __future__ import annotations

from pathlib import Path

from app.ui.report_center_presenter import (
    empty_report_action_summary,
    latest_report_picker_state,
    report_reader_decision_summary,
    report_run_detail_error_message,
    report_run_history_rows,
)


def test_report_center_presenter_is_streamlit_free() -> None:
    source = Path("app/ui/report_center_presenter.py").read_text()

    assert "import streamlit" not in source
    assert "st." not in source


def test_report_center_presenter_keeps_latest_only_picker_language() -> None:
    picker = latest_report_picker_state(
        [
            {
                "id": 15,
                "title": "AI 產業鏈",
                "topic": "AI 產業鏈",
                "generated_at": "2026-06-10T15:30:00",
            },
            {
                "id": 18,
                "title": "散熱產業鏈",
                "topic": "散熱產業鏈",
                "generated_at": "2026-06-09T16:10:00",
            },
        ],
        pending_report_id=18,
        current_report_id=15,
    )

    assert picker["mode"] == "multi_topic_latest"
    assert picker["selected_id"] == 18
    assert picker["summary_title"] == "每個主題的最新版"
    assert picker["scope_note"] == "這不是歷史版本清單；每個主題只顯示最新一份可讀報告。"


def test_report_center_presenter_keeps_run_history_operator_labels() -> None:
    rows = report_run_history_rows(
        [
            {
                "id": 42,
                "source": "follow_up_api",
                "status": "failed",
                "report_id": 15,
                "payload": '{"celery_task_id":"task-42"}',
                "started_at": "2026-06-11T09:00:00",
                "finished_at": None,
                "error": "task_queue_error",
            },
            "ignored",
        ]
    )

    assert rows == [
        {
            "紀錄": "#42",
            "來源": "自動補強",
            "狀態": "失敗",
            "報告": "#15",
            "背景任務": "task-42",
            "開始": "2026-06-11 09:00",
            "完成": "-",
            "錯誤": "背景任務佇列異常",
        }
    ]
    assert report_run_detail_error_message("task_queue_error") == (
        "執行紀錄錯誤：背景任務佇列異常"
    )


def test_report_center_presenter_keeps_empty_and_reader_decision_summaries() -> None:
    empty_summary = empty_report_action_summary(
        {
            "mode": "running",
            "action_label": "查看任務",
            "route_hint": "task:first-report-task",
        }
    )
    reader_summary = report_reader_decision_summary(
        {
            "overall_state": "attention",
            "trust_label": "可讀但需補強",
            "trust_explanation": "還有必要資料缺口",
            "primary_action": "補強資料",
            "primary_action_detail": "先補齊必要證據。",
        },
        {
            "state": "ready",
            "title": "品質門檻已通過",
            "detail": "候選清單可閱讀。",
        },
    )

    assert empty_summary == {
        "state": "running",
        "eyebrow": "建議操作",
        "title": "先確認背景任務進度",
        "caption": "最新任務還在背景執行；完成前避免重複送出分析。",
        "action_label": "查看任務",
        "route_hint": "task:first-report-task",
    }
    assert reader_summary == {
        "state": "attention",
        "eyebrow": "閱讀決策",
        "title": "可先閱讀，但投資判斷需標示限制",
        "caption": "還有必要資料缺口",
        "evidence": "尚無報告時間",
        "quality": "品質 -｜候選 0｜正式 0",
        "follow_up": "補強 尚無狀態",
        "action_label": "補強資料",
        "action_detail": "先補齊必要證據。",
    }
