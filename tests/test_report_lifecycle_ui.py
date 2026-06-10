from __future__ import annotations

from app.ui.report_lifecycle import latest_report_lifecycle, stage_by_key


def test_latest_report_lifecycle_marks_ready_report_readable() -> None:
    lifecycle = latest_report_lifecycle(
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
        {"summary": {"required_count": 0, "tracking_count": 1}, "status": "ready"},
    )

    assert lifecycle["overall_state"] == "ready"
    assert lifecycle["trust_label"] == "可閱讀"
    assert lifecycle["primary_action"] == "閱讀最新版"
    assert lifecycle["route_hint"] == "report:15"
    assert stage_by_key(lifecycle, "data")["state"] == "done"
    assert stage_by_key(lifecycle, "quality")["state"] == "done"
    assert stage_by_key(lifecycle, "readable")["label"] == "可閱讀"


def test_latest_report_lifecycle_blocks_zero_formal_tickers() -> None:
    lifecycle = latest_report_lifecycle(
        {
            "report_id": 18,
            "topic": "散熱產業鏈",
            "tickers": ["3017", "3324"],
            "quality_gate": {"status": "caution", "metrics": {"promoted_count": 0}},
            "candidate_whitelist": [{"ticker": "3017"}, {"ticker": "3324"}],
        },
        {"summary": {"required_count": 0}},
    )

    assert lifecycle["overall_state"] == "blocked"
    assert lifecycle["trust_label"] == "不可直接採信"
    assert lifecycle["primary_action"] == "補強資料"
    assert lifecycle["route_hint"] == "data_enrichment"
    assert stage_by_key(lifecycle, "quality")["state"] == "blocked"
    assert stage_by_key(lifecycle, "readable")["state"] == "blocked"


def test_latest_report_lifecycle_marks_required_gaps_as_attention() -> None:
    lifecycle = latest_report_lifecycle(
        {
            "report_id": 12,
            "topic": "AI 產業鏈",
            "quality_gate": {"status": "caution", "metrics": {"promoted_count": 1}},
            "candidate_whitelist": [{"ticker": "2330"}],
        },
        {"summary": {"required_count": 2}, "status": "needs_follow_up"},
    )

    assert lifecycle["overall_state"] == "attention"
    assert lifecycle["trust_label"] == "可閱讀但需註記"
    assert lifecycle["primary_action"] == "補強資料"
    assert stage_by_key(lifecycle, "data")["label"] == "缺口 2 項"
    assert stage_by_key(lifecycle, "follow_up")["state"] == "attention"
    assert stage_by_key(lifecycle, "rerun")["label"] == "補強後重跑"


def test_latest_report_lifecycle_marks_follow_up_running() -> None:
    lifecycle = latest_report_lifecycle(
        {
            "report_id": 21,
            "topic": "AI 伺服器供應鏈",
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 3}},
            "auto_follow_up": {"status": "queued"},
            "candidate_whitelist": [{"ticker": "2330"}, {"ticker": "2382"}, {"ticker": "6669"}],
        },
        {"summary": {"required_count": 1}, "status": "queued"},
    )

    assert lifecycle["overall_state"] == "running"
    assert lifecycle["trust_label"] == "補強中"
    assert lifecycle["primary_action"] == "查看補強任務"
    assert lifecycle["route_hint"] == "settings:maintenance"
    assert stage_by_key(lifecycle, "follow_up")["state"] == "running"
    assert stage_by_key(lifecycle, "rerun")["state"] == "running"


def test_latest_report_lifecycle_handles_empty_report() -> None:
    lifecycle = latest_report_lifecycle({}, {})

    assert lifecycle["overall_state"] == "attention"
    assert lifecycle["trust_label"] == "尚未有最新版報告"
    assert lifecycle["primary_action"] == "建立分析"
    assert lifecycle["route_hint"] == "analysis"
    assert stage_by_key(lifecycle, "data")["state"] == "unknown"


def test_latest_report_lifecycle_reads_nested_selected_required_count() -> None:
    lifecycle = latest_report_lifecycle(
        {
            "report_id": 31,
            "topic": "先進封裝",
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}},
            "candidate_whitelist": [{"ticker": "2330"}, {"ticker": "3711"}],
        },
        {"summary": {"selected": {"required_count": 3}}, "status": "needs_follow_up"},
    )

    assert lifecycle["overall_state"] == "attention"
    assert stage_by_key(lifecycle, "data")["label"] == "缺口 3 項"


def test_latest_report_lifecycle_marks_skipped_rerun_as_incomplete() -> None:
    lifecycle = latest_report_lifecycle(
        {
            "report_id": 32,
            "topic": "電源管理",
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}},
            "auto_follow_up": {"rerun_report": {"status": "skipped"}},
            "candidate_whitelist": [{"ticker": "2308"}, {"ticker": "6415"}],
        },
        {"summary": {"required_count": 0}, "status": "ready"},
    )

    assert lifecycle["overall_state"] == "attention"
    assert stage_by_key(lifecycle, "rerun")["state"] == "attention"
    assert stage_by_key(lifecycle, "rerun")["label"] == "重跑未完成"


def test_latest_report_lifecycle_falls_back_to_tickers_when_promoted_metrics_missing() -> None:
    lifecycle = latest_report_lifecycle(
        {
            "report_id": 33,
            "topic": "AI 代工",
            "tickers": ["2330", "2382"],
            "quality_gate": {"status": "ready", "metrics": {}},
        },
        {"summary": {"required_count": 0}, "status": "ready"},
    )

    assert lifecycle["overall_state"] == "ready"
    assert stage_by_key(lifecycle, "quality")["state"] == "done"


def test_latest_report_lifecycle_blocks_insufficient_quality_gate() -> None:
    lifecycle = latest_report_lifecycle(
        {
            "report_id": 34,
            "topic": "網通產業鏈",
            "quality_gate": {"status": "insufficient", "metrics": {"promoted_count": 2}},
            "candidate_whitelist": [{"ticker": "2345"}, {"ticker": "3596"}],
        },
        {"summary": {"required_count": 0}, "status": "ready"},
    )

    assert lifecycle["overall_state"] == "blocked"
    assert stage_by_key(lifecycle, "quality")["state"] == "blocked"
    assert stage_by_key(lifecycle, "quality")["label"] == "insufficient"


def test_latest_report_lifecycle_attention_explanation_names_incomplete_rerun() -> None:
    lifecycle = latest_report_lifecycle(
        {
            "report_id": 35,
            "topic": "車用電子",
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}},
            "auto_follow_up": {"rerun_report": {"status": "skipped"}},
            "candidate_whitelist": [{"ticker": "2308"}, {"ticker": "3034"}],
        },
        {"summary": {"required_count": 0}, "status": "ready"},
    )

    assert lifecycle["overall_state"] == "attention"
    assert "0 項必補缺口" not in lifecycle["trust_explanation"]
    assert "尚未產生可讀的重跑報告" in lifecycle["trust_explanation"]
