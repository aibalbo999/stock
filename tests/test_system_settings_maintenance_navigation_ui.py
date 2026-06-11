from __future__ import annotations

import app.ui.system_settings_maintenance as maintenance


def test_incident_summary_cards_group_repeated_operator_noise() -> None:
    incidents = [
        {
            "severity": "warning",
            "category": "data_source",
            "title": "資料來源抓取失敗",
            "impact": "最新版報告可能缺少最新市場或公司資料。",
            "next_action": "到維護頁重試此任務",
            "action_label": "重試任務",
            "route_hint": f"task:refresh-{index}",
            "retryable": True,
        }
        for index in range(3)
    ]
    incidents.append(
        {
            "severity": "critical",
            "category": "runtime_storage",
            "title": "本機儲存失敗",
            "impact": "報告檔案、SQLite 或備份可能沒有寫入成功。",
            "next_action": "到維護頁查看失敗診斷",
            "action_label": "檢查任務",
            "route_hint": "task:storage-1",
            "retryable": False,
        }
    )

    summaries = maintenance.incident_summary_cards(incidents)

    assert len(summaries) == 2
    repeated = summaries[1]
    assert repeated["title"] == "資料來源抓取失敗"
    assert repeated["repeat_count"] == 3
    assert repeated["hidden_count"] == 2
    assert repeated["route_hint"] == "task:refresh-0"
    assert repeated["route_hints"] == ["task:refresh-0", "task:refresh-1", "task:refresh-2"]


def test_render_incident_inbox_uses_grouped_cards_without_losing_counts(monkeypatch) -> None:
    class FakeStreamlit:
        def __init__(self) -> None:
            self.markdown_calls: list[str] = []

        def markdown(self, body: str, **_kwargs) -> None:
            self.markdown_calls.append(body)

    incidents = [
        {
            "severity": "warning",
            "category": "data_source",
            "title": "資料來源抓取失敗",
            "impact": "最新版報告可能缺少最新市場或公司資料。",
            "next_action": "到維護頁重試此任務",
            "action_label": "重試任務",
            "route_hint": f"task:refresh-{index}",
            "retryable": True,
        }
        for index in range(3)
    ]
    captured_action_incidents: list[dict] = []
    fake_st = FakeStreamlit()

    monkeypatch.setattr(maintenance, "st", fake_st)
    monkeypatch.setattr(
        maintenance,
        "_render_incident_action_controls",
        lambda action_incidents: captured_action_incidents.extend(action_incidents),
    )

    maintenance._render_incident_inbox(incidents)

    combined = "\n".join(fake_st.markdown_calls)
    assert "Warning 3" in combined
    assert "incident-priority-summary is-attention" in combined
    assert "先確認 3 個 Warning 事件" in combined
    assert "3 個可重試任務可直接在下方操作" in combined
    assert "0 個為歷史趨勢/觀測" in combined
    assert combined.count("資料來源抓取失敗") == 1
    assert "同類事件 3 筆" in combined
    assert "另有 2 筆同類事件" in combined
    assert captured_action_incidents == incidents


def test_incident_action_priority_summary_prioritizes_retryable_critical_tasks() -> None:
    incidents = [
        {
            "severity": "critical",
            "category": "runtime_storage",
            "title": "本機儲存失敗",
            "route_hint": "task:storage-1",
            "retryable": False,
        },
        {
            "severity": "critical",
            "category": "data_source",
            "title": "資料來源抓取失敗",
            "route_hint": "task:refresh-1",
            "retryable": True,
        },
        {
            "severity": "warning",
            "category": "data_source",
            "title": "資料來源抓取失敗",
            "route_hint": "task:refresh-2",
            "retryable": True,
        },
        {
            "severity": "info",
            "category": "unknown",
            "title": "歷史觀測",
            "retryable": False,
        },
    ]

    summary = maintenance.incident_action_priority_summary(incidents)

    assert summary["state"] == "blocked"
    assert summary["title"] == "先處理 2 個 Critical 事件"
    assert summary["counts_label"] == "Critical 2 / Warning 1 / Info 1"
    assert summary["retryable_count"] == 2
    assert summary["task_linked_count"] == 3
    assert summary["passive_count"] == 1
    assert "2 個可重試任務可直接在下方操作" in summary["primary_action"]
    assert "3 個任務檢視" in summary["secondary_action"]
    assert "1 個為歷史趨勢/觀測" in summary["secondary_action"]


def test_incident_action_priority_summary_tracks_historical_critical_when_latest_task_healthy() -> None:
    incidents = [
        {
            "severity": "critical",
            "category": "runtime_storage",
            "title": "本機儲存失敗",
            "route_hint": "task:storage-1",
            "retryable": True,
            "historical_after_latest_success": True,
        },
        {
            "severity": "critical",
            "category": "whitelist",
            "title": "payload validation repeated",
            "route_hint": "settings:maintenance",
            "retryable": False,
            "trend_only": True,
        },
    ]

    summary = maintenance.incident_action_priority_summary(incidents)

    assert summary["state"] == "attention"
    assert summary["title"] == "目前任務健康，追蹤 2 個歷史 Critical 紀錄"
    assert summary["counts_label"] == "Critical 2 / Warning 0 / Info 0（其中 2 個為歷史/趨勢）"
    assert summary["historical_count"] == 2
    assert "最新任務已成功" in summary["primary_action"]
    assert "2 個為歷史趨勢/觀測" in summary["secondary_action"]


def test_incident_action_priority_summary_keeps_current_report_blocker_urgent() -> None:
    incidents = [
        {
            "severity": "critical",
            "category": "runtime_storage",
            "title": "本機儲存失敗",
            "route_hint": "task:storage-1",
            "retryable": False,
            "historical_after_latest_success": True,
        },
        {
            "severity": "critical",
            "category": "report_quality",
            "title": "不可直接採信",
            "route_hint": "data_enrichment",
            "retryable": False,
        },
    ]

    summary = maintenance.incident_action_priority_summary(incidents)

    assert summary["state"] == "blocked"
    assert summary["title"] == "先處理 1 個當前 Critical 事件"
    assert summary["historical_count"] == 1
    assert "Critical 2 / Warning 0 / Info 0" in summary["counts_label"]
    assert "當前 Critical" in summary["primary_action"]
    assert "事件已連到任務檢視" not in summary["primary_action"]


def test_incident_action_priority_summary_ready_state_for_empty_inbox() -> None:
    summary = maintenance.incident_action_priority_summary([])

    assert summary["state"] == "ready"
    assert summary["title"] == "目前沒有待處理事件"
    assert summary["counts_label"] == "Critical 0 / Warning 0 / Info 0"
    assert summary["primary_action"] == "可以回到分析工作區產生最新版報告。"
    assert summary["secondary_action"] == "維護頁仍保留服務狀態與升級稽核供備查。"


def test_render_maintenance_tab_promotes_ai_quota_panel_when_requested(monkeypatch) -> None:
    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = {"pending_maintenance_focus": "ai_quota"}

        def toggle(self, *_args, **_kwargs) -> bool:
            return False

    fake_st = FakeStreamlit()
    events: list[str] = []

    monkeypatch.setattr(maintenance, "st", fake_st)
    monkeypatch.setattr(maintenance, "render_section_header", lambda *_args: events.append("header"))
    monkeypatch.setattr(
        maintenance,
        "load_api_json_or_default",
        lambda _endpoint, default, **_kwargs: default,
    )
    monkeypatch.setattr(maintenance, "_render_incident_inbox", lambda _incidents: events.append("incident"))
    monkeypatch.setattr(
        maintenance,
        "render_upgrade_audit_panel",
        lambda *_args: events.append("upgrade"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_optimization_progress_panel",
        lambda *_args: events.append("optimization"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_service_metrics_panel",
        lambda *_args: events.append("metrics"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_external_deployment_panel",
        lambda *_args: events.append("external"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_ai_quota_panel",
        lambda *_args: events.append("ai_quota"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_ai_usage_panel",
        lambda *_args: events.append("ai_usage"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_report_generation_observability_panel",
        lambda *_args: events.append("reports"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_background_task_observability_panel",
        lambda *_args: events.append("tasks"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_report_quality_panel",
        lambda *_args: events.append("quality"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_service_details_panel",
        lambda *_args: events.append("details"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_maintenance_cleanup_panel",
        lambda *_args: events.append("cleanup"),
    )

    maintenance.render_maintenance_tab()

    assert "pending_maintenance_focus" not in fake_st.session_state
    assert events.index("ai_quota") < events.index("upgrade")
    assert events.count("ai_quota") == 1


def test_render_maintenance_tab_promotes_task_observability_when_requested(
    monkeypatch,
) -> None:
    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = {
                "maintenance_inspect_task_id": "task-123",
                "pending_maintenance_focus": "task_observability",
            }

        def toggle(self, *_args, **_kwargs) -> bool:
            return False

    fake_st = FakeStreamlit()
    events: list[str] = []

    monkeypatch.setattr(maintenance, "st", fake_st)
    monkeypatch.setattr(maintenance, "render_section_header", lambda *_args: events.append("header"))
    monkeypatch.setattr(
        maintenance,
        "load_api_json_or_default",
        lambda _endpoint, default, **_kwargs: default,
    )
    monkeypatch.setattr(maintenance, "_render_incident_inbox", lambda _incidents: events.append("incident"))
    monkeypatch.setattr(
        maintenance,
        "render_upgrade_audit_panel",
        lambda *_args: events.append("upgrade"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_optimization_progress_panel",
        lambda *_args: events.append("optimization"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_service_metrics_panel",
        lambda *_args: events.append("metrics"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_external_deployment_panel",
        lambda *_args: events.append("external"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_ai_quota_panel",
        lambda *_args: events.append("ai_quota"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_ai_usage_panel",
        lambda *_args: events.append("ai_usage"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_report_generation_observability_panel",
        lambda *_args: events.append("reports"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_background_task_observability_panel",
        lambda *_args: events.append("tasks"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_report_quality_panel",
        lambda *_args: events.append("quality"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_service_details_panel",
        lambda *_args: events.append("details"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_maintenance_cleanup_panel",
        lambda *_args: events.append("cleanup"),
    )

    maintenance.render_maintenance_tab()

    assert "pending_maintenance_focus" not in fake_st.session_state
    assert events.index("tasks") < events.index("upgrade")
    assert events.count("tasks") == 1


def test_render_maintenance_tab_promotes_external_deployment_when_requested(
    monkeypatch,
) -> None:
    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = {
                "pending_maintenance_focus": "external_deployment",
                "pending_external_deployment_focus": "structured_api",
            }

        def toggle(self, *_args, **_kwargs) -> bool:
            return False

    fake_st = FakeStreamlit()
    events: list[str] = []
    external_focus_contexts: list[str | None] = []

    def capture_external_panel(*_args, **kwargs) -> None:
        events.append("external")
        external_focus_contexts.append(kwargs.get("focus_context"))

    monkeypatch.setattr(maintenance, "st", fake_st)
    monkeypatch.setattr(maintenance, "render_section_header", lambda *_args: events.append("header"))
    monkeypatch.setattr(
        maintenance,
        "load_api_json_or_default",
        lambda _endpoint, default, **_kwargs: default,
    )
    monkeypatch.setattr(maintenance, "_render_incident_inbox", lambda _incidents: events.append("incident"))
    monkeypatch.setattr(
        maintenance,
        "render_upgrade_audit_panel",
        lambda *_args: events.append("upgrade"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_optimization_progress_panel",
        lambda *_args: events.append("optimization"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_service_metrics_panel",
        lambda *_args: events.append("metrics"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_external_deployment_panel",
        capture_external_panel,
    )
    monkeypatch.setattr(
        maintenance,
        "render_ai_quota_panel",
        lambda *_args: events.append("ai_quota"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_ai_usage_panel",
        lambda *_args: events.append("ai_usage"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_report_generation_observability_panel",
        lambda *_args: events.append("reports"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_background_task_observability_panel",
        lambda *_args: events.append("tasks"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_report_quality_panel",
        lambda *_args: events.append("quality"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_service_details_panel",
        lambda *_args: events.append("details"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_maintenance_cleanup_panel",
        lambda *_args: events.append("cleanup"),
    )
    monkeypatch.setattr(
        maintenance,
        "render_submission_guard_panel",
        lambda *_args: events.append("guards"),
    )

    maintenance.render_maintenance_tab()

    assert "pending_maintenance_focus" not in fake_st.session_state
    assert "pending_external_deployment_focus" not in fake_st.session_state
    assert events.index("external") < events.index("incident")
    assert events.index("external") < events.index("metrics")
    assert events.count("external") == 1
    assert external_focus_contexts == ["structured_api"]
