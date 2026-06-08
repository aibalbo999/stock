from __future__ import annotations

from pathlib import Path

from app.services.status_frontend_sources import FrontendSourceContext


def frontend_external_deployment_readiness_status(
    source_context: FrontendSourceContext,
) -> dict:
    root = source_context.root
    ui_source = source_context.ui_source
    ui_sources = source_context.ui_sources
    external_deployment_source = ui_sources["external_deployment_diagnostics.py"]
    external_deployment_common_source = ui_sources["external_deployment_common.py"]
    maintenance_deployment_panel_source = ui_sources["maintenance_deployment_panel.py"]
    system_settings_maintenance_source = ui_sources["system_settings_maintenance.py"]
    readiness_service_path = root / "app" / "services" / "external_deployment_readiness.py"
    readiness_service_source = _read_text(readiness_service_path)
    return {
        "frontend_external_deployment_readiness_status_extracted": True,
        "frontend_external_deployment_readiness_status_path": (
            "app/services/status_frontend_external_deployment_readiness.py"
        ),
        "ui_external_deployment_readiness_checklist_enabled": (
            "def external_deployment_readiness_rows(" in external_deployment_source
            and "def external_deployment_readiness_rows(" in external_deployment_common_source
            and "from app.services.external_deployment_readiness import"
            in external_deployment_common_source
            and "EXTERNAL_READINESS_METADATA" in readiness_service_source
            and "EXTERNAL_LOCAL_ACTION_METADATA" in readiness_service_source
            and "def external_deployment_local_action(" in readiness_service_source
            and "def local_dependency_status_rows(" in external_deployment_common_source
            and "def local_dependency_status_rows(" in external_deployment_source
            and "def local_dependency_last_start_rows(" in external_deployment_common_source
            and "def local_dependency_last_start_rows(" in external_deployment_source
            and "def local_dependency_repair_rows(" in external_deployment_common_source
            and "def local_dependency_repair_rows(" in external_deployment_source
            and "local_dependency_wait" in readiness_service_source
            and "local_dependency_status_rows(service_snapshot)" in ui_source
            and "local_dependency_last_start_rows(service_snapshot)" in ui_source
            and "local_dependency_repair_rows(service_snapshot)" in ui_source
            and "外部部署 readiness checklist" in ui_source
            and "最近本機依賴啟動" in ui_source
            and "本機依賴修復指引" in ui_source
            and "本機依賴狀態" in ui_source
            and '"部署決策"' in readiness_service_source
            and '"本機動作"' in readiness_service_source
            and '"本機指令"' in readiness_service_source
            and '"驗證指令"' in readiness_service_source
        ),
        "ui_local_dependency_start_history_enabled": (
            "def local_dependency_last_start_rows(" in external_deployment_common_source
            and "def local_dependency_last_start_rows(" in readiness_service_source
            and "def local_dependency_last_start_rows(" in external_deployment_source
            and "local_dependency_last_start_rows(service_snapshot)" in ui_source
            and "最近本機依賴啟動" in ui_source
        ),
        "ui_local_dependency_repair_guidance_enabled": (
            "def local_dependency_repair_rows(" in external_deployment_common_source
            and "def local_dependency_repair_rows(" in readiness_service_source
            and "def local_dependency_repair_rows(" in external_deployment_source
            and '"repair_plan"' in readiness_service_source
            and "local_dependency_repair_rows(service_snapshot)" in ui_source
            and "本機依賴修復指引" in ui_source
        ),
        "ui_maintenance_operations_enabled": (
            'maintenance_operations = load_api_json_or_default(\n        "/maintenance/operations"'
            in system_settings_maintenance_source
            and "maintenance_operations,\n    )" in system_settings_maintenance_source
            and "def maintenance_operation_rows(" in maintenance_deployment_panel_source
            and "本機依賴操作" in maintenance_deployment_panel_source
            and "選擇維護操作" in maintenance_deployment_panel_source
            and "confirm_maintenance_operation" in maintenance_deployment_panel_source
            and "maintenance_run_operation" in maintenance_deployment_panel_source
            and 'f"/maintenance/operations/{selected_operation_id}/run"'
            in maintenance_deployment_panel_source
            and '"confirmed": True' in maintenance_deployment_panel_source
            and "timeout=300" in maintenance_deployment_panel_source
        ),
        "ui_maintenance_operations_path": "app/ui/maintenance_deployment_panel.py",
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
