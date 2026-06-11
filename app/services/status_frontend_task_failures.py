from __future__ import annotations

from app.services.status_frontend_sources import FrontendSourceContext


def frontend_task_failure_status(source_context: FrontendSourceContext) -> dict:
    ui_dir = source_context.ui_dir
    ui_source = source_context.ui_source
    ui_sources = source_context.ui_sources
    dashboard_core_source = ui_sources["dashboard_core.py"]
    maintenance_task_panels_source = ui_sources["maintenance_task_panels.py"]
    task_status_panel_source = ui_sources["task_status_panel.py"]
    task_status_presenter_source = ui_sources["task_status_presenter.py"]
    task_status_view_source = ui_sources["task_status_view.py"]
    task_failure_catalog_source = ui_sources["task_failure_catalog.py"]
    task_failure_diagnostics_source = ui_sources["task_failure_diagnostics.py"]
    maintenance_status_source = ui_sources["maintenance_status.py"]
    retry_submission_enabled = 'f"/tasks/{task_id}/retry"' in ui_source and (
        "_submit_task_retry(str(selected_retry_task_id))" in ui_source
    )
    recommended_retry_enabled = (
        "def recommended_task_retry_option(" in task_failure_diagnostics_source
        and "def task_retry_option_index(" in task_failure_diagnostics_source
        and "recommended_task_retry_option(" in ui_source
        and "task_retry_option_index(" in ui_source
        and "maintenance_retry_recommended_task" in ui_source
        and "一鍵重試建議任務" in ui_source
        and (
            "_submit_task_retry(str(retry_option" in ui_source
            or "_submit_task_retry(recommended_task_id)" in ui_source
        )
    )
    task_observability_auto_expand_enabled = (
        "def task_observability_expander_expanded(" in ui_source
        and "expanded=task_observability_expander_expanded(task_summary)" in ui_source
        and 'totals.get("failed_count")' in ui_source
        and 'totals.get("stale_running_count")' in ui_source
    )
    return {
        "frontend_task_failure_status_extracted": True,
        "frontend_task_failure_status_path": "app/services/status_frontend_task_failures.py",
        "ui_task_failure_drilldown_enabled": "def task_failure_drilldown_rows("
        in task_failure_diagnostics_source
        and "def task_retry_options(" in task_failure_diagnostics_source
        and "def task_failure_action_route_rows(" in task_failure_diagnostics_source
        and "task_failure_drilldown_rows(task_summary)" in ui_source
        and "task_retry_options(task_summary)" in ui_source
        and "task_failure_action_route_rows(task_summary)" in ui_source
        and retry_submission_enabled
        and "render_task_status_panel(" in ui_source,
        "ui_task_failure_recommended_retry_enabled": recommended_retry_enabled,
        "ui_task_observability_auto_expand_enabled": task_observability_auto_expand_enabled,
        "ui_task_failure_diagnostics_extracted": (ui_dir / "task_failure_diagnostics.py").exists()
        and "from app.ui.task_failure_diagnostics import (" in ui_source
        and "def task_failure_drilldown_rows(" in task_failure_diagnostics_source
        and "def task_retry_options(" in task_failure_diagnostics_source
        and "def task_failure_drilldown_rows(" not in maintenance_status_source
        and "def task_retry_options(" not in maintenance_status_source,
        "ui_task_failure_diagnostics_path": "app/ui/task_failure_diagnostics.py",
        "ui_task_failure_catalog_extracted": (
            (ui_dir / "task_failure_catalog.py").exists()
            and "from app.ui.task_failure_catalog import ("
            in task_failure_diagnostics_source
            and "def task_failure_action_route(" in task_failure_catalog_source
            and "def task_failure_action_route_detail(" in task_failure_catalog_source
            and "def task_failure_operation_label(" in task_failure_catalog_source
            and "def task_failure_category_label(" in task_failure_catalog_source
            and "def task_failure_severity_label(" in task_failure_catalog_source
            and "TASK_FAILURE_ACTION_ROUTE_DETAILS" in task_failure_catalog_source
            and "CATEGORY_LABELS = {" not in task_failure_diagnostics_source
            and "def _is_external_config_failure(" not in task_failure_diagnostics_source
        ),
        "ui_task_failure_category_display_enabled": '"category": task_failure_category_label(row.get("error_category"))'
        in task_failure_diagnostics_source
        and '"severity": task_failure_severity_label(row.get("error_severity"))'
        in task_failure_diagnostics_source
        and '"summary": task_failure_summary_text(row)' in task_failure_diagnostics_source
        and '"next_steps": task_failure_next_steps_text(row)' in task_failure_diagnostics_source
        and 'task_summary.get("by_error_category")' in ui_source
        and "失敗原因分類" in ui_source,
        "ui_task_failure_operator_labels_enabled": (
            "CATEGORY_LABELS = {" in task_failure_catalog_source
            and "SEVERITY_LABELS = {" in task_failure_catalog_source
            and "OPERATION_LABELS = {" in task_failure_catalog_source
            and "def task_failure_operation_label(" in task_failure_catalog_source
            and "def task_failure_category_label(" in task_failure_catalog_source
            and "def task_failure_severity_label(" in task_failure_catalog_source
            and "def task_failure_summary_text(" in task_failure_diagnostics_source
            and "def task_failure_next_action_text(" in task_failure_diagnostics_source
            and "def task_failure_next_steps_text(" in task_failure_diagnostics_source
            and '"summary": task_failure_summary_text(row)'
            in task_failure_diagnostics_source
            and '"next_action": task_failure_next_action_text(row)'
            in task_failure_diagnostics_source
            and "task_failure_operation_label(task_status.get(\"operation\"))"
            in task_status_view_source
            and "task_failure_category_label(task_status.get(\"error_category\"))"
            in task_status_view_source
            and "task_failure_summary_text(task_status)" in task_status_view_source
            and "task_failure_next_action_text(task_status)" in task_status_view_source
            and "task_failure_next_steps_text(task_status)" in task_status_view_source
            and "系統設定 > 維護 > 背景任務觀測" in task_failure_diagnostics_source
            and "背景任務佇列/執行器" in task_failure_catalog_source
            and "先修復 Redis/Celery" not in task_failure_diagnostics_source
            and '"next_action": task_status.get("next_action")' not in task_status_view_source
        ),
        "ui_task_observability_summary_operator_labels_enabled": (
            "def task_operation_summary_rows(" in task_failure_diagnostics_source
            and "def task_failure_category_summary_rows(" in task_failure_diagnostics_source
            and "def task_failure_category_daily_rows(" in task_failure_diagnostics_source
            and "task_operation_summary_rows(task_summary)" in maintenance_task_panels_source
            and "task_failure_category_summary_rows(task_summary)"
            in maintenance_task_panels_source
            and "task_failure_category_daily_rows(task_summary)" in maintenance_task_panels_source
            and 'st.dataframe(task_summary["by_operation"]' not in maintenance_task_panels_source
            and 'st.dataframe(task_summary["by_error_category"]'
            not in maintenance_task_panels_source
            and 'st.dataframe(task_summary["error_category_daily"]'
            not in maintenance_task_panels_source
        ),
        "ui_task_observability_alert_operator_guidance_enabled": (
            "def task_summary_alert_rows(" in task_failure_diagnostics_source
            and "def task_summary_alert_message(" in task_failure_diagnostics_source
            and "def task_summary_alert_next_steps(" in task_failure_diagnostics_source
            and "task_failure_next_steps_text(alert)" in task_failure_diagnostics_source
            and "系統設定 > 維護 > 背景任務觀測" in task_failure_diagnostics_source
            and "背景任務提交狀態" in task_failure_diagnostics_source
            and "背景執行器是否在線" in task_failure_diagnostics_source
            and "task_summary_alert_rows(task_summary)" in maintenance_task_panels_source
            and 'alert.get("code")' not in maintenance_task_panels_source
            and 'alert.get("next_steps") or []' not in maintenance_task_panels_source
        ),
        "ui_task_observability_alert_queue_operator_labels_enabled": (
            "背景任務提交狀態" in task_failure_diagnostics_source
            and "背景任務執行狀態" in task_failure_diagnostics_source
            and "背景執行器是否在線" in task_failure_diagnostics_source
            and "Redis 訊息佇列連線" in task_failure_diagnostics_source
            and "Redis 結果儲存連線" in task_failure_diagnostics_source
            and "背景任務送出契約" in task_failure_diagnostics_source
            and "Queue 提交狀態" not in task_failure_diagnostics_source
            and "Queue 執行狀態" not in task_failure_diagnostics_source
            and "Celery worker 是否在線" not in task_failure_diagnostics_source
            and "Redis broker 連線" not in task_failure_diagnostics_source
            and "Redis backend 連線" not in task_failure_diagnostics_source
            and "Celery 任務契約" not in task_failure_diagnostics_source
        ),
        "ui_task_failure_action_routes_enabled": '"action_route": task_failure_action_route(row)'
        in task_failure_diagnostics_source
        and "一鍵重試" in task_failure_catalog_source
        and "外部配置缺失" in task_failure_catalog_source
        and "需人工處理" in task_failure_catalog_source
        and "任務輸入、範圍、向量庫/本機儲存或取消狀態需人工檢查"
        in task_failure_catalog_source
        and "payload、輸入範圍" not in task_failure_diagnostics_source
        and "payload 是否支援" not in task_failure_diagnostics_source
        and "失敗處理路徑" in ui_source,
        "ui_task_retry_guard_enabled": "retry_guarded" in task_failure_diagnostics_source
        and "retry_guard_message" in task_failure_diagnostics_source
        and "先修配置再重試" in task_failure_diagnostics_source
        and "disabled=selected_retry_guarded" in ui_source
        and "st.warning(selected_retry_guard_message)" in ui_source,
        "ui_task_failure_trend_enabled": 'task_summary.get("error_category_daily")' in ui_source
        and "失敗原因趨勢" in ui_source,
        "ui_task_failure_alerts_enabled": 'task_summary.get("alerts")' in ui_source
        and 'alert.get("severity") == "error"' in ui_source
        and 'alert.get("severity") == "warning"' in ui_source,
        "ui_maintenance_task_retry_confirmation_gate_enabled": (
            "recommended_retry_confirmed = st.checkbox(" in maintenance_task_panels_source
            and 'key=f"maintenance_retry_recommended_confirm_{recommended_task_id}"'
            in maintenance_task_panels_source
            and "selected_retry_confirmed = st.checkbox(" in maintenance_task_panels_source
            and 'key=f"maintenance_retry_selected_confirm_{selected_retry_task_id}"'
            in maintenance_task_panels_source
            and "disabled=not recommended_retry_confirmed" in maintenance_task_panels_source
            and "disabled=selected_retry_guarded or not selected_retry_confirmed"
            in maintenance_task_panels_source
            and "可能消耗模型或資料源額度" in maintenance_task_panels_source
        ),
        "ui_task_status_panel_extracted": (ui_dir / "task_status_panel.py").exists()
        and "def render_task_status_panel(" in task_status_panel_source
        and "def render_task_status_panel(" not in dashboard_core_source
        and "run_every" in task_status_panel_source
        and "from app.ui.task_status_panel import" in ui_source,
        "ui_task_status_presenter_extracted": (
            "from app.ui.task_status_presenter import (" in task_status_panel_source
            and "import streamlit" not in task_status_presenter_source
            and "def task_action_preflight_summary(" in task_status_presenter_source
            and "def task_status_operation_label(" in task_status_presenter_source
            and "def task_status_state_label(" in task_status_presenter_source
            and "def task_status_poll_caption(" in task_status_presenter_source
        ),
        "ui_task_status_view_extracted": (
            "from app.ui.task_status_view import (" in task_status_panel_source
            and "import streamlit" not in task_status_view_source
            and "def task_status_metric_values(" in task_status_view_source
            and "def task_run_summary_rows(" in task_status_view_source
            and "def task_status_progress_caption(" in task_status_view_source
            and "def task_action_preflight_summary_html(" in task_status_view_source
            and "def task_status_diagnostic_rows(" in task_status_view_source
            and "def task_execution_context_rows(" in task_status_view_source
            and "def company_filing_gap_rows(" in task_status_view_source
            and "def task_status_metric_values(" not in task_status_panel_source
            and "def task_execution_context_rows(" not in task_status_panel_source
        ),
        "ui_task_status_poll_backoff_enabled": "def task_status_poll_interval_seconds("
        in task_status_presenter_source
        and "TASK_STATUS_QUEUED_POLL_SECONDS" in task_status_presenter_source
        and "TASK_STATUS_RETRY_POLL_SECONDS" in task_status_presenter_source
        and "task_status_poll_interval_seconds(" in task_status_panel_source,
        "ui_task_status_autorefresh_feedback_enabled": "def task_status_poll_caption("
        in task_status_presenter_source
        and "狀態輪詢：" in task_status_presenter_source
        and "TASK_PROGRESS_STEP_LABELS = {" in task_status_presenter_source
        and "def task_status_progress_step_label(" in task_status_presenter_source
        and "task_status_progress_step_label(" in task_status_view_source
        and "task_status_progress_caption(task_status)" in task_status_panel_source
        and "等待背景執行器" in task_status_presenter_source
        and "背景執行器已接手" in task_status_presenter_source
        and "fragment_supported" in task_status_presenter_source
        and "st.caption(\n        task_status_poll_caption(" in task_status_panel_source,
        "ui_task_status_failure_diagnostics_enabled": "def task_status_diagnostic_rows("
        in task_status_view_source
        and "失敗診斷" in task_status_panel_source
        and "task_failure_category_label(task_status.get(\"error_category\"))"
        in task_status_view_source
        and '"action_route": task_failure_action_route(task_status)' in task_status_view_source
        and "task_failure_action_route_detail(task_status)" in task_status_view_source
        and '"next_steps": task_failure_next_steps_text(task_status)'
        in task_status_view_source,
        "ui_task_execution_context_enabled": "def task_execution_context_rows("
        in task_status_view_source
        and "執行上下文" in task_status_panel_source
        and "execution_context" in task_status_view_source
        and "payload_shape" in task_status_view_source
        and "celery_info_shape" in task_status_view_source
        and "已遮蔽敏感欄位" in task_status_view_source
        and "exception_message_preview" in task_status_view_source,
        "ui_task_status_operator_context_labels_enabled": (
            "TASK_STATUS_LABELS = {" in task_status_presenter_source
            and "RUN_STATUS_LABELS = {" in task_status_presenter_source
            and "RUN_SOURCE_LABELS = {" in task_status_presenter_source
            and "def task_status_state_label(" in task_status_presenter_source
            and "def task_run_status_label(" in task_status_presenter_source
            and "def task_run_source_label(" in task_status_presenter_source
            and "task_failure_operation_label(_operator_operation_from_source(raw_source))"
            in task_status_presenter_source
            and '"celery_status": task_status_state_label(' in task_status_view_source
            and '"ready": _task_context_ready_label(' in task_status_view_source
            and '"successful": _task_context_success_label(' in task_status_view_source
            and '"run_status": task_run_status_label(' in task_status_view_source
            and '"source": task_run_source_label(' in task_status_view_source
            and '"operation": task_failure_operation_label(' in task_status_view_source
            and "資料欄位：" in task_status_view_source
            and "沒有任務輸入紀錄" in task_status_view_source
            and "沒有 run payload" not in task_status_view_source
            and "回報型態：" in task_status_view_source
            and "已遮蔽敏感欄位" in task_status_view_source
            and "執行錯誤：" in task_status_view_source
            and 'return f"{exception_type}: {preview}"' not in task_status_view_source
        ),
        "ui_task_status_metric_operator_labels_enabled": (
            "def task_status_metric_values(" in task_status_view_source
            and "def task_run_summary_rows(" in task_status_view_source
            and "def task_status_progress_caption(" in task_status_view_source
            and '"label": "任務狀態"' in task_status_view_source
            and '"label": "是否結束"' in task_status_view_source
            and '"label": "是否成功"' in task_status_view_source
            and '"label": "執行紀錄"' in task_status_view_source
            and '"報告": _number_ref(run.get("report_id"))' in task_status_view_source
            and '"輸出檔": run.get("output_path") or "-"' in task_status_view_source
            and "task_run_status_label(run.get(\"status\"))" in task_status_view_source
            and "task_status_state_label(progress.get(\"status\")" in task_status_view_source
            and "task_status_metric_values(task_status)" in task_status_panel_source
            and "task_run_summary_rows(task_status)" in task_status_panel_source
            and 'metric("Task"' not in task_status_panel_source
            and 'metric("Ready"' not in task_status_panel_source
            and 'metric("Success"' not in task_status_panel_source
            and 'metric("Run"' not in task_status_panel_source
        ),
        "ui_task_status_operation_confirmation_gate_enabled": (
            "cancel_confirmed = st.checkbox(" in task_status_panel_source
            and 'key=f"{refresh_key}_confirm_cancel"' in task_status_panel_source
            and "retry_confirmed = st.checkbox(" in task_status_panel_source
            and 'key=f"{refresh_key}_confirm_retry"' in task_status_panel_source
            and "disabled=cancel_blocked or not cancel_confirmed" in task_status_panel_source
            and "disabled=retry_blocked or not retry_confirmed" in task_status_panel_source
            and "可能消耗模型或資料源額度" in task_status_panel_source
        ),
        "ui_task_status_operation_preflight_summary_enabled": (
            "def task_action_preflight_summary(" in task_status_presenter_source
            and "def render_task_action_preflight_summary(" in task_status_panel_source
            and "render_task_action_preflight_summary(" in task_status_panel_source
            and "task_action_preflight_summary(" in task_status_panel_source
            and 'class="task-action-preflight-summary' in task_status_view_source
            and 'class="task-action-preflight-summary' not in task_status_panel_source
            and 'f"任務編號 {task_id}"' in task_status_presenter_source
            and 'f"Task {task_id}"' not in task_status_presenter_source
            and "task_failure_next_action_text(task_status)" in task_status_presenter_source
            and "payload 不支援自動重試" not in task_status_presenter_source
            and "背景執行器已完成" in task_status_presenter_source
            and "worker 已完成" not in task_status_presenter_source
            and "會重新排隊並可能再次消耗模型、外部資料源或 API 額度"
            in task_status_presenter_source
            and "此任務不支援一鍵重試" in task_status_presenter_source
            and "避免重複失敗與額度浪費" in task_status_presenter_source
        ),
        "ui_task_status_operation_label_inference_enabled": (
            "def task_status_operation_label(" in task_status_presenter_source
            and "task_status_operation_label(task_status)" in task_status_presenter_source
            and "task_action_preflight_summary(" in task_status_panel_source
            and '"execution_context"' in task_status_presenter_source
            and '"operation"' in task_status_presenter_source
            and "def _task_run_payload(" in task_status_presenter_source
            and '"payload_json"' in task_status_presenter_source
            and '"workflow_name"' in task_status_presenter_source
            and "def _operator_operation_from_source(" in task_status_presenter_source
            and '"celery_"' in task_status_presenter_source
        ),
        "ui_task_status_terminal_task_action_guard_enabled": (
            "cancel_blocked = cancel_summary.get" in task_status_panel_source
            and "retry_blocked = retry_summary.get" in task_status_panel_source
            and "此任務已結束，不能取消" in task_status_presenter_source
            and "此任務已成功，不需要一鍵重試" in task_status_presenter_source
            and "此任務仍在執行，不能重試" in task_status_presenter_source
            and "disabled=cancel_blocked or not cancel_confirmed" in task_status_panel_source
            and "disabled=retry_blocked or not retry_confirmed" in task_status_panel_source
        ),
        "ui_task_status_panel_path": "app/ui/task_status_panel.py",
        "task_retry_uses_scoped_state_key": "task_state_key" in task_status_panel_source
        and 'st.session_state["last_data_task_id"]' not in task_status_panel_source,
        "uses_task_status_panel": "def render_task_status_panel(" in ui_source
        and '"fragment"' in ui_source
        and "run_every" in ui_source,
    }
