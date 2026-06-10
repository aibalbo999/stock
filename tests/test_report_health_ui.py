from __future__ import annotations

from app.ui.report_health import latest_report_health_summary


def test_latest_report_health_summary_uses_quality_gate_candidate_and_follow_up_state() -> None:
    result = latest_report_health_summary(
        {
            "report_id": 15,
            "title": "記憶體產業鏈 自動分析報告",
            "topic": "記憶體產業鏈",
            "generated_at": "2026-06-06T16:31:24",
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
        "report_label": "記憶體產業鏈 自動分析報告",
        "report_meta_label": "#15｜記憶體產業鏈｜2026-06-06 16:31",
        "candidate_label": "候選 2｜正式 2",
        "follow_up_state": "ready",
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
    assert result["follow_up_state"] == "needs_data"
    assert result["follow_up_label"] == "需補強 2 項"
    assert result["action_label"] == "補強資料"


def test_latest_report_health_summary_marks_market_freshness_as_attention() -> None:
    result = latest_report_health_summary(
        {
            "report_id": 15,
            "topic": "AI 產業鏈",
            "tickers": ["2330", "2382"],
            "quality_gate": {
                "status": "ready",
                "metrics": {
                    "promoted_count": 2,
                    "market_latest_trade_date": "2026-06-02",
                    "market_database_latest_trade_date": "2026-06-05",
                    "market_older_than_database_latest_count": 1,
                    "market_trade_date_lag_days": 3,
                    "market_trade_date_warning_suppressed": False,
                },
            },
            "candidate_whitelist": [{"ticker": "2330"}, {"ticker": "2382"}],
        },
        {"summary": {"required_count": 0}, "status": "ready"},
    )

    assert result["state"] == "attention"
    assert result["follow_up_state"] == "market_freshness"
    assert result["follow_up_label"] == "股價落後 1 檔"
    assert result["action_label"] == "刷新股價"


def test_latest_report_health_summary_marks_missing_quality_gate_as_attention() -> None:
    result = latest_report_health_summary(
        {
            "report_id": 29,
            "topic": "機器人供應鏈",
            "tickers": ["2357", "2308"],
            "candidate_whitelist": [{"ticker": "2357"}, {"ticker": "2308"}],
        },
        {"summary": {"required_count": 0}, "status": "ready"},
    )

    assert result["state"] == "attention"
    assert result["quality_label"] == "尚無法判斷"
    assert result["candidate_label"] == "候選 2｜正式 0"
    assert result["follow_up_state"] == "quality_unknown"
    assert result["follow_up_label"] == "品質待確認"
    assert result["action_label"] == "確認品質"


def test_latest_report_health_summary_prefills_first_required_data_gap_action() -> None:
    result = latest_report_health_summary(
        {
            "report_id": 12,
            "topic": "AI 產業鏈",
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}},
            "candidate_whitelist": [{"ticker": "2330"}, {"ticker": "2382"}],
        },
        {
            "summary": {"required_count": 2},
            "status": "needs_follow_up",
            "next_actions": [
                {
                    "action": "refresh_market",
                    "tickers": ["2330"],
                    "purpose": "required",
                    "target": "股價與量能",
                    "reason": "缺少最新股價",
                },
                {
                    "action": "ingest_company_filings",
                    "tickers": ["2382"],
                    "purpose": "required",
                    "target": "公司公開文件",
                    "reason": "缺少法說會簡報",
                },
            ],
        },
    )

    assert result["state"] == "attention"
    assert result["follow_up_state"] == "needs_data"
    assert result["follow_up_label"] == "需補強 2 項"
    assert result["action_label"] == "刷新股價"


def test_latest_report_health_summary_marks_follow_up_running() -> None:
    result = latest_report_health_summary(
        {
            "report_id": 21,
            "topic": "AI 伺服器供應鏈",
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 3}},
            "auto_follow_up": {"status": "queued"},
            "candidate_whitelist": [{"ticker": "2330"}, {"ticker": "2382"}, {"ticker": "6669"}],
        },
        {"summary": {"required_count": 1}, "status": "queued"},
    )

    assert result["state"] == "attention"
    assert result["follow_up_state"] == "rerun_running"
    assert result["follow_up_label"] == "重跑中"
    assert result["action_label"] == "查看進度"


def test_latest_report_health_summary_marks_blocked_follow_up() -> None:
    result = latest_report_health_summary(
        {
            "report_id": 32,
            "topic": "電源管理",
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}},
            "auto_follow_up": {
                "rerun_report": {
                    "status": "skipped",
                    "blockers": ["公司公開文件仍不足：2382"],
                }
            },
            "candidate_whitelist": [{"ticker": "2308"}, {"ticker": "6415"}],
        },
        {"summary": {"required_count": 0}, "status": "blocked"},
    )

    assert result["state"] == "blocked"
    assert result["follow_up_state"] == "blocked"
    assert result["follow_up_label"] == "補強受阻"
    assert result["action_label"] == "查看阻塞"


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
        "report_meta_label": "尚無報告時間",
        "candidate_label": "候選 0｜正式 0",
        "follow_up_state": "missing",
        "follow_up_label": "尚無狀態",
        "action_label": "建立分析",
    }


def test_latest_report_health_summary_falls_back_to_topic_when_title_missing() -> None:
    result = latest_report_health_summary(
        {
            "report_id": 22,
            "topic": "散熱產業鏈",
            "generated_at": "2026-06-06T08:05:00",
        },
        {},
    )

    assert result["report_label"] == "散熱產業鏈"
    assert result["report_meta_label"] == "#22｜散熱產業鏈｜2026-06-06 08:05"
