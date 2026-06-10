from __future__ import annotations

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
        {"models": [], "recommended_model": None},
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
        {"models": [], "recommended_model": None},
    )

    assert incidents[0]["severity"] == "critical"
    assert incidents[0]["title"] == "有 2 個任務疑似卡住"
    assert incidents[0]["dedupe_key"] == "task_queue:stale_running"


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
        {"models": [], "recommended_model": None},
    )

    whitelist_incidents = [item for item in incidents if item["category"] == "whitelist"]
    assert len(whitelist_incidents) == 1
    assert whitelist_incidents[0]["title"] == "白名單或輸入擋下任務"
    assert whitelist_incidents[0]["retryable"] is True
    assert whitelist_incidents[0]["route_hint"] == "task:abc"


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
                    "state": "blocked",
                    "remaining": 0,
                    "limit": 1500,
                }
            ],
        },
    )

    assert incidents[0]["category"] == "quota"
    assert incidents[0]["severity"] == "warning"
    assert incidents[0]["title"] == "AI 額度需注意"
    assert incidents[0]["source"] == "gemini-3.5-flash"


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
