from __future__ import annotations

from app.ui.report_health import latest_report_health_summary


def test_latest_report_health_summary_uses_quality_gate_candidate_and_follow_up_state() -> None:
    result = latest_report_health_summary(
        {
            "report_id": 15,
            "topic": "記憶體產業鏈",
            "tickers": ["2408", "8150"],
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}},
            "candidate_whitelist": [
                {"ticker": "2408", "status": "evidence_supported"},
                {"ticker": "8150", "status": "evidence_supported"},
            ],
        },
        {
            "summary": {"required_count": 0, "tracking_count": 1},
            "status": "ready",
        },
    )

    assert result == {
        "state": "ready",
        "quality_label": "ready",
        "report_label": "#15｜記憶體產業鏈",
        "candidate_label": "候選 2｜正式 2",
        "follow_up_label": "可閱讀",
        "action_label": "閱讀最新版",
    }


def test_latest_report_health_summary_marks_required_gaps_as_attention() -> None:
    result = latest_report_health_summary(
        {
            "report_id": 12,
            "topic": "AI 產業鏈",
            "quality_gate": {"status": "caution", "metrics": {"promoted_count": 1}},
            "candidate_whitelist": [{"ticker": "2330"}],
        },
        {"summary": {"required_count": 2}, "status": "needs_follow_up"},
    )

    assert result["state"] == "attention"
    assert result["follow_up_label"] == "需補強 2 項"
    assert result["action_label"] == "補強資料"


def test_latest_report_health_summary_preserves_explicit_zero_promoted_count() -> None:
    result = latest_report_health_summary(
        {
            "report_id": 18,
            "topic": "散熱產業鏈",
            "tickers": ["3017", "3324"],
            "quality_gate": {"status": "caution", "metrics": {"promoted_count": 0}},
            "candidate_whitelist": [{"ticker": "3017"}, {"ticker": "3324"}],
        },
        {"summary": {"required_count": 0}},
    )

    assert result["candidate_label"] == "候選 2｜正式 0"


def test_latest_report_health_summary_handles_empty_report() -> None:
    result = latest_report_health_summary({}, {})

    assert result == {
        "state": "attention",
        "quality_label": "-",
        "report_label": "尚未選擇報告",
        "candidate_label": "候選 0｜正式 0",
        "follow_up_label": "尚無狀態",
        "action_label": "建立分析",
    }
