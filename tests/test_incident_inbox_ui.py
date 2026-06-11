from __future__ import annotations

from app.ui import system_settings_maintenance
from app.ui.incident_inbox import incident_counts, incident_inbox_items, top_incidents


def test_incident_inbox_reports_queue_unavailable() -> None:
    incidents = incident_inbox_items(
        {
            "task_queue": {
                "ready": False,
                "processing_ready": False,
                "worker_online": False,
            }
        },
        {"totals": {"stale_running_count": 0}},
        {},
    )

    assert incidents[0]["severity"] == "critical"
    assert incidents[0]["category"] == "task_queue"
    assert incidents[0]["title"] == "背景任務未就緒"
    assert incidents[0]["route_hint"] == "settings:maintenance"


def test_incident_inbox_reports_stale_running_task() -> None:
    incidents = incident_inbox_items(
        {
            "task_queue": {
                "ready": True,
                "processing_ready": True,
                "worker_online": True,
            }
        },
        {"totals": {"stale_running_count": 2}},
        {},
    )

    assert incidents[0]["severity"] == "critical"
    assert incidents[0]["title"] == "有 2 個任務疑似卡住"
    assert incidents[0]["dedupe_key"] == "task_queue:stale_running"


def test_incident_inbox_deduplicates_stale_running_alert_with_totals() -> None:
    incidents = incident_inbox_items(
        {
            "task_queue": {
                "ready": True,
                "processing_ready": True,
                "worker_online": True,
            }
        },
        {
            "totals": {"stale_running_count": 1},
            "alerts": [
                {
                    "severity": "error",
                    "code": "task_stale_running",
                    "message": "stale running task detected",
                }
            ],
        },
        {},
    )

    stale_incidents = [
        item for item in incidents if item["dedupe_key"] == "task_queue:stale_running"
    ]
    assert len(incidents) == 1
    assert len(stale_incidents) == 1


def test_incident_inbox_deduplicates_recent_failures() -> None:
    failure = {
        "task_id": "abc",
        "operation": "market_refresh",
        "status": "failed",
        "error_category": "payload_validation",
        "retryable": True,
        "finished_at": "2026-06-10T09:30:00",
    }
    incidents = incident_inbox_items(
        {
            "task_queue": {
                "ready": True,
                "processing_ready": True,
                "worker_online": True,
            }
        },
        {"recent_failures": [failure], "recent": [failure]},
        {},
    )

    whitelist_incidents = [item for item in incidents if item["category"] == "whitelist"]
    assert len(whitelist_incidents) == 1
    assert whitelist_incidents[0]["title"] == "白名單或輸入擋下任務"
    assert whitelist_incidents[0]["retryable"] is True
    assert whitelist_incidents[0]["route_hint"] == "task:abc"
    assert whitelist_incidents[0]["action_label"] == "重試任務"


def test_incident_inbox_labels_manual_failures_for_operator_review() -> None:
    incidents = incident_inbox_items(
        {
            "task_queue": {
                "ready": True,
                "processing_ready": True,
                "worker_online": True,
            }
        },
        {
            "recent_failures": [
                {
                    "task_id": "store-1",
                    "operation": "report_write",
                    "status": "failed",
                    "error_category": "runtime_storage",
                    "retryable": False,
                }
            ]
        },
        {},
    )

    assert incidents[0]["category"] == "runtime_storage"
    assert incidents[0]["action_label"] == "檢查任務"


def test_incident_inbox_reports_quota_pressure() -> None:
    incidents = incident_inbox_items(
        {
            "task_queue": {
                "ready": True,
                "processing_ready": True,
                "worker_online": True,
            }
        },
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
    )

    assert incidents[0]["category"] == "quota"
    assert incidents[0]["severity"] == "warning"
    assert incidents[0]["title"] == "AI 額度需注意"
    assert incidents[0]["source"] == "gemini-3.5-flash"


def test_incident_inbox_maps_task_alert_error_category() -> None:
    incidents = incident_inbox_items(
        {
            "task_queue": {
                "ready": True,
                "processing_ready": True,
                "worker_online": True,
            }
        },
        {
            "alerts": [
                {
                    "severity": "warning",
                    "error_category": "quota",
                    "code": "quota_warning",
                    "message": "額度不足",
                }
            ]
        },
        {},
    )

    assert incidents[0]["category"] == "quota"
    assert incidents[0]["title"] == "額度不足"
    assert "quota_warning" in incidents[0]["dedupe_key"]


def test_incident_inbox_preserves_allowed_raw_failure_category() -> None:
    incidents = incident_inbox_items(
        {
            "task_queue": {
                "ready": True,
                "processing_ready": True,
                "worker_online": True,
            }
        },
        {
            "recent_failures": [
                {
                    "id": 31,
                    "task_id": "quota-task",
                    "operation": "report_generation",
                    "status": "failed",
                    "error_category": "quota",
                    "finished_at": "2026-06-10T09:30:00",
                }
            ]
        },
        {},
    )

    assert incidents[0]["category"] == "quota"
    assert incidents[0]["source"] == "quota-task"
    assert incidents[0]["title"] == "AI 額度需注意"
    assert "unknown" not in incidents[0]["impact"].casefold()


def test_incident_inbox_prefers_failure_payload_summary_action_and_severity() -> None:
    incidents = incident_inbox_items(
        {
            "task_queue": {
                "ready": True,
                "processing_ready": True,
                "worker_online": True,
            }
        },
        {
            "recent_failures": [
                {
                    "id": 41,
                    "operation": "follow_up_api",
                    "status": "failed",
                    "error_category": "external_config",
                    "error_summary": "Structured API 未設定",
                    "next_action": "設定 API key",
                    "error_severity": "error",
                    "finished_at": "2026-06-10T09:45:00",
                }
            ]
        },
        {},
    )

    assert incidents[0]["category"] == "external_config"
    assert incidents[0]["severity"] == "critical"
    assert incidents[0]["title"] == "Structured API 未設定"
    assert incidents[0]["next_action"] == "設定 API key"


def test_incident_inbox_dedupes_same_task_id_to_newest_failure() -> None:
    incidents = incident_inbox_items(
        {
            "task_queue": {
                "ready": True,
                "processing_ready": True,
                "worker_online": True,
            }
        },
        {
            "recent_failures": [
                {
                    "id": 51,
                    "task_id": "abc",
                    "operation": "report_generation",
                    "status": "failed",
                    "error_category": "external_config",
                    "error_summary": "舊錯",
                    "finished_at": "2026-06-10T09:00:00",
                },
                {
                    "id": 52,
                    "task_id": "abc",
                    "operation": "report_generation",
                    "status": "failed",
                    "error_category": "external_config",
                    "error_summary": "新錯",
                    "finished_at": "2026-06-10T10:00:00",
                },
            ]
        },
        {},
    )

    matching = [item for item in incidents if item["dedupe_key"] == "failure:external_config:task:abc"]
    assert len(matching) == 1
    assert matching[0]["title"] == "新錯"
    assert matching[0]["created_at"] == "2026-06-10T10:00:00"


def test_incident_inbox_keeps_distinct_runs_without_task_id() -> None:
    incidents = incident_inbox_items(
        {
            "task_queue": {
                "ready": True,
                "processing_ready": True,
                "worker_online": True,
            }
        },
        {
            "recent_failures": [
                {
                    "id": 61,
                    "operation": "report_generation",
                    "status": "failed",
                    "error_category": "external_config",
                    "error_summary": "run 61",
                    "finished_at": "2026-06-10T09:00:00",
                },
                {
                    "id": 62,
                    "operation": "report_generation",
                    "status": "failed",
                    "error_category": "external_config",
                    "error_summary": "run 62",
                    "finished_at": "2026-06-10T09:05:00",
                },
            ]
        },
        {},
    )

    assert {item["dedupe_key"] for item in incidents} == {
        "failure:external_config:run:61",
        "failure:external_config:run:62",
    }


def test_incident_inbox_reports_report_lifecycle_blocker() -> None:
    incidents = incident_inbox_items(
        {
            "task_queue": {
                "ready": True,
                "processing_ready": True,
                "worker_online": True,
            }
        },
        {},
        {},
        {
            "overall_state": "blocked",
            "trust_label": "不可直接採信",
            "trust_explanation": "正式分析 0 檔。",
            "primary_action": "補強資料",
            "route_hint": "data_enrichment",
            "report_id": 18,
        },
    )

    assert incidents[0]["category"] == "report_quality"
    assert incidents[0]["severity"] == "critical"
    assert incidents[0]["source"] == "report:18"
    assert incident_counts(incidents) == {"critical": 1, "warning": 0, "info": 0}


def test_top_incidents_limits_sorted_results() -> None:
    incidents = [
        {"id": "info", "severity": "info", "category": "quota", "retryable": False},
        {"id": "warning", "severity": "warning", "category": "whitelist", "retryable": True},
        {"id": "critical", "severity": "critical", "category": "task_queue", "retryable": False},
    ]

    assert [item["id"] for item in top_incidents(incidents, limit=2)] == [
        "critical",
        "warning",
    ]


def test_top_incidents_sorts_newer_events_before_older_peers() -> None:
    incidents = [
        {
            "id": "old",
            "severity": "warning",
            "category": "quota",
            "retryable": False,
            "created_at": "2026-06-10T09:00:00",
        },
        {
            "id": "new",
            "severity": "warning",
            "category": "quota",
            "retryable": False,
            "created_at": "2026-06-10T10:00:00",
        },
    ]

    assert [item["id"] for item in top_incidents(incidents)] == ["new", "old"]


def test_incident_action_summaries_use_grouped_incident_cards() -> None:
    incidents = [
        {
            "id": "old",
            "severity": "warning",
            "category": "quota",
            "title": "AI 額度需注意",
            "impact": "模型額度不足。",
            "next_action": "查看額度頁。",
            "action_label": "查看額度",
            "route_hint": "settings:ai_quota",
            "retryable": False,
            "source": "gemini-3.5-flash",
            "created_at": "2026-06-10T09:00:00",
        },
        {
            "id": "new",
            "severity": "warning",
            "category": "quota",
            "title": "AI 額度需注意",
            "impact": "模型額度不足。",
            "next_action": "查看額度頁。",
            "action_label": "查看額度",
            "route_hint": "settings:ai_quota",
            "retryable": False,
            "source": "gemini-2.5-flash",
            "created_at": "2026-06-10T10:00:00",
        },
    ]

    summaries = system_settings_maintenance.incident_action_summaries(incidents)

    assert len(summaries) == 1
    assert summaries[0]["id"] == "new"
    assert summaries[0]["repeat_count"] == 2
    assert summaries[0]["hidden_count"] == 1
    assert summaries[0]["source_ids"] == ["gemini-3.5-flash", "gemini-2.5-flash"]
    assert system_settings_maintenance.incident_action_caption(summaries[0]) == (
        "AI 額度需注意｜同類事件 2 筆"
    )
