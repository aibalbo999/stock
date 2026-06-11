from __future__ import annotations

from app.services.status_frontend_sources import FrontendSourceContext


def frontend_settings_core_status(source_context: FrontendSourceContext) -> dict:
    ui_dir = source_context.ui_dir
    ui_source = source_context.ui_source
    ui_sources = source_context.ui_sources
    dashboard_core_source = ui_sources["dashboard_core.py"]
    api_client_source = ui_sources["api_client.py"]
    api_loaders_source = ui_sources["api_loaders.py"]
    follow_up_status_source = ui_sources["follow_up_status.py"]
    maintenance_status_source = ui_sources["maintenance_status.py"]
    system_settings_source = ui_sources["system_settings.py"]
    system_settings_scope_source = ui_sources["system_settings_scope.py"]
    system_settings_schedule_source = ui_sources["system_settings_schedule.py"]
    return {
        "frontend_settings_core_status_extracted": True,
        "frontend_settings_core_status_path": "app/services/status_frontend_settings_core.py",
        "ui_status_helpers_extracted": (ui_dir / "follow_up_status.py").exists()
        and (ui_dir / "maintenance_status.py").exists()
        and "def follow_up_result_message(" in follow_up_status_source
        and "def follow_up_result_message(" not in dashboard_core_source
        and "def upgrade_audit_html(" in maintenance_status_source
        and "def upgrade_audit_html(" not in dashboard_core_source
        and "from app.ui.follow_up_status import (" in ui_source
        and "from app.ui.maintenance_status import (" in ui_source,
        "ui_status_helper_paths": [
            "app/ui/follow_up_status.py",
            "app/ui/maintenance_status.py",
        ],
        "ui_system_settings_tabs_extracted": (ui_dir / "system_settings_scope.py").exists()
        and (ui_dir / "system_settings_schedule.py").exists()
        and "render_scope_tab(settings_whitelist)" in system_settings_source
        and "render_schedule_tab(sorted(settings_whitelist.allowed_tickers()))"
        in system_settings_source
        and "def render_scope_tab(" in system_settings_scope_source
        and "def render_schedule_tab(" in system_settings_schedule_source
        and 'api_put("/schedule"' in system_settings_schedule_source
        and "SupplyChainWhitelist" not in system_settings_schedule_source
        and 'api_put("/schedule"' not in system_settings_source
        and "st.dataframe(segment_rows" not in system_settings_source,
        "ui_system_settings_tab_paths": [
            "app/ui/system_settings_scope.py",
            "app/ui/system_settings_schedule.py",
        ],
        "ui_schedule_settings_save_confirmation_enabled": (
            "schedule_save_confirmed = st.checkbox(" in system_settings_schedule_source
            and 'key="confirm_schedule_settings_save"' in system_settings_schedule_source
            and "我了解這會更新自動排程與每日維護設定"
            in system_settings_schedule_source
            and "避免誤觸排程變更" in system_settings_schedule_source
            and "disabled=not schedule_ready or not schedule_save_confirmed"
            in system_settings_schedule_source
        ),
        "ui_api_client_extracted": (ui_dir / "api_client.py").exists()
        and "def api_task_post(" in api_client_source
        and "def request_error_message(" in api_client_source
        and "def queue_data_operation(" in api_client_source
        and "def api_task_post(" not in dashboard_core_source
        and "from app.ui.api_client import (" in ui_source,
        "ui_api_client_path": "app/ui/api_client.py",
        "ui_api_loaders_extracted": (ui_dir / "api_loaders.py").exists()
        and "def load_api_json_or_default(" in api_loaders_source
        and "request_error_message(exc)" in api_loaders_source
        and "deepcopy(fallback)" in api_loaders_source
        and "from app.ui.api_loaders import load_api_json_or_default" in ui_source,
        "ui_api_loaders_path": "app/ui/api_loaders.py",
    }
