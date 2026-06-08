from __future__ import annotations

from pathlib import Path

from app.services.status_frontend_sources import FrontendSourceContext


def frontend_external_deployment_status(source_context: FrontendSourceContext) -> dict:
    root = source_context.root
    ui_dir = source_context.ui_dir
    ui_source = source_context.ui_source
    ui_sources = source_context.ui_sources
    external_deployment_source = ui_sources["external_deployment_diagnostics.py"]
    external_deployment_common_source = ui_sources["external_deployment_common.py"]
    external_deployment_env_keys_source = ui_sources["external_deployment_env_keys.py"]
    external_deployment_unlocker_source = ui_sources["external_deployment_unlocker.py"]
    external_deployment_neo4j_source = ui_sources["external_deployment_neo4j.py"]
    external_deployment_structured_api_source = ui_sources[
        "external_deployment_structured_api.py"
    ]
    maintenance_status_source = ui_sources["maintenance_status.py"]
    maintenance_deployment_panel_source = ui_sources["maintenance_deployment_panel.py"]
    system_settings_maintenance_source = ui_sources["system_settings_maintenance.py"]
    external_deployment_env_gap_service_path = (
        root / "app" / "services" / "external_deployment_env_gaps.py"
    )
    external_deployment_env_gap_service_source = _read_text(
        external_deployment_env_gap_service_path
    )
    external_deployment_readiness_service_path = (
        root / "app" / "services" / "external_deployment_readiness.py"
    )
    external_deployment_readiness_service_source = _read_text(
        external_deployment_readiness_service_path
    )
    return {
        "frontend_external_deployment_status_extracted": True,
        "frontend_external_deployment_status_path": (
            "app/services/status_frontend_external_deployment.py"
        ),
        "ui_external_deployment_diagnostics_enabled": "def external_deployment_warning_rows("
        in external_deployment_source
        and "def external_deployment_readiness_rows(" in external_deployment_source
        and "external_deployment_readiness_rows(\n        upgrade_audit," in ui_source
        and "外部部署 readiness checklist" in ui_source
        and "最近本機依賴啟動" in ui_source
        and "本機依賴修復指引" in ui_source
        and "本機依賴狀態" in ui_source
        and "def external_deployment_smoke_commands(" in external_deployment_source
        and "def external_deployment_env_key_rows(" in external_deployment_source
        and "external_deployment_env_key_rows(upgrade_audit, service_snapshot)"
        in ui_source
        and "外部設定缺口" in ui_source
        and "optional_warnings" in maintenance_status_source
        and "external_deployment_warning_rows(upgrade_audit)" in ui_source
        and "external_deployment_smoke_commands(upgrade_audit)" in ui_source
        and "def local_neo4j_operation_rows(" in external_deployment_source
        and "local_neo4j_operation_rows(upgrade_audit)" in ui_source
        and "本機 Neo4j / GraphRAG 操作提示" in ui_source
        and "def local_unlocker_operation_rows(" in external_deployment_source
        and "local_unlocker_operation_rows(upgrade_audit)" in ui_source
        and "本機 unlocker 操作提示" in ui_source
        and "def structured_filing_api_operation_rows(" in external_deployment_source
        and "structured_filing_api_operation_rows(upgrade_audit)" in ui_source
        and "結構化文件 API 操作提示" in ui_source
        and "Configuration check" in external_deployment_structured_api_source
        and "configuration_check" in external_deployment_structured_api_source
        and "Configuration check" in external_deployment_unlocker_source
        and "configuration_check" in external_deployment_unlocker_source
        and "單項診斷指令" in ui_source
        and "external_integrations_smoke.py --strict --json" in ui_source,
        "ui_external_deployment_readiness_checklist_enabled": (
            "def external_deployment_readiness_rows(" in external_deployment_source
            and "def external_deployment_readiness_rows(" in external_deployment_common_source
            and "from app.services.external_deployment_readiness import"
            in external_deployment_common_source
            and "EXTERNAL_READINESS_METADATA" in external_deployment_readiness_service_source
            and "EXTERNAL_LOCAL_ACTION_METADATA"
            in external_deployment_readiness_service_source
            and "def external_deployment_local_action("
            in external_deployment_readiness_service_source
            and "def local_dependency_status_rows(" in external_deployment_common_source
            and "def local_dependency_status_rows(" in external_deployment_source
            and "def local_dependency_last_start_rows(" in external_deployment_common_source
            and "def local_dependency_last_start_rows(" in external_deployment_source
            and "def local_dependency_repair_rows(" in external_deployment_common_source
            and "def local_dependency_repair_rows(" in external_deployment_source
            and "local_dependency_wait" in external_deployment_readiness_service_source
            and "local_dependency_status_rows(service_snapshot)" in ui_source
            and "local_dependency_last_start_rows(service_snapshot)" in ui_source
            and "local_dependency_repair_rows(service_snapshot)" in ui_source
            and "外部部署 readiness checklist" in ui_source
            and "最近本機依賴啟動" in ui_source
            and "本機依賴修復指引" in ui_source
            and "本機依賴狀態" in ui_source
            and '"部署決策"' in external_deployment_readiness_service_source
            and '"本機動作"' in external_deployment_readiness_service_source
            and '"本機指令"' in external_deployment_readiness_service_source
            and '"驗證指令"' in external_deployment_readiness_service_source
        ),
        "ui_external_deployment_diagnostics_extracted": (
            ui_dir / "external_deployment_diagnostics.py"
        ).exists()
        and "from app.ui.external_deployment_diagnostics import (" in ui_source
        and "def external_deployment_readiness_rows(" in external_deployment_source
        and "def local_dependency_status_rows(" in external_deployment_source
        and "def local_dependency_last_start_rows(" in external_deployment_source
        and "def local_dependency_repair_rows(" in external_deployment_source
        and "def external_deployment_env_key_rows(" in external_deployment_env_keys_source
        and "from app.services.external_deployment_env_gaps import"
        in external_deployment_env_keys_source
        and "def external_deployment_env_key_rows("
        in external_deployment_env_gap_service_source
        and '"處理類型"' in external_deployment_env_gap_service_source
        and '"維護動作"' in external_deployment_env_gap_service_source
        and "external_deployment_env_key_rows(upgrade_audit, service_snapshot)"
        in ui_source
        and "外部設定缺口" in ui_source
        and "def external_deployment_warning_rows(" in external_deployment_source
        and "def high_risk_filing_unlocker_rows(" in external_deployment_source
        and "def local_neo4j_operation_rows(" in external_deployment_source
        and "def structured_filing_api_operation_rows(" in external_deployment_source
        and "def external_deployment_warning_rows(" not in maintenance_status_source
        and "def local_neo4j_operation_rows(" not in maintenance_status_source
        and "def structured_filing_api_operation_rows(" not in maintenance_status_source,
        "ui_external_deployment_diagnostics_path": "app/ui/external_deployment_diagnostics.py",
        "ui_local_dependency_start_history_enabled": (
            "def local_dependency_last_start_rows(" in external_deployment_common_source
            and "def local_dependency_last_start_rows("
            in external_deployment_readiness_service_source
            and "def local_dependency_last_start_rows(" in external_deployment_source
            and "local_dependency_last_start_rows(service_snapshot)" in ui_source
            and "最近本機依賴啟動" in ui_source
        ),
        "ui_local_dependency_repair_guidance_enabled": (
            "def local_dependency_repair_rows(" in external_deployment_common_source
            and "def local_dependency_repair_rows("
            in external_deployment_readiness_service_source
            and "def local_dependency_repair_rows(" in external_deployment_source
            and '"repair_plan"' in external_deployment_readiness_service_source
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
        "ui_external_deployment_domain_helpers_extracted": (
            ui_dir / "external_deployment_common.py"
        ).exists()
        and external_deployment_readiness_service_path.exists()
        and (ui_dir / "external_deployment_env_keys.py").exists()
        and external_deployment_env_gap_service_path.exists()
        and (ui_dir / "external_deployment_unlocker.py").exists()
        and (ui_dir / "external_deployment_neo4j.py").exists()
        and (ui_dir / "external_deployment_structured_api.py").exists()
        and "def external_deployment_warning_items(" in external_deployment_common_source
        and "from app.services.external_deployment_readiness import"
        in external_deployment_common_source
        and "def external_deployment_readiness_rows(" in external_deployment_common_source
        and "def external_deployment_env_key_rows(" in external_deployment_env_keys_source
        and "from app.services.external_deployment_env_gaps import"
        in external_deployment_env_keys_source
        and "def external_deployment_env_gap_report("
        in external_deployment_env_gap_service_source
        and "EXTERNAL_READINESS_METADATA" in external_deployment_readiness_service_source
        and "EXTERNAL_LOCAL_ACTION_METADATA"
        in external_deployment_readiness_service_source
        and "def high_risk_filing_unlocker_rows(" in external_deployment_unlocker_source
        and "def local_unlocker_operation_rows(" in external_deployment_unlocker_source
        and "def local_neo4j_operation_rows(" in external_deployment_neo4j_source
        and "def structured_filing_api_operation_rows(" in external_deployment_structured_api_source
        and "from app.ui.external_deployment_common import" in external_deployment_source
        and "from app.ui.external_deployment_env_keys import" in external_deployment_source
        and "from app.ui.external_deployment_unlocker import" in external_deployment_source
        and "from app.ui.external_deployment_neo4j import" in external_deployment_source
        and "from app.ui.external_deployment_structured_api import" in external_deployment_source,
        "ui_external_deployment_domain_helper_paths": [
            "app/ui/external_deployment_common.py",
            "app/services/external_deployment_readiness.py",
            "app/ui/external_deployment_env_keys.py",
            "app/services/external_deployment_env_gaps.py",
            "app/ui/external_deployment_unlocker.py",
            "app/ui/external_deployment_neo4j.py",
            "app/ui/external_deployment_structured_api.py",
        ],
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
