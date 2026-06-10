from __future__ import annotations

import app.ui.system_settings_maintenance as maintenance


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
