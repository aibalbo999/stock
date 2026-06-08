from __future__ import annotations

from app.services.status_frontend_sources import FrontendSourceContext


def frontend_task_failure_status(source_context: FrontendSourceContext) -> dict:
    ui_dir = source_context.ui_dir
    ui_source = source_context.ui_source
    ui_sources = source_context.ui_sources
    dashboard_core_source = ui_sources["dashboard_core.py"]
    task_status_panel_source = ui_sources["task_status_panel.py"]
    task_failure_diagnostics_source = ui_sources["task_failure_diagnostics.py"]
    maintenance_status_source = ui_sources["maintenance_status.py"]
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
        and 'f"/tasks/{selected_retry_task_id}/retry"' in ui_source
        and "render_task_status_panel(" in ui_source,
        "ui_task_failure_diagnostics_extracted": (ui_dir / "task_failure_diagnostics.py").exists()
        and "from app.ui.task_failure_diagnostics import (" in ui_source
        and "def task_failure_drilldown_rows(" in task_failure_diagnostics_source
        and "def task_retry_options(" in task_failure_diagnostics_source
        and "def task_failure_drilldown_rows(" not in maintenance_status_source
        and "def task_retry_options(" not in maintenance_status_source,
        "ui_task_failure_diagnostics_path": "app/ui/task_failure_diagnostics.py",
        "ui_task_failure_category_display_enabled": '"category": row.get("error_category")'
        in task_failure_diagnostics_source
        and '"severity": row.get("error_severity")' in task_failure_diagnostics_source
        and '"summary": row.get("error_summary")' in task_failure_diagnostics_source
        and '"next_steps": _task_next_steps_text(row)' in task_failure_diagnostics_source
        and 'task_summary.get("by_error_category")' in ui_source
        and "失敗原因分類" in ui_source,
        "ui_task_failure_action_routes_enabled": '"action_route": task_failure_action_route(row)'
        in task_failure_diagnostics_source
        and "一鍵重試" in task_failure_diagnostics_source
        and "外部配置缺失" in task_failure_diagnostics_source
        and "需人工處理" in task_failure_diagnostics_source
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
        "ui_task_status_panel_extracted": (ui_dir / "task_status_panel.py").exists()
        and "def render_task_status_panel(" in task_status_panel_source
        and "def render_task_status_panel(" not in dashboard_core_source
        and "run_every" in task_status_panel_source
        and "from app.ui.task_status_panel import" in ui_source,
        "ui_task_status_poll_backoff_enabled": "def task_status_poll_interval_seconds("
        in task_status_panel_source
        and "TASK_STATUS_QUEUED_POLL_SECONDS" in task_status_panel_source
        and "TASK_STATUS_RETRY_POLL_SECONDS" in task_status_panel_source
        and "task_status_poll_interval_seconds(" in task_status_panel_source,
        "ui_task_status_autorefresh_feedback_enabled": "def task_status_poll_caption("
        in task_status_panel_source
        and "狀態輪詢：" in task_status_panel_source
        and "fragment_supported" in task_status_panel_source
        and "st.caption(\n        task_status_poll_caption(" in task_status_panel_source,
        "ui_task_status_failure_diagnostics_enabled": "def task_status_diagnostic_rows("
        in task_status_panel_source
        and "失敗診斷" in task_status_panel_source
        and '"category": task_status.get("error_category")' in task_status_panel_source
        and '"action_route": task_failure_action_route(task_status)' in task_status_panel_source
        and "task_failure_action_route_detail(task_status)" in task_status_panel_source
        and '"next_steps": _task_status_next_steps_text(task_status)' in task_status_panel_source,
        "ui_task_status_panel_path": "app/ui/task_status_panel.py",
        "task_retry_uses_scoped_state_key": "task_state_key" in task_status_panel_source
        and 'st.session_state["last_data_task_id"]' not in task_status_panel_source,
        "uses_task_status_panel": "def render_task_status_panel(" in ui_source
        and '"fragment"' in ui_source
        and "run_every" in ui_source,
    }
