from __future__ import annotations

from app.services.status_frontend_sources import FrontendSourceContext


def frontend_maintenance_ui_status(source_context: FrontendSourceContext) -> dict:
    ui_dir = source_context.ui_dir
    ui_source = source_context.ui_source
    ui_sources = source_context.ui_sources
    system_settings_source = ui_sources["system_settings.py"]
    operator_routes_source = ui_sources["operator_routes.py"]
    system_settings_maintenance_source = ui_sources["system_settings_maintenance.py"]
    maintenance_panels_source = ui_sources["maintenance_panels.py"]
    maintenance_deployment_panel_source = ui_sources["maintenance_deployment_panel.py"]
    maintenance_ai_panels_source = ui_sources["maintenance_ai_panels.py"]
    maintenance_task_panels_source = ui_sources["maintenance_task_panels.py"]
    maintenance_cleanup_panel_source = ui_sources["maintenance_cleanup_panel.py"]
    llm_quota_panel_source = ui_sources["llm_quota_panel.py"]
    return {
        "frontend_maintenance_ui_status_extracted": True,
        "frontend_maintenance_ui_status_path": "app/services/status_frontend_maintenance.py",
        "ui_settings_ai_quota_route_focus_enabled": (
            "def maintenance_focus_from_pending_section(" in system_settings_source
            and '"pending_maintenance_focus"' in system_settings_source
            and "maintenance_focus_from_pending_section(pending_section)"
            in system_settings_source
            and "def _consume_pending_maintenance_focus(" in system_settings_maintenance_source
            and 'st.session_state.pop("pending_maintenance_focus"' in system_settings_maintenance_source
            and 'if maintenance_focus == "ai_quota":' in system_settings_maintenance_source
            and "render_ai_quota_panel(llm_quota, service_snapshot)"
            in system_settings_maintenance_source
            and 'if maintenance_focus != "ai_quota":' in system_settings_maintenance_source
        ),
        "ui_settings_task_route_focus_enabled": (
            '"maintenance_inspect_task_id": task_id' in operator_routes_source
            and '"pending_maintenance_focus": "task_observability"' in operator_routes_source
            and 'if maintenance_focus == "task_observability":'
            in system_settings_maintenance_source
            and 'if maintenance_focus != "task_observability":'
            in system_settings_maintenance_source
            and 'focus in {"ai_quota", "task_observability"}'
            in system_settings_maintenance_source
            and system_settings_maintenance_source.count(
                "render_background_task_observability_panel("
            )
            >= 2
        ),
        "ui_incident_action_labels_enabled": (
            '"action_label": incident_action_label(incident, index)'
            in system_settings_maintenance_source
            and "def incident_action_label(" in system_settings_maintenance_source
            and '"action_label": _failure_action_label(category, retryable)' in ui_source
            and "def _failure_action_label(" in ui_source
            and 'return "重試任務"' in ui_source
            and 'return "檢查任務"' in ui_source
        ),
        "ui_maintenance_panels_extracted": (ui_dir / "maintenance_panels.py").exists()
        and (ui_dir / "maintenance_deployment_panel.py").exists()
        and (ui_dir / "maintenance_ai_panels.py").exists()
        and (ui_dir / "maintenance_task_panels.py").exists()
        and (ui_dir / "maintenance_cleanup_panel.py").exists()
        and "from app.ui.maintenance_deployment_panel import render_external_deployment_panel"
        in maintenance_panels_source
        and "from app.ui.maintenance_ai_panels import (" in maintenance_panels_source
        and "from app.ui.maintenance_task_panels import render_background_task_observability_panel"
        in maintenance_panels_source
        and "from app.ui.maintenance_cleanup_panel import render_maintenance_cleanup_panel"
        in maintenance_panels_source
        and "def render_external_deployment_panel(" in maintenance_deployment_panel_source
        and "service_snapshot: dict | None = None" in maintenance_deployment_panel_source
        and "local_dependency_status_rows(service_snapshot)" in maintenance_deployment_panel_source
        and "local_dependency_last_start_rows(service_snapshot)"
        in maintenance_deployment_panel_source
        and "local_dependency_repair_rows(service_snapshot)" in maintenance_deployment_panel_source
        and "def render_ai_usage_panel(" in maintenance_ai_panels_source
        and "def render_background_task_observability_panel(" in maintenance_task_panels_source
        and "def render_report_quality_panel(" in maintenance_panels_source
        and "def render_maintenance_cleanup_panel(" in maintenance_cleanup_panel_source
        and "from app.ui.maintenance_panels import (" in system_settings_maintenance_source
        and "render_external_deployment_panel(\n        upgrade_audit,"
        in system_settings_maintenance_source
        and 'maintenance_operations = load_api_json_or_default(\n        "/maintenance/operations"'
        in system_settings_maintenance_source
        and 'external_env_check = load_api_json_or_default(\n        "/services/external-deployment/env-check"'
        in system_settings_maintenance_source
        and "maintenance_operations,\n        external_env_check,\n    )"
        in system_settings_maintenance_source
        and "render_background_task_observability_panel(" in system_settings_maintenance_source
        and "maintenance_diagnostics," in system_settings_maintenance_source
        and 'maintenance_diagnostics = load_api_json_or_default(\n        "/maintenance/diagnostics"'
        in system_settings_maintenance_source
        and "external_deployment_warning_rows(upgrade_audit)"
        not in system_settings_maintenance_source
        and 'st.expander("背景任務觀測"' not in system_settings_maintenance_source,
        "ui_maintenance_panels_path": "app/ui/maintenance_panels.py",
        "ui_maintenance_panel_module_paths": [
            "app/ui/maintenance_deployment_panel.py",
            "app/ui/maintenance_ai_panels.py",
            "app/ui/maintenance_task_panels.py",
            "app/ui/maintenance_cleanup_panel.py",
        ],
        "ui_submission_guard_panel_enabled": (
            "def render_submission_guard_panel(service_snapshot: dict) -> None:"
            in maintenance_panels_source
            and "def submission_guard_metric_values(" in maintenance_panels_source
            and "def submission_guard_rows(" in maintenance_panels_source
            and "高風險操作保護" in maintenance_panels_source
            and "ui_risky_submission_guard_rows" in maintenance_panels_source
            and "確認所有會寫入、刪除、消耗額度或重試任務的入口都有確認閘門"
            in maintenance_panels_source
            and "render_submission_guard_panel(service_snapshot)"
            in system_settings_maintenance_source
        ),
        "ui_maintenance_cleanup_confirmation_gate_enabled": (
            "cleanup_confirmed = st.checkbox(" in maintenance_cleanup_panel_source
            and 'key="confirm_maintenance_cleanup"' in maintenance_cleanup_panel_source
            and "我了解這裡會改動或刪除歷史資料" in maintenance_cleanup_panel_source
            and "清理操作會刪除歷史紀錄" in maintenance_cleanup_panel_source
            and "disabled=not cleanup_confirmed" in maintenance_cleanup_panel_source
            and 'api_post("/maintenance/cleanup"' in maintenance_cleanup_panel_source
        ),
        "ui_llm_quota_panel_extracted": (ui_dir / "llm_quota_panel.py").exists()
        and "def llm_quota_metric_values(" in llm_quota_panel_source
        and "def llm_quota_model_rows(" in llm_quota_panel_source
        and "def llm_quota_captions(" in llm_quota_panel_source
        and "額度重置" in llm_quota_panel_source
        and "quota_hit_count" in llm_quota_panel_source
        and "quota_skip_count" in llm_quota_panel_source
        and "active_cooldown" in llm_quota_panel_source
        and "from app.ui.llm_quota_panel import (" in ui_source
        and "llm_quota_metric_values(llm_quota)" in ui_source
        and "llm_quota_model_rows(llm_quota)" in ui_source,
        "ui_llm_quota_panel_path": "app/ui/llm_quota_panel.py",
    }
