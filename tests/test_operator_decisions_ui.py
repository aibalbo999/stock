from __future__ import annotations

from app.ui.operator_decisions import operator_next_best_action, operator_secondary_actions


READY_QUEUE = {"task_queue": {"ready": True, "processing_ready": True, "worker_online": True}}
READY_QUOTA = {
    "recommended_model": "gemini-3.5-flash",
    "models": [
        {
            "model": "gemini-3.5-flash",
            "status": "ready",
            "requests_remaining": 42,
            "request_budget": 1500,
        }
    ],
}
HEALTHY_REPORT = {
    "report_id": 15,
    "topic": "AI 產業鏈",
    "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}},
    "candidate_whitelist": [{"ticker": "2330"}, {"ticker": "2382"}],
}


def test_operator_next_action_prioritizes_queue_blocker() -> None:
    action = operator_next_best_action(
        {"task_queue": {"ready": False, "processing_ready": False, "worker_online": False}},
        {},
        {},
        [{"id": 15, "title": "AI 產業鏈"}],
        {"report_id": 15, "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}}},
        {"summary": {"required_count": 0}},
    )

    assert action["state"] == "blocked"
    assert action["priority"] == 1
    assert action["title"] == "先修復背景任務"
    assert action["action_label"] == "查看維護"
    assert action["route_hint"] == "settings:maintenance"


def test_operator_next_action_treats_missing_service_status_as_attention_not_queue_failure() -> None:
    action = operator_next_best_action(
        {},
        {},
        READY_QUOTA,
        [{"id": 15, "title": "AI 產業鏈"}],
        HEALTHY_REPORT,
        {"summary": {"required_count": 0}},
    )

    assert action["state"] == "attention"
    assert action["priority"] == 1
    assert action["title"] == "確認系統狀態"
    assert "目前無法讀取系統狀態" in action["reason"]
    assert "不代表背景任務已壞掉" in action["risk"]
    assert action["action_label"] == "查看維護"
    assert action["route_hint"] == "settings:maintenance"


def test_operator_next_action_distinguishes_stale_running_from_queue_unavailable() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {"totals": {"stale_running_count": 2}},
        READY_QUOTA,
        [{"id": 15, "title": "AI 產業鏈"}],
        HEALTHY_REPORT,
        {"summary": {"required_count": 0}},
    )

    assert action["state"] == "blocked"
    assert action["priority"] == 2
    assert action["title"] == "檢查卡住的背景任務"
    assert "2 個任務疑似卡住" in action["reason"]
    assert action["action_label"] == "查看任務"
    assert action["route_hint"] == "settings:maintenance"


def test_operator_next_action_distinguishes_stale_running_alert() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {
            "alerts": [
                {
                    "code": "stale_running_tasks",
                    "severity": "error",
                    "message": "有任務疑似卡住",
                    "next_steps": ["查看背景任務", "重試可重試任務"],
                }
            ]
        },
        READY_QUOTA,
        [{"id": 15, "title": "AI 產業鏈"}],
        HEALTHY_REPORT,
        {"summary": {"required_count": 0}},
    )

    assert action["state"] == "blocked"
    assert action["priority"] == 2
    assert action["title"] == "檢查卡住的背景任務"
    assert action["reason"] == "有任務疑似卡住"
    assert action["impact"] == "查看背景任務；重試可重試任務"
    assert action["action_label"] == "查看維護"


def test_operator_next_action_prompts_report_creation_when_missing() -> None:
    action = operator_next_best_action(READY_QUEUE, {}, {}, [], {}, {})

    assert action["state"] == "attention"
    assert action["priority"] == 3
    assert action["title"] == "先建立最新版報告"
    assert action["action_label"] == "建立分析"
    assert action["route_hint"] == "analysis"


def test_operator_next_action_waits_for_running_first_report_task() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {
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
        READY_QUOTA,
        [],
        {},
        {},
    )

    assert action["state"] == "attention"
    assert action["priority"] == 3
    assert action["title"] == "等待最新任務完成"
    assert "尚未產生可閱讀的最新版報告" in action["reason"]
    assert "重複送出同類任務" in action["risk"]
    assert action["action_label"] == "查看任務進度"
    assert action["route_hint"] == "task:first-report-task"
    assert action["source_ids"] == ["first-report-task"]


def test_operator_next_action_reads_report_status_when_only_list_row_exists() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {},
        READY_QUOTA,
        [{"id": 15, "title": "AI 產業鏈"}],
        {},
        {},
    )

    assert action["state"] == "attention"
    assert action["priority"] == 3
    assert action["title"] == "先讀取最新版報告狀態"
    assert action["title"] != "先確認報告可信度"
    assert action["title"] != "閱讀最新版報告"
    assert action["route_hint"] == "report:15"


def test_operator_next_action_prioritizes_zero_formal_tickers() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {},
        READY_QUOTA,
        [{"id": 18, "title": "散熱產業鏈"}],
        {
            "report_id": 18,
            "topic": "散熱產業鏈",
            "quality_gate": {"status": "caution", "metrics": {"promoted_count": 0}},
            "candidate_whitelist": [{"ticker": "3017"}],
        },
        {"summary": {"required_count": 0}},
    )

    assert action["state"] == "blocked"
    assert action["priority"] == 4
    assert action["title"] == "先確認報告可信度"
    assert action["reason"] == "最新版報告目前不可直接採信。"
    assert action["action_label"] == "查看報告生命週期"
    assert action["route_hint"] == "report:18"


def test_operator_next_action_prioritizes_required_data_gaps() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {},
        READY_QUOTA,
        [{"id": 12, "title": "AI 產業鏈"}],
        {
            "report_id": 12,
            "topic": "AI 產業鏈",
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}},
            "candidate_whitelist": [{"ticker": "2330"}, {"ticker": "2382"}],
        },
        {"summary": {"required_count": 2}, "status": "needs_follow_up"},
    )

    assert action["state"] == "attention"
    assert action["priority"] == 5
    assert action["title"] == "先補強最新版報告資料"
    assert action["action_label"] == "補強資料"
    assert action["route_hint"] == "data_enrichment"


def test_operator_next_action_prefills_first_required_data_gap_action() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {},
        READY_QUOTA,
        [{"id": 12, "title": "AI 產業鏈"}],
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

    assert action["state"] == "attention"
    assert action["priority"] == 5
    assert action["action_label"] == "刷新股價"
    assert action["route_hint"] == "data_enrichment:market_refresh:2330"
    assert "刷新股價可改善" in action["impact"]
    assert "2330" in action["source_ids"]


def test_operator_next_action_surfaces_quality_warning_before_healthy_read() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {},
        READY_QUOTA,
        [{"id": 15, "title": "AI 產業鏈"}],
        {
            "report_id": 15,
            "topic": "AI 產業鏈",
            "quality_gate": {"status": "caution", "metrics": {"promoted_count": 2}},
            "candidate_whitelist": [{"ticker": "2330"}, {"ticker": "2382"}],
        },
        {"summary": {"required_count": 0}},
    )

    assert action["state"] == "attention"
    assert action["priority"] == 4
    assert action["title"] == "先確認報告品質警示"
    assert action["route_hint"] == "report:15"


def test_operator_next_action_surfaces_missing_quality_gate_before_healthy_read() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {},
        READY_QUOTA,
        [{"id": 29, "title": "機器人供應鏈"}],
        {
            "report_id": 29,
            "topic": "機器人供應鏈",
            "tickers": ["2357", "2308"],
            "candidate_whitelist": [{"ticker": "2357"}, {"ticker": "2308"}],
        },
        {"summary": {"required_count": 0}, "status": "ready"},
    )

    assert action["state"] == "attention"
    assert action["priority"] == 4
    assert action["title"] == "先確認報告品質狀態"
    assert "品質門檻" in action["reason"]
    assert action["action_label"] == "查看報告生命週期"
    assert action["route_hint"] == "report:29"


def test_operator_next_action_surfaces_quota_pressure_after_report_gates() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {},
        {
            "recommended_model": "gemini-3.5-flash",
            "models": [
                {
                    "model": "gemini-3.5-flash",
                    "status": "blocked",
                    "requests_remaining": 0,
                    "request_budget": 1500,
                }
            ],
        },
        [{"id": 15, "title": "AI 產業鏈"}],
        {
            "report_id": 15,
            "topic": "AI 產業鏈",
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}},
            "candidate_whitelist": [{"ticker": "2330"}, {"ticker": "2382"}],
        },
        {"summary": {"required_count": 0}},
    )

    assert action["state"] == "attention"
    assert action["priority"] == 8
    assert action["title"] == "等待額度或查看 fallback"
    assert action["action_label"] == "查看額度"
    assert action["route_hint"] == "settings:ai_quota"


def test_operator_next_action_surfaces_market_freshness_after_quota_is_ready() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {},
        READY_QUOTA,
        [{"id": 15, "title": "AI 產業鏈"}],
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

    assert action["state"] == "attention"
    assert action["priority"] == 9
    assert action["title"] == "先刷新股價"
    assert action["reason"] == (
        "刷新股價可改善「股價與量能」：有 1 檔股價落後資料庫最新交易日 2026-06-05。"
    )
    assert "閱讀前" in action["risk"]
    assert action["action_label"] == "刷新股價"
    assert action["route_hint"] == "data_enrichment:market_refresh:2330,2382"
    assert action["source_ids"] == ["report:15", "2330", "2382"]


def test_operator_next_action_prioritizes_retryable_failure_affecting_latest_report() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {
            "recent_failures": [
                {
                    "id": 88,
                    "task_id": "retry-latest-1",
                    "report_id": 15,
                    "operation": "market_refresh",
                    "status": "failed",
                    "error_category": "data_source",
                    "error_summary": "股價刷新暫時失敗",
                    "next_action": "重試股價刷新任務",
                    "retryable": True,
                    "finished_at": "2026-06-10T10:00:00",
                }
            ]
        },
        READY_QUOTA,
        [{"id": 15, "title": "AI 產業鏈"}],
        HEALTHY_REPORT,
        {"summary": {"required_count": 0}},
    )

    assert action["state"] == "attention"
    assert action["priority"] == 7
    assert action["title"] == "重試影響最新版報告的任務"
    assert action["reason"] == "股價刷新暫時失敗"
    assert action["action_label"] == "重試任務"
    assert action["route_hint"] == "task:retry-latest-1"
    assert action["source_ids"] == ["report:15", "retry-latest-1"]


def test_operator_next_action_does_not_block_healthy_report_when_quota_missing() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {},
        {},
        [{"id": 15, "title": "AI 產業鏈"}],
        HEALTHY_REPORT,
        {"summary": {"required_count": 0}},
    )

    assert action["state"] == "ready"
    assert action["priority"] == 10
    assert action["title"] == "閱讀最新版報告"
    assert "模型額度狀態暫不可讀" in action["reason"]
    assert "閱讀現有報告不消耗額度" in action["risk"]
    assert action["action_label"] == "讀報告"
    assert action["route_hint"] == "report:15"


def test_operator_next_action_promotes_non_queue_critical_incident() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {
            "recent_failures": [
                {
                    "task_id": "disk-1",
                    "operation": "report_write",
                    "status": "failed",
                    "error_category": "runtime_storage",
                    "error_severity": "error",
                    "retryable": False,
                }
            ]
        },
        READY_QUOTA,
        [{"id": 15, "title": "AI 產業鏈"}],
        HEALTHY_REPORT,
        {"summary": {"required_count": 0}},
    )

    assert action["state"] == "blocked"
    assert action["priority"] == 7
    assert action["title"] == "本機儲存失敗"
    assert action["route_hint"] == "task:disk-1"


def test_operator_next_action_does_not_promote_historical_failure_when_latest_task_healthy() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {
            "latest": {
                "task_id": "smoke-ok",
                "operation": "submission_smoke",
                "status": "success",
                "successful": True,
            },
            "recent_failures": [
                {
                    "task_id": "old-disk-1",
                    "operation": "report_write",
                    "status": "failed",
                    "error_category": "runtime_storage",
                    "error_severity": "error",
                    "retryable": False,
                    "finished_at": "2026-06-09T09:00:00",
                }
            ],
        },
        READY_QUOTA,
        [{"id": 15, "title": "AI 產業鏈"}],
        HEALTHY_REPORT,
        {"summary": {"required_count": 0}},
    )

    assert action["state"] == "ready"
    assert action["priority"] == 10
    assert action["title"] == "閱讀最新版報告"
    assert action["route_hint"] == "report:15"


def test_operator_secondary_actions_keep_historical_failure_when_latest_task_healthy() -> None:
    actions = operator_secondary_actions(
        READY_QUEUE,
        {
            "latest": {
                "task_id": "smoke-ok",
                "operation": "submission_smoke",
                "celery_status": "SUCCESS",
            },
            "recent_failures": [
                {
                    "task_id": "old-disk-1",
                    "operation": "report_write",
                    "status": "failed",
                    "error_category": "runtime_storage",
                    "error_severity": "error",
                    "retryable": False,
                    "finished_at": "2026-06-09T09:00:00",
                }
            ],
        },
        READY_QUOTA,
        [{"id": 15, "title": "AI 產業鏈"}],
        HEALTHY_REPORT,
        {"summary": {"required_count": 0}},
    )

    assert any(action["title"] == "本機儲存失敗" for action in actions)


def test_operator_next_action_reads_latest_when_healthy() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {},
        READY_QUOTA,
        [{"id": 15, "title": "AI 產業鏈"}],
        HEALTHY_REPORT,
        {"summary": {"required_count": 0}},
    )

    assert action["state"] == "ready"
    assert action["priority"] == 10
    assert action["title"] == "閱讀最新版報告"
    assert action["action_label"] == "讀報告"
    assert action["route_hint"] == "report:15"


def test_operator_next_action_keeps_report_readable_when_task_summary_missing() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {},
        READY_QUOTA,
        [{"id": 15, "title": "AI 產業鏈"}],
        HEALTHY_REPORT,
        {"summary": {"required_count": 0}},
    )

    assert action["state"] == "ready"
    assert action["title"] == "閱讀最新版報告"
    assert action["route_hint"] == "report:15"


def test_operator_secondary_actions_show_ranked_incidents() -> None:
    actions = operator_secondary_actions(
        READY_QUEUE,
        {
            "recent_failures": [
                {
                    "task_id": "abc",
                    "operation": "market_refresh",
                    "status": "failed",
                    "error_category": "payload_validation",
                    "retryable": True,
                }
            ]
        },
        READY_QUOTA,
        [{"id": 15, "title": "AI 產業鏈"}],
        HEALTHY_REPORT,
        {"summary": {"required_count": 0}},
    )

    assert actions[0]["title"] == "白名單或輸入擋下任務"
    assert actions[0]["action_label"] == "重試任務"
    assert actions[0]["route_hint"] == "task:abc"


def test_operator_secondary_actions_hide_primary_queue_blocker() -> None:
    actions = operator_secondary_actions(
        {"task_queue": {"ready": False, "processing_ready": False, "worker_online": False}},
        {
            "recent_failures": [
                {
                    "task_id": "abc",
                    "operation": "market_refresh",
                    "status": "failed",
                    "error_category": "payload_validation",
                    "retryable": True,
                }
            ]
        },
        READY_QUOTA,
        [{"id": 15, "title": "AI 產業鏈"}],
        HEALTHY_REPORT,
        {"summary": {"required_count": 0}},
    )

    assert all(action["title"] != "背景任務未就緒" for action in actions)
    assert any(action["title"] == "白名單或輸入擋下任務" for action in actions)


def test_operator_secondary_actions_keep_distinct_incident_with_same_route() -> None:
    actions = operator_secondary_actions(
        {"task_queue": {"ready": False, "processing_ready": False, "worker_online": False}},
        {
            "recent_failures": [
                {
                    "operation": "report_write",
                    "status": "failed",
                    "error_category": "runtime_storage",
                    "error_severity": "error",
                    "retryable": False,
                }
            ]
        },
        READY_QUOTA,
        [{"id": 15, "title": "AI 產業鏈"}],
        HEALTHY_REPORT,
        {"summary": {"required_count": 0}},
    )

    assert any(action["title"] == "本機儲存失敗" for action in actions)
    assert any(action["route_hint"] == "settings:maintenance" for action in actions)


def test_operator_secondary_actions_hide_primary_report_route_action() -> None:
    primary = operator_next_best_action(
        READY_QUEUE,
        {},
        READY_QUOTA,
        [{"id": 18, "title": "散熱產業鏈"}],
        {
            "report_id": 18,
            "topic": "散熱產業鏈",
            "quality_gate": {"status": "caution", "metrics": {"promoted_count": 0}},
            "candidate_whitelist": [{"ticker": "3017"}],
        },
        {"summary": {"required_count": 0}},
    )
    actions = operator_secondary_actions(
        READY_QUEUE,
        {},
        READY_QUOTA,
        [{"id": 18, "title": "散熱產業鏈"}],
        {
            "report_id": 18,
            "topic": "散熱產業鏈",
            "quality_gate": {"status": "caution", "metrics": {"promoted_count": 0}},
            "candidate_whitelist": [{"ticker": "3017"}],
        },
        {"summary": {"required_count": 0}},
        primary_action=primary,
    )

    assert primary["route_hint"] == "report:18"
    assert all(action["route_hint"] != "report:18" for action in actions)


def test_operator_secondary_actions_hide_primary_data_gap_action() -> None:
    primary = operator_next_best_action(
        READY_QUEUE,
        {},
        READY_QUOTA,
        [{"id": 12, "title": "AI 產業鏈"}],
        {
            "report_id": 12,
            "topic": "AI 產業鏈",
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}},
            "candidate_whitelist": [{"ticker": "2330"}, {"ticker": "2382"}],
        },
        {"summary": {"required_count": 2}, "status": "needs_follow_up"},
    )
    actions = operator_secondary_actions(
        READY_QUEUE,
        {},
        READY_QUOTA,
        [{"id": 12, "title": "AI 產業鏈"}],
        {
            "report_id": 12,
            "topic": "AI 產業鏈",
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}},
            "candidate_whitelist": [{"ticker": "2330"}, {"ticker": "2382"}],
        },
        {"summary": {"required_count": 2}, "status": "needs_follow_up"},
        primary_action=primary,
    )

    assert primary["route_hint"] == "data_enrichment"
    assert all(action["route_hint"] != "data_enrichment" for action in actions)


def test_operator_primary_action_contains_contract_keys() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {},
        READY_QUOTA,
        [{"id": 15, "title": "AI 產業鏈"}],
        HEALTHY_REPORT,
        {"summary": {"required_count": 0}},
    )

    assert {
        "state",
        "priority",
        "title",
        "reason",
        "risk",
        "impact",
        "action_label",
        "route_hint",
        "source_ids",
    } <= set(action)
    assert isinstance(action["source_ids"], list)
