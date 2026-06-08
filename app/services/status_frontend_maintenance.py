from __future__ import annotations

from app.services.status_frontend_sources import FrontendSourceContext


def frontend_maintenance_ui_status(source_context: FrontendSourceContext) -> dict:
    ui_dir = source_context.ui_dir
    ui_source = source_context.ui_source
    ui_sources = source_context.ui_sources
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
        and "maintenance_operations,\n    )" in system_settings_maintenance_source
        and "render_background_task_observability_panel(\n        service_snapshot,"
        in system_settings_maintenance_source
        and 'maintenance_diagnostics = load_api_json_or_default(\n        "/maintenance/diagnostics"'
        in system_settings_maintenance_source
        and "maintenance_diagnostics,\n    )" in system_settings_maintenance_source
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
        "ui_llm_quota_panel_extracted": (ui_dir / "llm_quota_panel.py").exists()
        and "def llm_quota_metric_values(" in llm_quota_panel_source
        and "def llm_quota_model_rows(" in llm_quota_panel_source
        and "def llm_quota_captions(" in llm_quota_panel_source
        and "額度重置" in llm_quota_panel_source
        and "from app.ui.llm_quota_panel import (" in ui_source
        and "llm_quota_metric_values(llm_quota)" in ui_source
        and "llm_quota_model_rows(llm_quota)" in ui_source,
        "ui_llm_quota_panel_path": "app/ui/llm_quota_panel.py",
    }
