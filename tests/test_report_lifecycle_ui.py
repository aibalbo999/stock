from __future__ import annotations

from app.ui import report_center
from app.ui.report_lifecycle import latest_report_lifecycle, stage_by_key


def test_latest_report_picker_state_single_latest_report_without_choice() -> None:
    picker = report_center.latest_report_picker_state(
        [
            {
                "id": 15,
                "title": "AI 產業鏈",
                "topic": "AI 產業鏈",
                "generated_at": "2026-06-10T15:30:00",
            }
        ],
        pending_report_id=None,
        current_report_id=None,
    )

    assert picker["mode"] == "single_latest"
    assert picker["selected_id"] == 15
    assert picker["selector_label"] == ""
    assert picker["summary_title"] == "目前最新版報告"
    assert picker["summary_detail"] == "AI 產業鏈｜2026-06-10 15:30"
    assert picker["scope_note"] == "此頁只顯示目前保留的最新版；舊版請到疑難排解的執行紀錄追蹤。"
    assert picker["options"][0]["label"] == "2026-06-10 15:30｜AI 產業鏈"


def test_latest_report_picker_state_multi_topic_uses_topic_latest_selector() -> None:
    picker = report_center.latest_report_picker_state(
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
    assert picker["selector_label"] == "選擇主題最新版報告"
    assert picker["summary_title"] == "每個主題的最新版"
    assert picker["summary_detail"] == "共 2 份主題最新版，預設讀取最新產生的一份。"
    assert picker["scope_note"] == "這不是歷史版本清單；每個主題只顯示最新一份可讀報告。"


def test_latest_report_picker_state_shows_running_empty_state() -> None:
    picker = report_center.latest_report_picker_state(
        [],
        task_summary={
            "latest": {
                "task_id": "first-report-task",
                "operation": "report_generation",
                "status": "queued",
                "celery_status": "PENDING",
            },
            "totals": {
                "run_count": 1,
                "success_count": 0,
                "failed_count": 0,
                "running_count": 1,
                "stale_running_count": 0,
            },
        },
    )

    assert picker == {
        "mode": "running",
        "options": [],
        "selected_id": None,
        "selector_label": "",
        "summary_title": "最新版報告生成中",
        "summary_detail": "最新任務正在背景執行；完成前不需要重複建立分析。",
        "scope_note": "完成後報告中心會只顯示可閱讀的最新版結果。",
        "action_label": "查看任務",
        "route_hint": "task:first-report-task",
    }


def test_latest_report_picker_state_empty_state_offers_create_analysis_action() -> None:
    picker = report_center.latest_report_picker_state([], task_summary={})

    assert picker == {
        "mode": "empty",
        "options": [],
        "selected_id": None,
        "selector_label": "",
        "summary_title": "尚無最新版報告",
        "summary_detail": "建立分析後，這裡會顯示目前保留的最新版報告。",
        "scope_note": "報告中心不需要手動整理歷史版本；系統會保留最新可讀結果。",
        "action_label": "建立分析",
        "route_hint": "analysis",
    }


def test_latest_report_picker_summary_renders_latest_only_scope_note(monkeypatch) -> None:
    rendered: list[str] = []
    monkeypatch.setattr(
        report_center.st,
        "markdown",
        lambda body, **_kwargs: rendered.append(str(body)),
    )

    report_center._render_latest_report_picker_summary(
        {
            "mode": "multi_topic_latest",
            "summary_title": "每個主題的最新版",
            "summary_detail": "共 2 份主題最新版，預設讀取最新產生的一份。",
            "scope_note": "這不是歷史版本清單；每個主題只顯示最新一份可讀報告。",
        }
    )

    assert rendered
    assert "這不是歷史版本清單" in rendered[0]
    assert "latest-report-picker-note" in rendered[0]


def test_empty_report_action_summary_distinguishes_empty_and_running_states() -> None:
    empty_summary = report_center.empty_report_action_summary(
        {
            "mode": "empty",
            "action_label": "建立分析",
            "route_hint": "analysis",
        }
    )
    running_summary = report_center.empty_report_action_summary(
        {
            "mode": "running",
            "action_label": "查看任務",
            "route_hint": "task:first-report-task",
        }
    )

    assert empty_summary == {
        "state": "empty",
        "eyebrow": "建議操作",
        "title": "建立第一份最新版報告",
        "caption": "前往分析工作區建立報告；完成後回到這裡閱讀最新版。",
        "action_label": "建立分析",
        "route_hint": "analysis",
    }
    assert running_summary == {
        "state": "running",
        "eyebrow": "建議操作",
        "title": "先確認背景任務進度",
        "caption": "最新任務還在背景執行；完成前避免重複送出分析。",
        "action_label": "查看任務",
        "route_hint": "task:first-report-task",
    }


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


def test_latest_report_lifecycle_marks_market_freshness_as_actionable_attention() -> None:
    lifecycle = latest_report_lifecycle(
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

    assert lifecycle["overall_state"] == "attention"
    assert lifecycle["primary_action"] == "刷新股價"
    assert lifecycle["primary_action_detail"] == (
        "刷新股價可改善「股價與量能」：有 1 檔股價落後資料庫最新交易日 2026-06-05。"
    )
    assert lifecycle["route_hint"] == "data_enrichment:market_refresh:2330,2382"
    assert stage_by_key(lifecycle, "data") == {
        "key": "data",
        "title": "資料",
        "state": "attention",
        "label": "股價落後 1 檔",
        "detail": "刷新股價可改善「股價與量能」：有 1 檔股價落後資料庫最新交易日 2026-06-05。",
    }


def test_latest_report_lifecycle_prefills_first_required_data_gap_action() -> None:
    lifecycle = latest_report_lifecycle(
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

    assert lifecycle["overall_state"] == "attention"
    assert lifecycle["primary_action"] == "刷新股價"
    assert lifecycle["route_hint"] == "data_enrichment:market_refresh:2330"
    assert lifecycle["primary_action_detail"] == "刷新股價可改善「股價與量能」：缺少最新股價"


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


def test_latest_report_lifecycle_marks_blocked_follow_up_as_blocked() -> None:
    lifecycle = latest_report_lifecycle(
        {
            "report_id": 36,
            "topic": "記憶體產業鏈",
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 8}},
            "candidate_whitelist": [],
            "auto_follow_up": {
                "rerun_report": {
                    "status": "skipped",
                    "blockers": ["公司公開文件仍不足：2408"],
                }
            },
        },
        {"summary": {"required_count": 0}, "status": "blocked"},
    )

    assert lifecycle["overall_state"] == "blocked"
    assert lifecycle["trust_label"] == "不可直接採信"
    assert lifecycle["primary_action"] == "查看阻塞"
    assert lifecycle["route_hint"] == "settings:maintenance"
    assert stage_by_key(lifecycle, "follow_up") == {
        "key": "follow_up",
        "title": "補強",
        "state": "blocked",
        "label": "補強受阻",
        "detail": "補強或重跑流程遇到阻塞，先查看失敗原因再採信最新版。",
    }
    assert stage_by_key(lifecycle, "readable")["state"] == "blocked"


def test_latest_report_lifecycle_handles_empty_report() -> None:
    lifecycle = latest_report_lifecycle({}, {})

    assert lifecycle["overall_state"] == "attention"
    assert lifecycle["trust_label"] == "尚未有最新版報告"
    assert lifecycle["primary_action"] == "建立分析"
    assert lifecycle["route_hint"] == "analysis"
    assert stage_by_key(lifecycle, "data")["state"] == "unknown"


def test_latest_report_lifecycle_marks_missing_quality_gate_as_unknown_attention() -> None:
    lifecycle = latest_report_lifecycle(
        {
            "report_id": 29,
            "topic": "機器人供應鏈",
            "tickers": ["2357", "2308"],
            "candidate_whitelist": [{"ticker": "2357"}, {"ticker": "2308"}],
        },
        {"summary": {"required_count": 0}, "status": "ready"},
    )

    assert lifecycle["overall_state"] == "attention"
    assert lifecycle["trust_label"] == "可閱讀但需註記"
    assert "尚無法判斷品質門檻" in lifecycle["trust_explanation"]
    assert lifecycle["primary_action"] == "確認品質門檻"
    assert lifecycle["route_hint"] == "report:29"
    assert stage_by_key(lifecycle, "quality") == {
        "key": "quality",
        "title": "品質",
        "state": "unknown",
        "label": "尚無 Gate",
        "detail": "尚無法判斷品質門檻；不要把 ticker 清單視為正式分析結果。",
    }
    assert stage_by_key(lifecycle, "readable")["state"] == "attention"
    assert stage_by_key(lifecycle, "readable")["label"] == "需人工確認"


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


def test_report_lifecycle_strip_renders_primary_action_detail(monkeypatch) -> None:
    rendered: list[str] = []
    monkeypatch.setattr(
        report_center.st,
        "markdown",
        lambda body, **_kwargs: rendered.append(str(body)),
    )

    report_center._render_report_lifecycle_strip(
        {
            "overall_state": "attention",
            "trust_label": "可閱讀但需註記",
            "trust_explanation": "仍有 1 項必補缺口。",
            "primary_action": "刷新股價",
            "primary_action_detail": "刷新股價可改善「股價與量能」：缺少最新股價",
            "stage_cards": [],
        }
    )

    assert "刷新股價可改善「股價與量能」：缺少最新股價" in rendered[0]


def test_report_reader_decision_summary_combines_lifecycle_and_health() -> None:
    summary = report_center.report_reader_decision_summary(
        {
            "overall_state": "attention",
            "trust_label": "可閱讀但需註記",
            "trust_explanation": "AI 產業鏈報告仍有 2 項必補缺口。",
            "primary_action": "刷新股價",
            "primary_action_detail": "刷新股價可改善「股價與量能」：缺少最新股價",
        },
        {
            "quality_label": "caution",
            "report_meta_label": "#12｜AI 產業鏈｜2026-06-10 15:30",
            "candidate_label": "候選 2｜正式 1",
            "follow_up_label": "需補強 2 項",
        },
    )

    assert summary == {
        "state": "attention",
        "eyebrow": "閱讀決策",
        "title": "可先閱讀，但投資判斷需標示限制",
        "caption": "AI 產業鏈報告仍有 2 項必補缺口。",
        "evidence": "#12｜AI 產業鏈｜2026-06-10 15:30",
        "quality": "品質 caution｜候選 2｜正式 1",
        "follow_up": "補強 需補強 2 項",
        "action_label": "刷新股價",
        "action_detail": "刷新股價可改善「股價與量能」：缺少最新股價",
    }


def test_report_reader_decision_summary_marks_blocked_reports_as_do_not_trust() -> None:
    summary = report_center.report_reader_decision_summary(
        {
            "overall_state": "blocked",
            "trust_label": "不可直接採信",
            "trust_explanation": "散熱產業鏈報告目前正式分析 0 檔。",
            "primary_action": "補強資料",
        },
        {
            "quality_label": "insufficient",
            "candidate_label": "候選 2｜正式 0",
            "follow_up_label": "補強受阻",
        },
    )

    assert summary["state"] == "blocked"
    assert summary["title"] == "暫停採信，先處理阻塞"
    assert summary["action_detail"] == "完成建議操作後再回來閱讀最新版。"


def test_report_reader_decision_summary_uses_blocked_health_as_guardrail() -> None:
    summary = report_center.report_reader_decision_summary(
        {
            "overall_state": "ready",
            "trust_label": "可閱讀",
            "trust_explanation": "記憶體產業鏈報告可作為最新版閱讀。",
            "primary_action": "閱讀最新版",
            "primary_action_detail": "開啟目前保留的最新版報告。",
        },
        {
            "state": "blocked",
            "action_label": "查看阻塞",
            "quality_label": "ready",
            "candidate_label": "候選 0｜正式 8",
            "follow_up_label": "補強受阻",
        },
    )

    assert summary["state"] == "blocked"
    assert summary["title"] == "暫停採信，先處理阻塞"
    assert summary["action_label"] == "查看阻塞"
    assert summary["action_detail"] == "完成建議操作後再回來閱讀最新版。"


def test_report_reader_decision_summary_renders_operator_cards(monkeypatch) -> None:
    rendered: list[str] = []
    monkeypatch.setattr(
        report_center.st,
        "markdown",
        lambda body, **_kwargs: rendered.append(str(body)),
    )

    report_center._render_report_reader_decision_summary(
        {
            "state": "ready",
            "eyebrow": "閱讀決策",
            "title": "可以閱讀最新版",
            "caption": "記憶體產業鏈報告可作為最新版閱讀。",
            "evidence": "#15｜記憶體產業鏈｜2026-06-10 15:30",
            "quality": "品質 ready｜候選 2｜正式 2",
            "follow_up": "補強 可閱讀",
            "action_label": "閱讀最新版",
            "action_detail": "開啟目前保留的最新版報告。",
        }
    )

    assert "report-reader-decision" in rendered[0]
    assert "閱讀決策" in rendered[0]
    assert "可以閱讀最新版" in rendered[0]
    assert "#15｜記憶體產業鏈｜2026-06-10 15:30" in rendered[0]
