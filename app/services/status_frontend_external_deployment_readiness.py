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
    maintenance_deployment_presenter_source = ui_sources["maintenance_deployment_presenter.py"]
    system_settings_maintenance_source = ui_sources["system_settings_maintenance.py"]
    readiness_service_path = root / "app" / "services" / "external_deployment_readiness.py"
    readiness_service_source = _read_text(readiness_service_path)
    enablement_service_path = root / "app" / "services" / "external_deployment_enablement.py"
    enablement_service_source = _read_text(enablement_service_path)
    local_dependency_service_path = (
        root / "app" / "services" / "external_deployment_local_dependencies.py"
    )
    local_dependency_service_source = _read_text(local_dependency_service_path)
    profile_catalog_path = root / "app" / "services" / "external_deployment_profiles.py"
    profile_catalog_source = _read_text(profile_catalog_path)
    return {
        "frontend_external_deployment_readiness_status_extracted": True,
        "frontend_external_deployment_readiness_status_path": (
            "app/services/status_frontend_external_deployment_readiness.py"
        ),
        "ui_external_deployment_profile_catalog_extracted": (
            profile_catalog_path.exists()
            and "EXTERNAL_READINESS_METADATA = {" in profile_catalog_source
            and "EXTERNAL_ENABLEMENT_METADATA = {" in profile_catalog_source
            and "EXTERNAL_LOCAL_ACTION_METADATA = {" in profile_catalog_source
            and "EXTERNAL_SMOKE_COMMAND_KEYS = frozenset(" in profile_catalog_source
            and "from app.services.external_deployment_profiles import" in readiness_service_source
        ),
        "ui_external_deployment_profile_catalog_path": (
            "app/services/external_deployment_profiles.py"
        ),
        "ui_external_deployment_readiness_checklist_enabled": (
            "def external_deployment_readiness_rows(" in external_deployment_source
            and "def external_deployment_readiness_rows(" in external_deployment_common_source
            and "from app.services.external_deployment_readiness import"
            in external_deployment_common_source
            and "EXTERNAL_READINESS_METADATA" in profile_catalog_source
            and "EXTERNAL_ENABLEMENT_METADATA" in profile_catalog_source
            and "EXTERNAL_LOCAL_ACTION_METADATA" in profile_catalog_source
            and "from app.services.external_deployment_profiles import" in readiness_service_source
            and "from app.services.external_deployment_enablement import"
            in readiness_service_source
            and "def external_deployment_enablement_profile(" in enablement_service_source
            and "def external_deployment_enablement_profile(" in external_deployment_common_source
            and "def external_deployment_local_projection(" in enablement_service_source
            and "def external_deployment_local_action(" in readiness_service_source
            and "from app.services.external_deployment_local_dependencies import"
            in readiness_service_source
            and "def local_dependency_status_rows(" in external_deployment_common_source
            and "def local_dependency_status_rows(" in external_deployment_source
            and "def local_dependency_status_rows(" in local_dependency_service_source
            and "def local_dependency_last_start_rows(" in external_deployment_common_source
            and "def local_dependency_last_start_rows(" in external_deployment_source
            and "def local_dependency_last_start_rows(" in local_dependency_service_source
            and "def local_dependency_repair_rows(" in external_deployment_common_source
            and "def local_dependency_repair_rows(" in external_deployment_source
            and "def local_dependency_repair_rows(" in local_dependency_service_source
            and "local_dependency_wait" in readiness_service_source
            and "local_dependency_status_rows(service_snapshot)" in ui_source
            and "local_dependency_last_start_rows(service_snapshot)" in ui_source
            and "local_dependency_repair_rows(service_snapshot)" in ui_source
            and "外部部署 readiness checklist" in ui_source
            and "最近本機依賴啟動" in ui_source
            and "本機依賴修復指引" in ui_source
            and "本機依賴狀態" in ui_source
            and '"部署決策"' in readiness_service_source
            and '"啟用分類"' in readiness_service_source
            and '"免費驗證"' in readiness_service_source
            and '"免費驗證指令"' in readiness_service_source
            and '"成本/額度"' in readiness_service_source
            and '"建議路徑"' in readiness_service_source
            and '"本機動作"' in readiness_service_source
            and '"本機指令"' in readiness_service_source
            and '"驗證指令"' in readiness_service_source
        ),
        "ui_external_deployment_operator_summary_enabled": (
            "def external_deployment_operator_summary(" in maintenance_deployment_presenter_source
            and "external_deployment_operator_summary(" in maintenance_deployment_panel_source
            and "def _external_deployment_operator_summary_html("
            in maintenance_deployment_panel_source
            and "external-deployment-operator-summary" in maintenance_deployment_panel_source
            and "外部部署選配決策摘要" in maintenance_deployment_panel_source
            and "外部選配不是系統故障" in maintenance_deployment_presenter_source
            and "沒有 blocking deployment 缺口" in maintenance_deployment_presenter_source
            and "付費/API 選配" in maintenance_deployment_presenter_source
        ),
        "ui_local_dependency_start_history_enabled": (
            "def local_dependency_last_start_rows(" in external_deployment_common_source
            and "def local_dependency_last_start_rows(" in local_dependency_service_source
            and "def local_dependency_last_start_rows(" in external_deployment_source
            and "local_dependency_last_start_rows(service_snapshot)" in ui_source
            and "最近本機依賴啟動" in ui_source
        ),
        "ui_local_dependency_repair_guidance_enabled": (
            "def local_dependency_repair_rows(" in external_deployment_common_source
            and "def local_dependency_repair_rows(" in local_dependency_service_source
            and "def local_dependency_repair_rows(" in external_deployment_source
            and '"repair_plan"' in local_dependency_service_source
            and "local_dependency_repair_rows(service_snapshot)" in ui_source
            and "本機依賴修復指引" in ui_source
        ),
        "ui_maintenance_operations_enabled": (
            'maintenance_operations = load_api_json_or_default(\n        "/maintenance/operations"'
            in system_settings_maintenance_source
            and 'external_env_check = load_api_json_or_default(\n        "/services/external-deployment/env-check"'
            in system_settings_maintenance_source
            and "maintenance_operations,\n            external_env_check,\n        )"
            in system_settings_maintenance_source
            and "from app.ui.maintenance_deployment_presenter import"
            in maintenance_deployment_panel_source
            and "def maintenance_operation_rows(" in maintenance_deployment_presenter_source
            and "def maintenance_operation_post_run_check_rows("
            in maintenance_deployment_presenter_source
            and "def maintenance_operation_post_run_diagnostic_action_ids("
            in maintenance_deployment_presenter_source
            and "def maintenance_operation_post_run_diagnostic_action_rows("
            in maintenance_deployment_presenter_source
            and "local_resolution_projection" in maintenance_deployment_presenter_source
            and "resolves_capabilities" in maintenance_deployment_presenter_source
            and '"可處理能力"' in maintenance_deployment_presenter_source
            and "本機依賴操作" in maintenance_deployment_panel_source
            and "選擇維護操作" in maintenance_deployment_panel_source
            and "後續驗證" in maintenance_deployment_panel_source
            and '"可執行診斷"' in maintenance_deployment_presenter_source
            and "可直接執行的後續診斷" in maintenance_deployment_panel_source
            and "maintenance_operation_post_run_diagnostic_action_rows(post_run_rows)"
            in maintenance_deployment_panel_source
            and "maintenance_post_run_diagnostic_" in maintenance_deployment_panel_source
            and 'f"/tasks/maintenance-diagnostic/{action_id}"'
            in maintenance_deployment_panel_source
            and "confirm_maintenance_operation" in maintenance_deployment_panel_source
            and "maintenance_run_operation" in maintenance_deployment_panel_source
            and "runtime_settings_cache_cleared" in maintenance_deployment_panel_source
            and "Runtime settings cache" in maintenance_deployment_panel_source
            and 'LAST_MAINTENANCE_OPERATION_TASK_KEY = "last_maintenance_operation_task_id"'
            in maintenance_deployment_panel_source
            and 'LAST_POST_RUN_DIAGNOSTIC_TASK_KEY = "last_post_run_diagnostic_task_id"'
            in maintenance_deployment_panel_source
            and "task_state_key=LAST_MAINTENANCE_OPERATION_TASK_KEY"
            in maintenance_deployment_panel_source
            and 'refresh_key="refresh_maintenance_operation_task_status"'
            in maintenance_deployment_panel_source
            and "task_state_key=LAST_POST_RUN_DIAGNOSTIC_TASK_KEY"
            in maintenance_deployment_panel_source
            and 'refresh_key="refresh_maintenance_diagnostic_task_status"'
            in maintenance_deployment_panel_source
            and "後續診斷結果" in maintenance_deployment_panel_source
            and 'f"/tasks/maintenance-operation/{selected_operation_id}"'
            in maintenance_deployment_panel_source
            and '"confirmed": True' in maintenance_deployment_panel_source
        ),
        "ui_maintenance_operation_rows_operator_labels_enabled": (
            "def _maintenance_operation_scope_label(" in maintenance_deployment_presenter_source
            and '"docker services": "Docker 服務"' in maintenance_deployment_presenter_source
            and '"local files": "本機檔案"' in maintenance_deployment_presenter_source
            and '"作用範圍": _maintenance_operation_scope_label('
            in maintenance_deployment_presenter_source
            and '"逾時秒數": int(operation.get("timeout_seconds") or 0)'
            in maintenance_deployment_presenter_source
            and '"Timeout"' not in maintenance_deployment_presenter_source
            and '"Docker services"' not in maintenance_deployment_presenter_source
        ),
        "ui_maintenance_operation_confirmation_gate_enabled": (
            "operation_confirmed = st.checkbox(" in maintenance_deployment_panel_source
            and 'key="confirm_maintenance_operation"' in maintenance_deployment_panel_source
            and "我了解此操作會啟動本機 Docker 依賴" in maintenance_deployment_panel_source
            and "disabled=not operation_confirmed" in maintenance_deployment_panel_source
            and 'f"/tasks/maintenance-operation/{selected_operation_id}"'
            in maintenance_deployment_panel_source
            and '"confirmed": True' in maintenance_deployment_panel_source
        ),
        "ui_maintenance_post_run_diagnostic_confirmation_gate_enabled": (
            "action_confirmed = st.checkbox(" in maintenance_deployment_panel_source
            and 'key=f"maintenance_post_run_diagnostic_confirm_{action_id}"'
            in maintenance_deployment_panel_source
            and 'f"我了解這會送出「{label}」後續診斷背景任務"'
            in maintenance_deployment_panel_source
            and 'f"執行 {label}"' in maintenance_deployment_panel_source
            and "避免誤觸後續診斷" in maintenance_deployment_panel_source
            and "disabled=not action_confirmed" in maintenance_deployment_panel_source
            and 'f"/tasks/maintenance-diagnostic/{action_id}"'
            in maintenance_deployment_panel_source
        ),
        "ui_maintenance_operations_path": "app/ui/maintenance_deployment_presenter.py",
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
