from __future__ import annotations

from app.ui.operator_decisions import operator_next_best_action, operator_secondary_actions


READY_QUEUE = {"task_queue": {"ready": True, "processing_ready": True, "worker_online": True}}


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
    assert action["title"] == "先修復背景任務"
    assert action["action_label"] == "查看維護"
    assert action["route_hint"] == "settings:maintenance"


def test_operator_next_action_prompts_report_creation_when_missing() -> None:
    action = operator_next_best_action(READY_QUEUE, {}, {}, [], {}, {})

    assert action["state"] == "attention"
    assert action["title"] == "先建立最新版報告"
    assert action["action_label"] == "建立分析"
    assert action["route_hint"] == "analysis"


def test_operator_next_action_prioritizes_zero_formal_tickers() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {},
        {},
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
    assert action["title"] == "先確認報告可信度"
    assert action["reason"] == "最新版報告目前不可直接採信。"
    assert action["action_label"] == "查看報告生命週期"
    assert action["route_hint"] == "report:18"


def test_operator_next_action_prioritizes_required_data_gaps() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {},
        {},
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
    assert action["title"] == "先補強最新版報告資料"
    assert action["action_label"] == "補強資料"
    assert action["route_hint"] == "data_enrichment"


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
    assert action["title"] == "等待額度或查看 fallback"
    assert action["action_label"] == "查看額度"
    assert action["route_hint"] == "settings:ai_quota"


def test_operator_next_action_reads_latest_when_healthy() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {},
        {},
        [{"id": 15, "title": "AI 產業鏈"}],
        {
            "report_id": 15,
            "topic": "AI 產業鏈",
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}},
            "candidate_whitelist": [{"ticker": "2330"}, {"ticker": "2382"}],
        },
        {"summary": {"required_count": 0}},
    )

    assert action["state"] == "ready"
    assert action["title"] == "閱讀最新版報告"
    assert action["action_label"] == "讀報告"
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
        {},
        [{"id": 15, "title": "AI 產業鏈"}],
        {
            "report_id": 15,
            "topic": "AI 產業鏈",
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}},
            "candidate_whitelist": [{"ticker": "2330"}, {"ticker": "2382"}],
        },
        {"summary": {"required_count": 0}},
    )

    assert actions[0]["title"] == "白名單或輸入擋下任務"
    assert actions[0]["route_hint"] == "task:abc"
