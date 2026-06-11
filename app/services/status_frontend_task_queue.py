from __future__ import annotations

from app.services.status_frontend_sources import FrontendSourceContext


def frontend_task_queue_status(source_context: FrontendSourceContext) -> dict:
    ui_dir = source_context.ui_dir
    ui_source = source_context.ui_source
    ui_sources = source_context.ui_sources
    dashboard_core_source = ui_sources["dashboard_core.py"]
    api_client_source = ui_sources["api_client.py"]
    background_tasks_source = ui_sources["background_tasks.py"]
    task_queue_diagnostics_source = ui_sources["task_queue_diagnostics.py"]
    maintenance_status_source = ui_sources["maintenance_status.py"]
    maintenance_task_panels_source = ui_sources["maintenance_task_panels.py"]
    system_settings_maintenance_source = ui_sources["system_settings_maintenance.py"]
    return {
        "frontend_task_queue_status_extracted": True,
        "frontend_task_queue_status_path": "app/services/status_frontend_task_queue.py",
        "ui_background_task_client_extracted": (ui_dir / "background_tasks.py").exists()
        and "def submit_background_task(" in background_tasks_source
        and "def submit_api_task(" in background_tasks_source
        and "def submit_data_operation_task(" in background_tasks_source
        and "def submit_background_task(" not in dashboard_core_source
        and "from app.ui.background_tasks import" in ui_source,
        "ui_background_task_client_path": "app/ui/background_tasks.py",
        "ui_api_error_operator_guidance_enabled": (
            "OPERATION_LABELS = {" in api_client_source
            and "FAILURE_STAGE_LABELS = {" in api_client_source
            and "def _request_next_steps(" in api_client_source
            and "def _operation_label(" in api_client_source
            and "def _failure_stage_label(" in api_client_source
            and "系統設定 > 維護 > 背景任務觀測" in api_client_source
            and '"Redis/Celery 與 worker": "背景任務佇列與背景執行器"'
            in api_client_source
            and "背景任務佇列與背景執行器" in api_client_source
            and "確認 Redis/Celery 與 worker" not in api_client_source
            and "task_queue/error" not in api_client_source
        ),
        "ui_task_queue_preflight_enabled": "def task_queue_preflight_ready("
        in background_tasks_source
        and "api_task_queue_status" in background_tasks_source
        and "API_TASK_PREFLIGHT_TIMEOUT_SECONDS" in api_client_source
        and "preflight: bool = True" in background_tasks_source,
        "ui_task_queue_preflight_cache_enabled": "def cached_task_queue_status("
        in background_tasks_source
        and "TASK_QUEUE_PREFLIGHT_CACHE_KEY" in background_tasks_source
        and "TASK_QUEUE_PREFLIGHT_READY_TTL_SECONDS" in background_tasks_source
        and "TASK_QUEUE_PREFLIGHT_UNREADY_TTL_SECONDS" in background_tasks_source,
        "ui_task_queue_preflight_degrades_open": "仍會嘗試送出" in background_tasks_source,
        "ui_task_queue_worker_warning_enabled": "def task_queue_worker_warning("
        in background_tasks_source
        and "背景執行器未回應" in background_tasks_source
        and "Celery worker 未回應" not in background_tasks_source,
        "ui_task_queue_submission_smoke_hint_enabled": (
            "def task_queue_smoke_hint(" in background_tasks_source
            and "task_submission_smoke.py" in background_tasks_source
            and "task_queue_smoke_hint(task_queue)" in background_tasks_source
        ),
        "ui_task_queue_operator_hint_enabled": (
            "def task_queue_operator_hint(" in background_tasks_source
            and "def task_queue_smoke_label(" in background_tasks_source
            and "task_queue_operator_hint(task_queue)" in background_tasks_source
            and "系統設定 > 維護 > 背景任務觀測" in background_tasks_source
            and "背景任務送出檢查" in background_tasks_source
            and "任務送出 smoke" not in background_tasks_source
        ),
        "ui_task_queue_health_panel_extracted": "def task_queue_health_rows("
        in task_queue_diagnostics_source
        and "def task_queue_health_alert(" in task_queue_diagnostics_source
        and "def task_queue_repair_rows(" in task_queue_diagnostics_source
        and "def task_queue_smoke_command(" in task_queue_diagnostics_source
        and "task_queue_health_rows(service_snapshot)" in ui_source
        and "task_queue_health_alert(service_snapshot)" in ui_source
        and "task_queue_repair_rows(service_snapshot)" in ui_source
        and "task_queue_smoke_command(service_snapshot)" in ui_source
        and "背景任務修復指引" in ui_source
        and "from app.ui.task_queue_diagnostics import (" in ui_source
        and "def task_queue_health_rows(" not in maintenance_status_source,
        "ui_task_queue_health_operator_labels_enabled": (
            "背景任務提交" in task_queue_diagnostics_source
            and "背景任務執行" in task_queue_diagnostics_source
            and "Redis 佇列服務" in task_queue_diagnostics_source
            and "Redis 結果儲存" in task_queue_diagnostics_source
            and "任務註冊" in task_queue_diagnostics_source
            and "背景執行器" in task_queue_diagnostics_source
            and "背景任務可送出且背景執行器可執行" in task_queue_diagnostics_source
            and "背景執行 worker" not in task_queue_diagnostics_source
            and "worker 可執行" not in task_queue_diagnostics_source
            and "Redis broker" not in task_queue_diagnostics_source
            and "背景任務送出與執行狀態" in maintenance_task_panels_source
            and "背景任務修復指引" in maintenance_task_panels_source
            and "Queue / Worker readiness" not in maintenance_task_panels_source
            and "Queue 修復指引" not in maintenance_task_panels_source
        ),
        "ui_task_queue_repair_guidance_enabled": "def task_queue_repair_rows("
        in task_queue_diagnostics_source
        and 'task_queue.get("repair_plan")' in task_queue_diagnostics_source
        and "def _task_queue_repair_plan_row(" in task_queue_diagnostics_source
        and '"修復指令"' in task_queue_diagnostics_source
        and '"驗證指令"' in task_queue_diagnostics_source
        and "task_queue_repair_rows(service_snapshot)" in ui_source
        and "背景任務修復指引" in ui_source,
        "ui_task_queue_processing_readiness_displayed": "processing_ready"
        in task_queue_diagnostics_source
        and "背景任務執行" in task_queue_diagnostics_source
        and "def task_queue_processing_label(" in task_queue_diagnostics_source,
        "ui_task_queue_diagnostics_path": "app/ui/task_queue_diagnostics.py",
        "ui_maintenance_diagnostic_actions_enabled": (
            'maintenance_diagnostics = load_api_json_or_default(\n        "/maintenance/diagnostics"'
            in system_settings_maintenance_source
            and "render_background_task_observability_panel("
            in system_settings_maintenance_source
            and "maintenance_diagnostics," in system_settings_maintenance_source
            and "def maintenance_diagnostic_action_rows(" in maintenance_task_panels_source
            and "維護診斷動作" in maintenance_task_panels_source
            and "選擇診斷動作" in maintenance_task_panels_source
            and "maintenance_run_diagnostic_action" in maintenance_task_panels_source
            and 'f"/tasks/maintenance-diagnostic/{selected_action_id}"'
            in maintenance_task_panels_source
            and "task_state_key=MAINTENANCE_DIAGNOSTIC_TASK_KEY"
            in maintenance_task_panels_source
            and 'refresh_key="refresh_maintenance_diagnostic_action_status"'
            in maintenance_task_panels_source
        ),
        "ui_maintenance_diagnostic_action_operator_labels_enabled": (
            "def maintenance_diagnostic_action_rows(" in maintenance_task_panels_source
            and '"逾時秒數": int(action.get("timeout_seconds") or 0)'
            in maintenance_task_panels_source
            and '"Timeout"' not in maintenance_task_panels_source
        ),
        "ui_maintenance_diagnostic_effect_operator_labels_enabled": (
            "def maintenance_diagnostic_effect_label(" in maintenance_task_panels_source
            and '"效果": maintenance_diagnostic_effect_label(action.get("effect"))'
            in maintenance_task_panels_source
            and '"read_only": "只讀檢查"' in maintenance_task_panels_source
            and '"safe_noop_task_submission": "安全空跑送出"'
            in maintenance_task_panels_source
            and '"safe_local_neo4j_import_smoke": "本機 Neo4j 匯入檢查"'
            in maintenance_task_panels_source
        ),
        "ui_maintenance_diagnostic_confirmation_gate_enabled": (
            "diagnostic_confirmed = st.checkbox(" in maintenance_task_panels_source
            and 'key=f"maintenance_diagnostic_confirm_{selected_action_id}"'
            in maintenance_task_panels_source
            and "disabled=not diagnostic_confirmed" in maintenance_task_panels_source
            and 'f"我了解這會送出「{selected_label}」維護診斷背景任務"'
            in maintenance_task_panels_source
            and 'f"執行 {selected_label}"' in maintenance_task_panels_source
            and "避免誤觸診斷" in maintenance_task_panels_source
        ),
        "ui_maintenance_safe_noop_diagnostics_enabled": (
            "safe_to_run" in maintenance_task_panels_source
            and "safe_noop_task_submission" in maintenance_task_panels_source
            and "安全空跑" in maintenance_task_panels_source
        ),
        "ui_maintenance_diagnostic_actions_path": "app/ui/maintenance_task_panels.py",
        "uses_background_task_submit_helper": "submit_api_task(" in ui_source
        and "submit_data_operation_task(" in ui_source,
        "uses_task_queue_preflight": "task_queue_preflight_ready(" in background_tasks_source
        and "api_task_queue_status" in background_tasks_source,
    }
