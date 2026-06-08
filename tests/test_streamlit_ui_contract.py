from __future__ import annotations

from pathlib import Path

import streamlit_ui_test_helpers as ui


def test_streamlit_app_defers_annotation_evaluation_for_modern_python() -> None:
    source = Path("streamlit_app.py").read_text()
    dashboard_source = ui.DASHBOARD_SOURCE.read_text()

    assert source.startswith("from __future__ import annotations")
    assert "st.navigation" in source
    assert dashboard_source.startswith("from __future__ import annotations")


def test_streamlit_page_import_contract_exports_page_functions() -> None:
    from app.ui import streamlit_dashboard

    assert callable(streamlit_dashboard.configure_page)
    assert callable(streamlit_dashboard.render_analysis_workspace)
    assert callable(streamlit_dashboard.render_report_center)
    assert callable(streamlit_dashboard.render_data_enrichment)
    assert callable(streamlit_dashboard.render_system_settings)


def test_streamlit_shell_uses_operational_workspace_header() -> None:
    source = ui.read_ui_source()
    styles = ui.STYLE_SOURCE.read_text()
    report_styles = ui.REPORT_STYLE_SOURCE.read_text()
    combined = source + "\n" + styles + "\n" + report_styles

    assert "workspace-topbar" in combined
    assert "workflow-strip" in combined
    assert "workspace-ledger" in combined
    assert "credibility_html" in source
    assert "credibility-grid" in combined
    assert "upgrade_audit_html" in source
    assert "from app.ui.maintenance_panels import (" in source
    assert (
        "from app.ui.maintenance_deployment_panel import render_external_deployment_panel" in source
    )
    assert "from app.ui.maintenance_ai_panels import (" in source
    assert (
        "from app.ui.maintenance_task_panels import render_background_task_observability_panel"
        in source
    )
    assert "from app.ui.maintenance_cleanup_panel import render_maintenance_cleanup_panel" in source
    assert "from app.ui.maintenance_status import (" in source
    assert "from app.ui.external_deployment_diagnostics import (" in source
    assert "from app.ui.task_queue_diagnostics import (" in source
    assert "from app.ui.task_failure_diagnostics import (" in source
    assert (
        "from app.ui.report_observability_panel import render_report_observability_panel" in source
    )
    assert "from app.ui.follow_up_status import (" in source
    assert "from app.ui.api_client import (" in source
    assert "from app.ui.background_tasks import" in source
    assert "from app.ui.task_status_panel import" in source
    assert "from app.ui.report_state import " in source
    assert "from app.ui.report_panels import (" in source
    assert "from app.ui.report_follow_up_controls import" in source
    assert "from app.ui.report_markdown import (" in source
    assert "from app.ui.report_candidate_audit import" in source
    assert "from app.ui.report_formatters import" in source
    assert "from app.ui.report_sections import (" in source
    assert "from app.ui.data_enrichment_market import render_market_data_tab" in source
    assert "from app.ui.data_enrichment_manual import render_manual_ingest_tab" in source
    assert "from app.ui.data_enrichment_rss import render_rss_ingest_tab" in source
    assert "from app.ui.dashboard_core import configure_page" in source
    assert "from app.ui.dashboard_core import *" not in source
    assert "import *" not in source
    assert "F403" not in source
    assert "F405" not in source
    assert "upgrade-audit-grid" in combined
    assert '[data-baseweb="tab"] p' in combined
    assert "def render_analysis_workspace() -> None:" in source
    assert "def render_report_center() -> None:" in source
    assert "def render_data_enrichment() -> None:" in source
    assert "def render_system_settings() -> None:" in source
    assert "def render_maintenance_tab() -> None:" in source
    assert "def render_external_deployment_panel(upgrade_audit: dict) -> None:" in source
    assert "def render_background_task_observability_panel(" in source
    assert "def render_report_quality_panel(report_quality_summary: dict) -> None:" in source
    assert "def render_maintenance_cleanup_panel() -> None:" in source
    assert "def render_external_deployment_panel(" not in ui.MAINTENANCE_PANELS_SOURCE.read_text()
    assert "def render_ai_usage_panel(" not in ui.MAINTENANCE_PANELS_SOURCE.read_text()
    assert (
        "def render_background_task_observability_panel("
        not in ui.MAINTENANCE_PANELS_SOURCE.read_text()
    )
    assert "def render_maintenance_cleanup_panel(" not in ui.MAINTENANCE_PANELS_SOURCE.read_text()
    assert "def render_market_data_tab(allowed_tickers: list[str]) -> None:" in source
    assert (
        "def render_manual_ingest_tab(whitelist: Any, allowed_tickers: list[str]) -> None:"
        in source
    )
    assert "def render_rss_ingest_tab() -> None:" in source
    assert "def render_scope_tab(settings_whitelist: SupplyChainWhitelist) -> None:" in source
    assert "def render_schedule_tab(settings_tickers: list[str]) -> None:" in source
    assert "render_scope_tab(settings_whitelist)" in ui.SYSTEM_SETTINGS_SOURCE.read_text()
    assert "render_schedule_tab(sorted(settings_whitelist.allowed_tickers()))" in (
        ui.SYSTEM_SETTINGS_SOURCE.read_text()
    )
    assert 'api_put("/schedule"' not in ui.SYSTEM_SETTINGS_SOURCE.read_text()
    assert "st.dataframe(segment_rows" not in ui.SYSTEM_SETTINGS_SOURCE.read_text()
    assert 'api_put("/schedule"' in ui.SYSTEM_SETTINGS_SCHEDULE_SOURCE.read_text()
    assert "st.dataframe(segment_rows" in ui.SYSTEM_SETTINGS_SCOPE_SOURCE.read_text()
    assert "def company_filing_visual_rag_model_chain_rows(" in source
    assert Path("pages/01_分析工作區.py").exists()
    assert Path("pages/02_報告中心.py").exists()
    assert Path("pages/03_資料補強.py").exists()
    assert Path("pages/04_系統設定.py").exists()
    assert 'data_tabs = st.tabs(["市場快取與刷新", "手動補充", "RSS 匯入"])' in source
    assert 'settings_tabs = st.tabs(["股票範圍", "自動排程", "維護"])' in source
    assert '"匯入新聞/研究摘要"' in source
    assert '"匯入 RAG"' not in source
    assert "manual_news_ready = bool(title.strip() and text.strip())" in source
    assert 'or schedule_task == "latest_report_update"' in source
    assert '"產業分類篩選"' in source
    assert 'st.columns([0.20, 0.80], gap="medium")' not in source
    assert 'report_action_cols = st.columns([0.16, 0.16, 0.68], gap="small")' in source
    assert ".report { max-width:1360px" in report_styles
    assert ".report-grid { display:block" in report_styles
    assert "<style>\n  :root" not in source
    assert "<style>{report_css}</style>" in source
    assert "REPORT_HTML_STYLE_PATH" in source
    assert "from app.ui.report_html import (" in source
    assert "def report_html(" not in ui.DASHBOARD_CORE_SOURCE.read_text()
    assert "def report_html(" in ui.REPORT_HTML_SOURCE.read_text()
    assert "def upgrade_audit_html(" not in ui.DASHBOARD_CORE_SOURCE.read_text()
    assert "def upgrade_audit_html(" in ui.MAINTENANCE_STATUS_SOURCE.read_text()
    assert "def follow_up_result_message(" not in ui.DASHBOARD_CORE_SOURCE.read_text()
    assert "def follow_up_result_message(" in ui.FOLLOW_UP_STATUS_SOURCE.read_text()
    assert "def api_task_post(" not in ui.DASHBOARD_CORE_SOURCE.read_text()
    assert "def api_task_post(" in ui.API_CLIENT_SOURCE.read_text()
    assert "def load_api_json_or_default(" in ui.API_LOADERS_SOURCE.read_text()
    assert "from app.ui.api_loaders import load_api_json_or_default" in source
    assert "def submit_background_task(" not in ui.DASHBOARD_CORE_SOURCE.read_text()
    assert "def submit_background_task(" in ui.BACKGROUND_TASKS_SOURCE.read_text()
    assert "def submit_data_operation_task(" in ui.BACKGROUND_TASKS_SOURCE.read_text()
    assert "def task_queue_preflight_ready(" in ui.BACKGROUND_TASKS_SOURCE.read_text()
    assert "def task_queue_worker_warning(" in ui.BACKGROUND_TASKS_SOURCE.read_text()
    assert "def api_task_queue_status(" in ui.API_CLIENT_SOURCE.read_text()
    assert "def task_queue_health_rows(" not in ui.MAINTENANCE_STATUS_SOURCE.read_text()
    assert "def task_queue_health_alert(" not in ui.MAINTENANCE_STATUS_SOURCE.read_text()
    assert "def task_queue_smoke_command(" not in ui.MAINTENANCE_STATUS_SOURCE.read_text()
    assert "def task_queue_health_rows(" in ui.TASK_QUEUE_DIAGNOSTICS_SOURCE.read_text()
    assert "def task_queue_health_alert(" in ui.TASK_QUEUE_DIAGNOSTICS_SOURCE.read_text()
    assert "def task_queue_smoke_command(" in ui.TASK_QUEUE_DIAGNOSTICS_SOURCE.read_text()
    assert "def external_deployment_warning_rows(" not in ui.MAINTENANCE_STATUS_SOURCE.read_text()
    assert "def external_deployment_smoke_commands(" not in ui.MAINTENANCE_STATUS_SOURCE.read_text()
    assert (
        "def high_risk_filing_unlocker_rows("
        in ui.EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    )
    assert (
        "def external_deployment_warning_rows("
        in ui.EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    )
    assert (
        "def external_deployment_smoke_commands("
        in ui.EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    )
    assert (
        "def local_neo4j_operation_rows(" in ui.EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    )
    assert (
        "def local_unlocker_operation_rows("
        in ui.EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    )
    assert (
        "def structured_filing_api_operation_rows("
        in ui.EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    )
    assert (
        "def external_deployment_warning_items(" in ui.EXTERNAL_DEPLOYMENT_COMMON_SOURCE.read_text()
    )
    assert (
        "def high_risk_filing_unlocker_rows(" in ui.EXTERNAL_DEPLOYMENT_UNLOCKER_SOURCE.read_text()
    )
    assert "def local_neo4j_operation_rows(" in ui.EXTERNAL_DEPLOYMENT_NEO4J_SOURCE.read_text()
    assert (
        "def structured_filing_api_operation_rows("
        in ui.EXTERNAL_DEPLOYMENT_STRUCTURED_API_SOURCE.read_text()
    )
    assert (
        "def _high_risk_unlocker_strategy("
        not in ui.EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    )
    assert (
        "def _neo4j_payload_summary(" not in ui.EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    )
    assert "def task_failure_drilldown_rows(" not in ui.MAINTENANCE_STATUS_SOURCE.read_text()
    assert "def task_retry_options(" not in ui.MAINTENANCE_STATUS_SOURCE.read_text()
    assert "def task_failure_drilldown_rows(" in ui.TASK_FAILURE_DIAGNOSTICS_SOURCE.read_text()
    assert "def task_retry_options(" in ui.TASK_FAILURE_DIAGNOSTICS_SOURCE.read_text()
    assert (
        "def render_report_observability_panel(" in ui.REPORT_OBSERVABILITY_PANEL_SOURCE.read_text()
    )
    assert (
        "def report_observability_metric_values("
        in ui.REPORT_OBSERVABILITY_PANEL_SOURCE.read_text()
    )
    assert (
        "def report_observability_bottleneck_rows("
        in ui.REPORT_OBSERVABILITY_PANEL_SOURCE.read_text()
    )
    assert "report_obs_cols" not in source
    assert "def render_task_status_panel(" not in ui.DASHBOARD_CORE_SOURCE.read_text()
    assert "def render_task_status_panel(" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    report_center_source = Path("app/ui/report_center.py").read_text()
    assert "from app.ui.task_status_panel import render_task_status_panel" in report_center_source
    assert 'with st.expander("背景任務狀態", expanded=False):' in report_center_source
    assert 'refresh_key=f"history_run_task_status_{selected_run_id}"' in report_center_source
    assert 'st.button("查詢背景任務狀態")' not in report_center_source
    assert 'st.json(api_get(f"/tasks/{selected_task_id}"))' not in report_center_source
    assert "def task_status_diagnostic_rows(" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "def hydrate_active_report_result(" not in ui.DASHBOARD_CORE_SOURCE.read_text()
    assert "def hydrate_active_report_result(" in ui.REPORT_STATE_SOURCE.read_text()
    assert "def parse_json_object(" not in ui.DASHBOARD_CORE_SOURCE.read_text()
    assert "def parse_json_object(" in ui.REPORT_STATE_SOURCE.read_text()
    assert "def render_follow_up_controls(" not in ui.DASHBOARD_CORE_SOURCE.read_text()
    assert "def render_follow_up_controls(" not in ui.REPORT_PANELS_SOURCE.read_text()
    assert "def render_follow_up_controls(" in ui.REPORT_FOLLOW_UP_CONTROLS_SOURCE.read_text()
    assert "def render_follow_up_flash(" not in ui.REPORT_PANELS_SOURCE.read_text()
    assert "def render_follow_up_flash(" in ui.REPORT_FOLLOW_UP_CONTROLS_SOURCE.read_text()
    assert "def render_quality_gate(" not in ui.DASHBOARD_CORE_SOURCE.read_text()
    assert "def render_quality_gate(" in ui.REPORT_PANELS_SOURCE.read_text()
    assert "def markdown_table_rows(" not in ui.REPORT_HTML_SOURCE.read_text()
    assert "def markdown_table_rows(" in ui.REPORT_MARKDOWN_SOURCE.read_text()
    assert "def first_tranche_allocation_label(" not in ui.REPORT_HTML_SOURCE.read_text()
    assert "def first_tranche_allocation_label(" in ui.REPORT_MARKDOWN_SOURCE.read_text()
    assert "def candidate_audit_html(" not in ui.REPORT_HTML_SOURCE.read_text()
    assert "def candidate_audit_html(" in ui.REPORT_CANDIDATE_AUDIT_SOURCE.read_text()
    assert "def candidate_source_matches_display_entity(" not in ui.REPORT_HTML_SOURCE.read_text()
    assert (
        "def candidate_source_matches_display_entity("
        in ui.REPORT_CANDIDATE_AUDIT_SOURCE.read_text()
    )
    assert "def metric_count_from_payload(" not in ui.REPORT_HTML_SOURCE.read_text()
    assert "def metric_count_from_payload(" in ui.REPORT_FORMATTERS_SOURCE.read_text()
    assert "def quality_issue_html(" not in ui.REPORT_HTML_SOURCE.read_text()
    assert "def quality_issue_html(" in ui.REPORT_FORMATTERS_SOURCE.read_text()
    assert "def auto_follow_up_status_html(" not in ui.REPORT_HTML_SOURCE.read_text()
    assert "def auto_follow_up_status_html(" in ui.REPORT_FORMATTERS_SOURCE.read_text()
    assert "def comparison_matrix_html(" not in ui.REPORT_HTML_SOURCE.read_text()
    assert "def comparison_matrix_html(" in ui.REPORT_SECTIONS_SOURCE.read_text()
    assert "def credibility_html(" not in ui.REPORT_HTML_SOURCE.read_text()
    assert "def credibility_html(" in ui.REPORT_SECTIONS_SOURCE.read_text()
    assert "def follow_up_tasks_html(" not in ui.REPORT_HTML_SOURCE.read_text()
    assert "def follow_up_tasks_html(" in ui.REPORT_SECTIONS_SOURCE.read_text()
    assert "grid-template-columns:minmax(240px,0.28fr)" not in source
    assert "上方選擇一份最新版報告後" in source
    assert 'load_api_json_or_default(\n        "/reports?limit=20"' in source
    assert "latest_by_topic(20)" not in source
    assert "選擇最新版報告" in source
    assert "flex-wrap: wrap" in combined
    assert 'button[data-testid^="stBaseButton"]' in styles
    assert '[data-testid="stSliderThumbValue"]' in styles
    assert '[data-baseweb="tag"]' in styles
    assert "min-height: 40px !important" in styles
    assert 'svg[role="button"]' in styles
    assert '[data-testid="stWidgetLabel"]' in styles
    assert '[data-testid="stDateInputField"]' in styles
    assert '[data-testid="stNumberInputField"]' in styles
    assert '[data-baseweb="input"]' in styles
    assert "border-color: #64748b" in styles
    assert '[data-testid="stJson"] *' in styles
    assert '[data-testid="stCode"] pre' in styles
    assert "white-space: pre-wrap" in styles
    assert 'button[data-testid^="stBaseButton"][disabled]' in styles
    assert "input:focus" in styles
    assert 'key="confirm_maintenance_cleanup"' in source
    assert '"正式部署檢查"' in source
    assert "/services/upgrade-audit" in source
    assert "audit_upgrade_capabilities" not in source
    assert "避免手機或滑鼠誤觸" in source
    assert "disabled=not cleanup_confirmed" in source
    assert "套用最新版報告保留策略" in source
    assert '"latest_reports_only": True' in source
    assert "old_report_files_deleted" in source
    assert "/llm/usage/summary?days=7" in source
    assert "AI 用量趨勢與成本" in source
    assert "估算成本 USD" in source
    assert "/tasks/summary?days=7" in source
    assert "背景任務觀測" in source
    assert "/reports/observability/summary?limit=20" in source
    assert "報告生成觀測" in source
    assert "trace_captured_count" in source
    assert "keyword_fallback_count" in source
    assert 'summary.get("bottlenecks")' in source
    assert "render_report_observability_panel(report_observability_summary)" in source
    assert "優先優化清單" in source
    assert "Queue / Worker readiness" in source
    assert "task_queue_health_rows(service_snapshot)" in source
    assert "task_queue_health_alert(service_snapshot)" in source
    assert "task_queue_smoke_command(service_snapshot)" in source
    assert "external_deployment_warning_rows(upgrade_audit)" in source
    assert "external_deployment_smoke_commands(upgrade_audit)" in source
    assert "high_risk_filing_unlocker_rows(upgrade_audit)" in source
    assert "local_neo4j_operation_rows(upgrade_audit)" in source
    assert "local_unlocker_operation_rows(upgrade_audit)" in source
    assert "structured_filing_api_operation_rows(upgrade_audit)" in source
    assert "高風險文件 unlocker" in source
    assert "本機 Neo4j / GraphRAG 操作提示" in source
    assert "本機 unlocker 操作提示" in source
    assert "結構化文件 API 操作提示" in source
    assert "Visual RAG 模型鏈" in source
    assert "Visual RAG / PDF 圖片解析模型鏈" in source
    assert "單項診斷指令" in source
    assert "task_failure_drilldown_rows(task_summary)" in source
    assert "task_retry_options(task_summary)" in source
    assert 'task_summary.get("by_error_category")' in source
    assert "失敗原因分類" in source
    assert 'task_summary.get("error_category_daily")' in source
    assert "失敗原因趨勢" in source
    assert 'task_summary.get("alerts")' in source
    assert 'alert.get("severity") == "error"' in source
    assert 'alert.get("severity") == "warning"' in source
    assert "maintenance_retry_failed_task" in source
    assert "maintenance_inspect_task_id" in source
    assert 'f"/tasks/{selected_retry_task_id}/retry"' in source
    assert "/reports/quality/summary?limit=20" in source
    assert "報告品質 Gate 總覽" in source
    assert "外部部署選配狀態" in source
    assert "render_external_deployment_panel(upgrade_audit)" in source
    assert "render_background_task_observability_panel(service_snapshot, task_summary)" in source
    assert (
        "external_deployment_warning_rows(upgrade_audit)"
        not in Path("app/ui/system_settings_maintenance.py").read_text()
    )
    assert (
        'st.expander("背景任務觀測"'
        not in Path("app/ui/system_settings_maintenance.py").read_text()
    )
    assert "正式分析不等於買進" in source
    assert "letter-spacing: -" not in combined
    assert "stock-hero" not in combined
    assert "https://fonts.googleapis.com" not in combined
    assert "asyncio.run" not in source
    assert "timeout=900" not in source
    assert "API_TASK_QUEUE_TIMEOUT_SECONDS = 20" in source
    assert "API_TASK_PREFLIGHT_TIMEOUT_SECONDS = 3" in source
    assert "def api_task_post(" in source
    assert "def api_task_queue_status(" in source
    assert "def submit_background_task(" in source
    assert "def task_queue_preflight_ready(" in source
    assert "def task_queue_unready_message(" in source
    assert "def task_queue_worker_warning(" in source
    assert "def task_queue_health_rows(" in source
    assert "def task_queue_health_alert(" in source
    assert "def external_deployment_warning_rows(" in source
    assert "def external_deployment_smoke_commands(" in source
    assert "def external_deployment_warning_rows(" not in ui.MAINTENANCE_STATUS_SOURCE.read_text()
    assert "def task_failure_drilldown_rows(" in source
    assert "def task_retry_options(" in source
    assert "def task_status_diagnostic_rows(" in source
    assert '"category": row.get("error_category")' in source
    assert '"next_steps": _task_next_steps_text(row)' in source
    assert '"category": task_status.get("error_category")' in source
    assert '"next_steps": _task_status_next_steps_text(task_status)' in source
    assert "失敗診斷" in source
    assert "仍會嘗試送出" in source
    assert "Celery worker 未回應" in source
    assert "/pipeline/run_discovered_async" in source
    assert "/tasks/data-operation" in source
    assert "/follow-up/run_async" in source
    assert 'submit_api_task(\n                    "/pipeline/run_discovered_async"' in source
    assert 'submit_api_task(\n                    "/reports/generate_async"' in source
    assert 'api_post("/pipeline/run_discovered_async"' not in source
    assert 'api_post("/reports/generate_async"' not in source
    assert "def request_error_message(" in source
    assert 'error_message="股價刷新任務送出失敗"' in source
    assert 'error_message="分析背景任務送出失敗"' in source
    assert 'error_message="自動補強任務送出失敗"' in source
    assert 'st.session_state["last_data_task_id"]' not in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert 'task_state_key="last_data_task_id"' in source
    assert 'task_state_key="last_async_task_id"' in source
    assert 'task_state_key="last_follow_up_task_id"' in source


def test_follow_up_controls_use_scoped_widget_keys() -> None:
    source = ui.read_ui_source()

    assert (
        'def render_follow_up_controls(report_id: int, markdown: str, scope: str = "report")'
        in source
    )
    assert 'key_suffix = f"{scope}_{report_id}"' in source
    assert 'key=f"followup_purpose_{key_suffix}"' in source
    assert 'scope="analysis_result"' in source
    assert 'scope="history_report"' in source
    assert "manual_tracking_selected" in source
    assert '"force_refresh": bool(force_refresh or manual_tracking_selected)' in source
    assert 'key=f"followup_purpose_{report_id}"' not in source
