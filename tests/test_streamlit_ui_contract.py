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
    external_readiness_service_source = Path(
        "app/services/external_deployment_readiness.py"
    ).read_text()
    external_enablement_service_source = Path(
        "app/services/external_deployment_enablement.py"
    ).read_text()
    external_local_dependency_service_source = Path(
        "app/services/external_deployment_local_dependencies.py"
    ).read_text()
    external_profile_catalog_source = Path(
        "app/services/external_deployment_profiles.py"
    ).read_text()
    company_filing_runtime_rows_service_source = Path(
        "app/services/company_filing_runtime_rows.py"
    ).read_text()
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
    assert "from app.ui.operator_status import (" in source
    assert "operator_status_cards(" in source
    assert '"今日狀態"' in source
    assert '"/tasks/summary?days=7&limit=10"' in source
    assert '"/llm/quota"' in source
    assert '"/reports?limit=5"' in source
    assert "operator-status-grid" in combined
    assert "operator-status-card" in combined
    assert "from app.ui.report_health import latest_report_health_summary" in source
    assert "latest_report_health_summary(" in source
    assert "report-health-strip" in combined
    assert "report-health-card" in combined
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
    assert "def render_external_deployment_panel(" in source
    assert "service_snapshot: dict | None = None" in source
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
    assert "from app.services.company_filing_runtime_rows import (" in source
    assert "visual_rag_runtime_available" in company_filing_runtime_rows_service_source
    assert "structured_api_configured" in company_filing_runtime_rows_service_source
    assert "visual_rag_model_chain" in company_filing_runtime_rows_service_source
    assert (
        "visual_rag_runtime_available" not in Path("app/ui/data_enrichment_runtime.py").read_text()
    )
    assert Path("pages/01_分析工作區.py").exists()
    assert Path("pages/02_報告中心.py").exists()
    assert Path("pages/03_資料補強.py").exists()
    assert Path("pages/04_系統設定.py").exists()
    assert 'data_tabs = st.tabs(["市場快取與刷新", "手動補充", "RSS 匯入"])' in source
    assert 'settings_tabs = st.tabs(["股票範圍", "自動排程", "維護"])' in source
    assert '"匯入新聞/研究摘要"' in source
    assert '"匯入 RAG"' not in source
    assert "會更新最新版報告的股價與成交量判讀" in source
    assert "會補齊五年財務與品質門檻需要的財報資料" in source
    assert "會更新本益比、股價淨值比與殖利率判讀" in source
    assert "會補齊公司文件、法說會或公開資訊缺口" in source
    assert "action-impact-grid" in combined
    assert "operator-workbench" in combined
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
        "def external_deployment_env_key_rows("
        in ui.EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    )
    assert (
        "def external_deployment_env_resolution_rows("
        in ui.EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    )
    assert (
        "def external_deployment_env_check_summary_rows("
        in ui.EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    )
    assert (
        "def external_deployment_env_check_detail_rows("
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
    assert "from app.services.external_deployment_readiness import (" in (
        ui.EXTERNAL_DEPLOYMENT_COMMON_SOURCE.read_text()
    )
    assert '"部署決策"' in external_readiness_service_source
    assert '"啟用分類"' in external_readiness_service_source
    assert '"成本/額度"' in external_readiness_service_source
    assert '"建議路徑"' in external_readiness_service_source
    assert "from app.services.external_deployment_profiles import" in (
        external_readiness_service_source
    )
    assert "EXTERNAL_ENABLEMENT_METADATA = {" in external_profile_catalog_source
    assert "EXTERNAL_LOCAL_ACTION_METADATA = {" in external_profile_catalog_source
    assert "EXTERNAL_ENABLEMENT_METADATA = {" not in external_readiness_service_source
    assert "EXTERNAL_LOCAL_ACTION_METADATA = {" not in external_readiness_service_source
    assert "def external_deployment_env_key_rows(" in (
        ui.EXTERNAL_DEPLOYMENT_ENV_KEYS_SOURCE.read_text()
    )
    assert "def external_deployment_env_resolution_rows(" in (
        ui.EXTERNAL_DEPLOYMENT_ENV_KEYS_SOURCE.read_text()
    )
    assert "def external_deployment_env_check_summary_rows(" in (
        ui.EXTERNAL_DEPLOYMENT_ENV_KEYS_SOURCE.read_text()
    )
    assert "def external_deployment_env_check_detail_rows(" in (
        ui.EXTERNAL_DEPLOYMENT_ENV_KEYS_SOURCE.read_text()
    )
    assert "from app.services.external_deployment_env_gaps import (" in (
        ui.EXTERNAL_DEPLOYMENT_ENV_KEYS_SOURCE.read_text()
    )
    assert "EXTERNAL_ENV_KEY_HINTS" not in ui.EXTERNAL_DEPLOYMENT_ENV_KEYS_SOURCE.read_text()
    assert "from app.ui.external_deployment_env_keys import (" in (
        ui.EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    )
    assert "外部設定缺口" in ui.MAINTENANCE_DEPLOYMENT_PANEL_SOURCE.read_text()
    assert "外部設定處理計畫" in ui.MAINTENANCE_DEPLOYMENT_PANEL_SOURCE.read_text()
    assert "目前 .env 外部部署檢查" in ui.MAINTENANCE_DEPLOYMENT_PANEL_SOURCE.read_text()
    assert "from app.ui.maintenance_deployment_presenter import (" in (
        ui.MAINTENANCE_DEPLOYMENT_PANEL_SOURCE.read_text()
    )
    assert "def recommended_maintenance_operation_id(" in (
        ui.MAINTENANCE_DEPLOYMENT_PRESENTER_SOURCE.read_text()
    )
    assert "def recommended_maintenance_operation_id(" not in (
        ui.MAINTENANCE_DEPLOYMENT_PANEL_SOURCE.read_text()
    )
    assert "index=recommended_operation_index" in (
        ui.MAINTENANCE_DEPLOYMENT_PANEL_SOURCE.read_text()
    )
    assert (
        "def high_risk_filing_unlocker_rows(" in ui.EXTERNAL_DEPLOYMENT_UNLOCKER_SOURCE.read_text()
    )
    assert (
        "def _high_risk_unlocker_configuration_detail("
        in ui.EXTERNAL_DEPLOYMENT_UNLOCKER_SOURCE.read_text()
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
    assert (
        "def report_observability_recommendation_rows("
        in ui.REPORT_OBSERVABILITY_PANEL_SOURCE.read_text()
    )
    assert "graph_reasoning_path_count" in ui.REPORT_OBSERVABILITY_PANEL_SOURCE.read_text()
    assert "GraphRAG paths" in ui.REPORT_OBSERVABILITY_PANEL_SOURCE.read_text()
    assert "Graph 覆蓋率" in ui.REPORT_OBSERVABILITY_PANEL_SOURCE.read_text()
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
    assert "def task_execution_context_rows(" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "執行上下文" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "sensitive_keys_masked" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
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
    assert "/reports/retention/preview" in source
    assert "可清舊報告檔" in source
    assert "deletable_artifact_count" in source
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
    assert 'summary.get("recommendations")' in source
    assert "render_report_observability_panel(report_observability_summary)" in source
    assert "優先優化清單" in source
    assert "建議處理順序" in source
    assert "Queue / Worker readiness" in source
    assert "Queue 修復指引" in source
    assert "task_queue_health_rows(service_snapshot)" in source
    assert "task_queue_health_alert(service_snapshot)" in source
    assert "task_queue_repair_rows(service_snapshot)" in source
    assert "task_queue_smoke_command(service_snapshot)" in source
    assert "external_deployment_warning_rows(upgrade_audit)" in source
    assert "external_deployment_env_check_summary_rows(" in source
    assert "external_deployment_env_check_detail_rows(" in source
    assert '".env 檢查目標"' in source
    assert "external_deployment_smoke_commands(upgrade_audit)" in source
    assert "local_dependency_status_rows(service_snapshot)" in source
    assert "local_dependency_last_start_rows(service_snapshot)" in source
    assert "local_dependency_repair_rows(service_snapshot)" in source
    assert "high_risk_filing_unlocker_rows(upgrade_audit)" in source
    assert "local_neo4j_operation_rows(upgrade_audit)" in source
    assert "local_unlocker_operation_rows(upgrade_audit)" in source
    assert "structured_filing_api_operation_rows(upgrade_audit)" in source
    assert "高風險文件 unlocker" in source
    assert "本機 Neo4j / GraphRAG 操作提示" in source
    assert "本機 unlocker 操作提示" in source
    assert "結構化文件 API 操作提示" in source
    assert "Configuration check" in source
    assert "configuration_check" in source
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
    assert "外部部署 readiness checklist" in source
    assert "外部部署啟用摘要" in source
    assert "有效外部缺口" in source
    assert "本機免費可補" in source
    assert "需付費 API" in source
    assert "最近本機依賴啟動" in source
    assert "本機依賴修復指引" in source
    assert "本機依賴狀態" in source
    assert 'load_api_json_or_default(\n        "/maintenance/operations"' in source
    assert "def maintenance_operation_rows(" in source
    assert "def maintenance_operation_post_run_check_rows(" in source
    assert "def maintenance_operation_post_run_diagnostic_action_ids(" in source
    assert 'LAST_MAINTENANCE_OPERATION_RESULT_KEY = "last_maintenance_operation_result"' in source
    assert 'LAST_POST_RUN_DIAGNOSTIC_RESULT_KEY = "last_post_run_diagnostic_result"' in source
    assert "本機依賴操作" in source
    assert "選擇維護操作" in source
    assert "後續驗證" in source
    assert '"可執行診斷"' in source
    assert "可直接執行的後續診斷" in source
    assert "maintenance_post_run_diagnostic_" in source
    assert 'f"/maintenance/diagnostics/{action_id}/run"' in source
    assert "confirm_maintenance_operation" in source
    assert "maintenance_run_operation" in source
    assert "st.session_state[LAST_MAINTENANCE_OPERATION_RESULT_KEY] = result" in source
    assert "st.session_state.get(LAST_MAINTENANCE_OPERATION_RESULT_KEY)" in source
    assert "st.session_state[LAST_POST_RUN_DIAGNOSTIC_RESULT_KEY] = result" in source
    assert "st.session_state.get(LAST_POST_RUN_DIAGNOSTIC_RESULT_KEY)" in source
    assert "後續診斷結果" in source
    assert "summary_rows" in source
    assert "診斷摘要" in source
    assert 'f"/maintenance/operations/{selected_operation_id}/run"' in source
    assert '"confirmed": True' in source
    assert "timeout=300" in source
    assert "def external_deployment_readiness_rows(" in source
    assert "def local_dependency_status_rows(" in source
    assert "def local_dependency_last_start_rows(" in source
    assert "def local_dependency_repair_rows(" in source
    assert '"部署決策"' in external_readiness_service_source
    assert '"啟用分類"' in external_readiness_service_source
    assert '"成本/額度"' in external_readiness_service_source
    assert '"建議路徑"' in external_readiness_service_source
    assert "EXTERNAL_ENABLEMENT_METADATA = {" in external_profile_catalog_source
    assert "EXTERNAL_ENABLEMENT_METADATA = {" not in external_readiness_service_source
    assert "from app.services.external_deployment_enablement import (" in (
        external_readiness_service_source
    )
    assert "def external_deployment_enablement_profile(" not in external_readiness_service_source
    assert "def external_deployment_enablement_profile(" in external_enablement_service_source
    assert "def external_deployment_local_projection(" in external_enablement_service_source
    assert "def external_deployment_enablement_summary(" in external_readiness_service_source
    assert "def external_deployment_enablement_summary_rows(" in external_readiness_service_source
    assert "def external_deployment_pending_gap_rows(" in external_readiness_service_source
    assert "def external_deployment_pending_gap_display_rows(" in external_readiness_service_source
    assert "def local_dependency_status_rows(" not in external_readiness_service_source
    assert "def local_dependency_status_rows(" in external_local_dependency_service_source
    assert "def local_dependency_last_start_rows(" not in external_readiness_service_source
    assert "def local_dependency_last_start_rows(" in external_local_dependency_service_source
    assert "def local_dependency_repair_rows(" not in external_readiness_service_source
    assert "def local_dependency_repair_rows(" in external_local_dependency_service_source
    assert "待處理缺口分類" in source
    assert '"本機動作"' in external_readiness_service_source
    assert '"本機指令"' in external_readiness_service_source
    assert "端口已啟動，需驗證" in external_readiness_service_source
    assert "local_dependency_wait" in external_readiness_service_source
    assert '"驗證指令"' in external_readiness_service_source
    assert "render_external_deployment_panel(\n        upgrade_audit," in source
    assert 'load_api_json_or_default(\n        "/services/external-deployment/env-check"' in source
    assert "maintenance_operations,\n        external_env_check,\n    )" in source
    assert 'load_api_json_or_default(\n        "/maintenance/diagnostics"' in source
    assert "render_background_task_observability_panel(\n        service_snapshot," in source
    assert "maintenance_diagnostics,\n    )" in source
    assert "def maintenance_diagnostic_action_rows(" in source
    assert "維護診斷動作" in source
    assert "選擇診斷動作" in source
    assert "safe_to_run" in source
    assert "安全 no-op" in source
    assert "maintenance_run_diagnostic_action" in source
    assert 'f"/maintenance/diagnostics/{selected_action_id}/run"' in source
    assert "timeout=120" in source
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
    assert "def task_queue_smoke_hint(" in source
    assert "task_submission_smoke.py" in source
    assert "def task_queue_health_rows(" in source
    assert "def task_queue_health_alert(" in source
    assert "def task_queue_repair_rows(" in source
    assert 'task_queue.get("repair_plan")' in source
    assert "def _task_queue_repair_plan_row(" in source
    assert "def task_queue_processing_label(" in source
    assert "Queue 執行" in source
    assert '"修復指令"' in source
    assert '"驗證指令"' in source
    assert "processing_ready" in source
    assert "def external_deployment_warning_rows(" in source
    assert "def external_deployment_smoke_commands(" in source
    assert "def external_deployment_warning_rows(" not in ui.MAINTENANCE_STATUS_SOURCE.read_text()
    assert "def task_failure_drilldown_rows(" in source
    assert "def task_failure_action_route_rows(" in source
    assert "失敗處理路徑" in source
    assert "外部配置缺失" in source
    assert "retry_guarded" in source
    assert "disabled=selected_retry_guarded" in source
    assert "先修配置再重試" in source
    assert "def task_retry_options(" in source
    assert "def task_status_diagnostic_rows(" in source
    assert '"category": row.get("error_category")' in source
    assert '"next_steps": _task_next_steps_text(row)' in source
    assert '"category": task_status.get("error_category")' in source
    assert '"action_route": task_failure_action_route(task_status)' in source
    assert "task_failure_action_route_detail(task_status)" in source
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
