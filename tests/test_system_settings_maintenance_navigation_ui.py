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
    assert combined.count("資料來源抓取失敗") == 1
    assert "同類事件 3 筆" in combined
    assert "另有 2 筆同類事件" in combined
    assert captured_action_incidents == incidents


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
