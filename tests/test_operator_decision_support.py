from __future__ import annotations

from app.ui.operator_decision_support import (
    data_gap_action_impact,
    data_gap_action_source_ids,
    healthy_read_reason,
    healthy_read_risk,
    has_report_detail_payload,
    latest_report,
    primary_data_gap_action,
    report_id,
    retryable_failure_affecting_report,
)


def test_primary_data_gap_action_prefers_required_non_followup_operation() -> None:
    action = primary_data_gap_action(
        {"report_id": 12},
        {
            "next_actions": [
                {
                    "action": "report_follow_up",
                    "purpose": "required",
                    "tickers": ["2330"],
                    "target": "追問",
                },
                {
                    "action": "refresh_market",
                    "purpose": "required",
                    "tickers": ["2382"],
                    "target": "股價與量能",
                    "reason": "缺少最新股價",
                },
            ]
        },
    )

    assert action["operation"] == "market_refresh"
    assert action["action_label"] == "刷新股價"
    assert action["route_hint"] == "data_enrichment:market_refresh:2382"


def test_data_gap_action_helpers_preserve_report_and_post_action_context() -> None:
    action = {
        "impact": "刷新股價可改善「股價與量能」。",
        "post_action_hint": "完成後重跑最新版報告。",
        "tickers": ["2330", "2382"],
    }

    assert data_gap_action_impact(action) == (
        "刷新股價可改善「股價與量能」。；完成後重跑最新版報告。"
    )
    assert data_gap_action_source_ids(action, 15) == ["report:15", "2330", "2382"]


def test_healthy_read_messages_allow_existing_report_when_quota_is_missing() -> None:
    assert "模型額度狀態暫不可讀" in healthy_read_reason(quota_missing=True)
    assert "閱讀現有報告不消耗額度" in healthy_read_risk(quota_missing=True)
    assert "模型額度狀態暫不可讀" not in healthy_read_reason(quota_missing=False)


def test_retryable_failure_affecting_report_matches_latest_report_only() -> None:
    failure = retryable_failure_affecting_report(
        {
            "recent_failures": [
                {
                    "task_id": "old",
                    "report_id": 14,
                    "retryable": True,
                },
                {
                    "task_id": "latest",
                    "report_id": 15,
                    "retryable": True,
                },
            ]
        },
        15,
    )

    assert failure["task_id"] == "latest"


def test_report_payload_helpers_detect_latest_detail_and_report_id() -> None:
    reports = [{}, {"id": 15}]
    detail = {"quality_gate": {"status": "ready"}, "report_id": 16}

    assert latest_report(reports) == {}
    assert has_report_detail_payload(detail) is True
    assert report_id(detail, {"id": 15}) == 16
    assert report_id({}, {"id": 15}) == 15
