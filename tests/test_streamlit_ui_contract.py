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
    assert "workspace-topbar is-compact" in source
    assert "AI 台股操作者控制台" in source
    assert "研究主題、補資料、看報告，集中在同一個工作台" not in source
    assert "先看下一步建議" not in source
    assert "workflow-strip" in combined
    assert "workflow-strip is-compact" in source
    assert "workspace-ledger" in combined
    assert "workspace-ledger is-compact" in source
    assert "credibility_html" in source
    assert "credibility-grid" in combined
    assert "upgrade_audit_html" in source
    assert "from app.ui.maintenance_panels import (" in source
    assert "from app.ui.operator_route_controls import render_operator_route_button" in source
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
    assert "def render_report_document(" in source
    assert "def load_legacy_streamlit_components(" in source
    assert "render_report_document(report_html(markdown, result), height=820)" in source
    assert 'getattr(streamlit_module, "iframe", None)' in source
    assert "iframe(document_html, width=\"stretch\", height=height)" in source
    assert "components_importer().html(document_html, height=height, scrolling=True)" in source
    assert "import streamlit.components.v1" not in source
    assert "components.html(report_html(" not in source
    assert "from app.ui.report_follow_up_controls import" in source
    assert "from app.ui.report_markdown import (" in source
    assert "from app.ui.report_candidate_audit import" in source
    assert "from app.ui.report_formatters import" in source
    assert "from app.ui.report_sections import (" in source
    assert "from app.ui.operator_status import (" in source
    assert "from app.ui.operator_routes import operator_route_target" in source
    assert "from app.ui.operator_route_controls import render_operator_route_button" in source
    assert "operator_status_cards(" in source
    assert "model_order_label" in source
    assert "limited_model_label" in source
    assert "high_quota_fallback_label" in source
    assert '"今日狀態"' in source
    assert '"/tasks/summary?days=7&limit=10"' in source
    assert '"/llm/quota"' in source
    assert '"/reports?limit=5"' in source
    assert "operator-status-grid" in combined
    assert "operator-status-card" in combined
    assert "from app.ui.operator_decisions import (" in source
    assert "operator_next_best_action(" in source
    assert "operator_secondary_actions(" in source
    assert "from app.ui.data_gap_actions import data_gap_action_items" in source
    assert "def _primary_data_gap_action(" in source
    assert 'data_gap_action.get("route_hint")' in source
    assert "operator-decision-card" in combined
    assert "operator-secondary-actions" in combined
    assert "operator-action-controls" in combined
    assert "operator-action-controls is-primary" in source
    assert "按下後會帶你到對應頁面" not in source
    assert "_render_operator_primary_action_control(" in source
    assert "_render_operator_action_controls(" in source
    assert "def _operator_source_label(" in source
    assert '"optimization:auto_local_defaults"' in source
    assert "本機 defaults 優化缺口" in source
    assert '"optimization:company_filing_structured_api_fallback"' in source
    assert "公司文件結構化 API 選配" in source
    assert source.index("_render_operator_workbench()") < source.index("workflow-strip")
    assert "operator_route_target(" in source
    assert "st.switch_page(" in source
    assert "pending_selected_report_id" in source
    assert "maintenance_inspect_task_id" in source
    assert "incident-action-controls" in combined
    assert "_render_incident_action_controls(" in source
    assert "incident-priority-summary" in combined
    assert "optimization-progress-operator-summary" in combined
    assert "optimization-progress-scope-summary" in combined
    assert "optimization_progress_operator_summary(" in source
    assert "optimization_progress_scope_summary(" in source
    assert "def _render_optimization_progress_operator_summary(" in source
    assert "def _render_optimization_progress_scope_summary(" in source
    assert "def optimization_progress_operator_summary(" in ui.MAINTENANCE_STATUS_SOURCE.read_text()
    assert "def optimization_progress_scope_summary(" in ui.MAINTENANCE_STATUS_SOURCE.read_text()
    assert "_render_incident_priority_summary(incidents)" in source
    assert "def incident_action_priority_summary(" in source
    assert "先處理 {critical} 個 Critical 事件" in source
    assert "歷史趨勢/觀測" in source
    assert "incident_action_summaries(incidents)" in source
    assert "def incident_action_summaries(" in source
    assert "def incident_action_caption(" in source
    assert 'key=f"incident_action_{index}"' in source
    assert '"action_label": incident_action_label(incident, index)' in source
    assert "def incident_action_label(" in source
    assert "下一步建議" in source
    assert 'f"/reports/{int(latest_report_id)}"' in source
    assert 'f"/reports/{int(latest_report_id)}/follow-up/plan"' in source
    assert "from app.ui.report_health import latest_report_health_summary" in source
    assert "latest_report_health_summary(" in source
    assert '"title": report_payload.get("title")' in source
    assert '"generated_at": report_payload.get("generated_at")' in source
    assert "report_meta_label" in source
    assert "follow_up_state" in source
    assert "summary.get(\"action_label\"" in source
    assert "report-health-strip" in combined
    assert "report-health-card" in combined
    assert "report-health-action" in combined
    assert "from app.ui.report_lifecycle import latest_report_lifecycle" in source
    assert "latest_report_lifecycle(" in source
    assert "from app.ui.data_gap_actions import data_gap_action_items" in source
    assert "def _primary_data_gap_action(" in source
    assert "primary_action_detail" in source
    assert "_render_report_lifecycle_action(" in source
    assert 'key="report_lifecycle_primary_action"' in source
    assert 'lifecycle.get("route_hint")' in source
    assert "report-lifecycle-strip" in combined
    assert "report-lifecycle-step" in combined
    assert "報告生命週期" in source
    assert "def report_reader_decision_summary(" in source
    assert "def _render_report_reader_decision_summary(" in source
    assert "report_reader_decision_summary(lifecycle, health_summary)" in source
    assert "report-reader-decision" in combined
    assert "閱讀決策" in source
    assert "可先閱讀，但投資判斷需標示限制" in source
    assert "from app.ui.data_enrichment_market import render_market_data_tab" in source
    assert "from app.ui.data_enrichment_manual import render_manual_ingest_tab" in source
    assert "from app.ui.data_enrichment_rss import render_rss_ingest_tab" in source
    assert "render_allowlist_scope_summary(whitelist, allowed_tickers)" in source
    assert "from app.ui.dashboard_core import configure_page" in source
    assert "from app.ui.dashboard_core import *" not in source
    assert "import *" not in source
    assert "F403" not in source
    assert "F405" not in source
    assert "upgrade-audit-grid" in combined
    assert '[data-baseweb="tab"] p' in combined
    assert '[data-testid="stToolbar"]' in styles
    assert '[data-testid="stDecoration"]' in styles
    assert '[data-testid="stStatusWidget"]' in styles
    assert '[data-testid="stSidebarCollapseButton"]' in styles
    assert ".stDeployButton" in styles
    assert '[data-testid="stSidebarNavLink"] {\n    min-height: 44px !important;' in styles
    assert 'a[aria-label="Link to heading"]' in styles
    assert "pointer-events: none !important" in styles
    assert "def render_analysis_workspace() -> None:" in source
    assert "def analysis_submission_ready(" in source
    assert "def analysis_submission_summary(" in source
    assert "def analysis_submission_quota_pressure(" in source
    assert "def _render_analysis_submission_summary(" in source
    assert "analysis-submission-summary" in combined
    assert "quota-pressure" in combined
    assert "額度壓力：" in source
    assert "適合快速試跑或額度偏緊時使用" in source
    assert "適合收盤後或額度剛重置時執行" in source
    assert "送出前確認" in source
    assert "可送出分析背景任務" in source
    assert "手動模式請先選擇至少一檔股票" in source
    assert "analysis_quota_confirmed = st.checkbox(" in source
    assert 'key="confirm_analysis_submission_quota_usage"' in source
    assert "我了解這會送出分析背景任務並消耗 AI/API 額度" in source
    assert "避免誤觸與免費額度消耗" in source
    assert "ai_discovery_mode=bool(ai_discovery_mode)" in source
    assert "manual_tickers=tickers" in source
    assert "disabled=not analysis_submission_ready(" in source
    assert "def render_report_center() -> None:" in source
    assert "def render_data_enrichment() -> None:" in source
    assert "def render_system_settings() -> None:" in source
    assert "def render_maintenance_tab() -> None:" in source
    assert "def render_external_deployment_panel(" in source
    assert "service_snapshot: dict | None = None" in source
    assert "def render_background_task_observability_panel(" in source
    assert "def render_report_quality_panel(report_quality_summary: dict) -> None:" in source
    assert "def render_submission_guard_panel(service_snapshot: dict) -> None:" in source
    assert "高風險操作保護" in source
    assert "submission_guard_metric_values(service_snapshot)" in source
    assert "submission_guard_rows(service_snapshot)" in source
    assert "完整" in source
    assert "需處理" in source
    assert "已保護" in source
    assert "缺保護" in source
    assert "未知" in source
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
    assert "def scope_source_summary(" in ui.SYSTEM_SETTINGS_SCOPE_SOURCE.read_text()
    assert "def _render_scope_source_summary(" in ui.SYSTEM_SETTINGS_SCOPE_SOURCE.read_text()
    assert "scope-source-summary" in combined
    assert "系統靜態股票範圍" in ui.SYSTEM_SETTINGS_SCOPE_SOURCE.read_text()
    assert "不是本次報告的動態候選名單" in ui.SYSTEM_SETTINGS_SCOPE_SOURCE.read_text()
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
    assert 'key="data_enrichment_section"' in source
    assert "pending_data_enrichment_section" in source
    assert 'data_tabs = st.tabs(["市場快取與刷新", "手動補充", "RSS 匯入"])' not in source
    assert 'settings_section = st.radio(' in source
    assert 'key="settings_section"' in source
    assert "pending_settings_section" in source
    assert "pending_maintenance_focus" in source
    assert '"pending_maintenance_focus": "task_observability"' in source
    assert "maintenance_focus_from_pending_section(pending_section)" in source
    assert "def _consume_pending_maintenance_focus(" in source
    assert 'if maintenance_focus == "ai_quota":' in source
    assert 'if maintenance_focus != "ai_quota":' in source
    assert 'if maintenance_focus == "task_observability":' in source
    assert 'if maintenance_focus != "task_observability":' in source
    assert '"匯入新聞/研究摘要"' in source
    assert '"匯入 RAG"' not in source
    assert "會更新最新版報告的股價與成交量判讀" in source
    assert "會補齊五年財務與品質門檻需要的財報資料" in source
    assert "會更新本益比、股價淨值比與殖利率判讀" in source
    assert "會補齊公司文件、法說會或公開資訊缺口" in source
    assert "action-impact-grid" in combined
    assert "market_operation_readiness_rows(" in source
    assert "_render_market_operation_readiness(" in source
    assert "market-operation-readiness" in combined
    assert "執行前檢查" in source
    assert "可送出背景任務" in source
    assert "def market_submission_preflight_summary(" in source
    assert "_render_market_submission_summary(" in source
    assert "market-submission-summary" in combined
    assert "送出前摘要" in source
    assert "避免重複送出" in source
    assert "def pending_market_handoff_summary(" in source
    assert "_render_pending_market_handoff(" in source
    assert "market-handoff-banner" in combined
    assert "補強導引" in source
    assert "先處理白名單提醒，再" in source
    assert "task_queue_status = _task_queue_status_from_service_snapshot(service_snapshot)" in source
    assert "task_queue=task_queue_status" in source
    assert "task_queue_blocks_submission = bool(_task_queue_block_reason(task_queue_status))" in source
    assert "def _task_queue_block_reason(" in source
    assert "背景任務未就緒，請先到維護頁檢查 Worker" in source
    assert "背景任務未就緒，請先到維護頁檢查 Redis/Celery" in source
    assert "from app.ui.data_gap_actions import (" in source
    assert "data_gap_action_items(" in source
    assert "data_gap_action_summary(" in source
    assert "data-gap-action-map" in combined
    assert "data-gap-action-card" in combined
    assert "data-gap-action-controls" in combined
    assert "資料缺口行動地圖" in source
    assert "from app.ui.operator_route_controls import render_operator_route_button" in source
    assert "_render_data_gap_action_controls(" in source
    assert 'key=f"data_gap_action_{index}"' in source
    assert "def market_cache_operator_summary(" in source
    assert "def _render_market_cache_operator_summary(" in source
    assert "market_cache_operator_summary(cache_summary" in source
    assert "市場快取新鮮度" in source
    assert "cached-stale" in source
    assert "market-cache-readiness" in combined
    assert "market-cache-card" in combined
    assert "def market_data_operation_button_type(" in source
    assert "MARKET_DATA_OPERATIONS = {" in source
    assert 'type=market_data_operation_button_type(pending_operation, "market_refresh")' in source
    assert (
        'type=market_data_operation_button_type(pending_operation, "company_filings_fetch")'
        in source
    )
    assert "market_operation_confirmed = st.checkbox(" in source
    assert 'key="confirm_market_data_operation_submission"' in source
    assert "我了解這會送出資料補強背景任務" in source
    assert "避免誤觸刷新" in source
    assert "or not market_operation_confirmed" in source
    assert "filing_url_confirmed = st.checkbox(" in source
    assert 'key="confirm_company_filing_url_import"' in source
    assert "我了解這會送出 URL 公司文件匯入背景任務" in source
    assert "避免誤觸 URL 匯入" in source
    assert "disabled=not filing_url_ready or not filing_url_confirmed" in source
    assert "manual_news_preflight_summary(" in source
    assert "company_filing_text_preflight_summary(" in source
    assert "company_filing_url_preflight_summary(" in source
    assert "render_data_ingest_submission_summary(" in source
    assert "data-ingest-submission-summary" in combined
    assert "資料送出前摘要" in source
    assert "不會消耗 AI 額度" in source
    assert "rss_fetch_confirmed = st.checkbox(" in source
    assert 'key="confirm_rss_fetch_submission"' in source
    assert "我了解這會送出 RSS 抓取背景任務" in source
    assert "避免誤觸 RSS 抓取" in source
    assert "disabled=not feed_ready or not rss_fetch_confirmed" in source
    assert "rss_fetch_preflight_summary(" in source
    assert "背景任務會排隊抓取與匯入文本" in source
    assert 'key="market_data_tickers"' in source
    assert "operator-workbench" in combined
    assert "manual_news_ready = bool(title.strip() and text.strip())" in source
    assert "manual_news_confirmed = st.checkbox(" in source
    assert 'key="confirm_manual_news_import"' in source
    assert "我了解這會直接寫入新聞/研究摘要資料庫" in source
    assert "避免誤觸手動匯入" in source
    assert "disabled=not manual_news_ready or not manual_news_confirmed" in source
    assert "filing_text_confirmed = st.checkbox(" in source
    assert 'key="confirm_manual_company_filing_import"' in source
    assert "我了解這會直接寫入公司文件資料庫" in source
    assert "避免誤觸公司文件匯入" in source
    assert "disabled=not filing_text_ready or not filing_text_confirmed" in source
    assert 'or schedule_task == "latest_report_update"' in source
    assert "schedule_save_confirmed = st.checkbox(" in source
    assert 'key="confirm_schedule_settings_save"' in source
    assert "我了解這會更新自動排程與每日維護設定" in source
    assert "避免誤觸排程變更" in source
    assert "disabled=not schedule_ready or not schedule_save_confirmed" in source
    assert '"產業分類篩選"' in source
    assert 'st.columns([0.20, 0.80], gap="medium")' not in source
    assert 'report_download_cols = st.columns(2, gap="small")' in source
    assert 'report_action_cols = st.columns([0.16, 0.16, 0.68], gap="small")' not in source
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
    assert 'with st.expander("報告管理")' not in report_center_source
    assert 'with st.expander("疑難排解：執行紀錄")' in report_center_source
    assert report_center_source.index('with st.expander("疑難排解：執行紀錄")') < (
        report_center_source.index('"刪除此報告",')
    )
    assert "進階操作，只在需要移除最新版報告時使用。" in report_center_source
    assert "report_delete_confirmed = st.checkbox(" in report_center_source
    assert 'key=f"confirm_delete_report_{selected_id}"' in report_center_source
    assert 'disabled=not report_delete_confirmed' in report_center_source
    assert "刪除報告會移除目前最新版報告與安全範圍內的報告檔" in report_center_source
    assert "run_delete_confirmed = st.checkbox(" in report_center_source
    assert 'key=f"confirm_delete_run_{selected_run_id}"' in report_center_source
    assert 'key=f"delete_run_{selected_run_id}"' in report_center_source
    assert 'disabled=not run_delete_confirmed' in report_center_source
    assert "刪除分析紀錄只會移除此筆執行歷史，不會刪除目前最新版報告" in (
        report_center_source
    )
    assert "避免誤觸" in report_center_source
    assert 'with st.expander("背景任務狀態", expanded=False):' in report_center_source
    assert 'refresh_key=f"history_run_task_status_{selected_run_id}"' in report_center_source
    assert 'st.button("查詢背景任務狀態")' not in report_center_source
    assert 'st.json(api_get(f"/tasks/{selected_task_id}"))' not in report_center_source
    assert "def task_status_diagnostic_rows(" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "def task_execution_context_rows(" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "執行上下文" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "def task_status_state_label(" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "def task_run_source_label(" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "已遮蔽敏感欄位" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "cancel_confirmed = st.checkbox(" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert 'key=f"{refresh_key}_confirm_cancel"' in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "retry_confirmed = st.checkbox(" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert 'key=f"{refresh_key}_confirm_retry"' in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "disabled=cancel_blocked or not cancel_confirmed" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "disabled=retry_blocked or not retry_confirmed" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "可能消耗模型或資料源額度" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "def task_action_preflight_summary(" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "def render_task_action_preflight_summary(" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "task-action-preflight-summary" in ui.STYLE_SOURCE.read_text()
    assert "此任務不支援一鍵重試" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "此任務已結束，不能取消" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "此任務已成功，不需要一鍵重試" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "此任務仍在執行，不能重試" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
    assert "避免重複失敗與額度浪費" in ui.TASK_STATUS_PANEL_SOURCE.read_text()
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
    assert "建立分析後，這裡會顯示目前保留的最新版報告。" in source
    assert "def empty_report_action_summary(" in source
    assert "建立第一份最新版報告" in source
    assert "前往分析工作區建立報告；完成後回到這裡閱讀最新版。" in source
    assert '"action_label": "建立分析"' in source
    assert '"route_hint": "analysis"' in source
    assert 'load_api_json_or_default(\n        "/reports?limit=5"' in source
    assert "latest_by_topic(20)" not in source
    assert "def latest_report_picker_state(" in source
    assert "目前最新版報告" in source
    assert "選擇主題最新版報告" in source
    assert "這不是歷史版本清單" in source
    assert "每個主題只顯示最新一份可讀報告" in source
    assert "latest-report-picker-note" in combined
    assert "flex-wrap: wrap" in combined
    assert 'button[data-testid^="stBaseButton"]' in styles
    assert 'button[data-testid^="stBaseButton"] {\n    min-height: 48px !important;' in styles
    assert '[data-testid="stSliderThumbValue"]' in styles
    assert '[data-baseweb="tag"]' in styles
    assert "min-height: 44px !important" in styles
    assert "min-height: 40px !important" not in styles
    assert '[data-baseweb="select"] > div {\n    min-height: 44px !important;' in styles
    assert styles.count('button[data-testid="stBaseButton-elementToolbar"]') == 3
    assert 'svg[role="button"]' in styles
    assert '[data-testid="stWidgetLabel"]' in styles
    assert '[data-testid="stDateInputField"]' in styles
    assert '[data-testid="stNumberInputField"]' in styles
    assert '[data-baseweb="input"]' in styles
    assert '[data-baseweb="input"] {\n    min-height: 44px !important;' in styles
    assert (
        '[data-testid="stExpander"],\n'
        '[data-testid="stExpander"] summary {\n'
        "    min-height: 44px !important;"
        in styles
    )
    assert (
        '[data-baseweb="checkbox"],\n'
        '[data-baseweb="radio"],\n'
        '[data-testid="stCheckbox"] label,\n'
        '[data-testid="stRadio"] label {\n'
        "    min-height: 44px !important;"
        in styles
    )
    assert (
        '[data-testid="stDateInputField"],\n'
        '[data-testid="stNumberInputField"],\n'
        '[data-testid="stTextInputRootElement"] input,\n'
        '[data-baseweb="input"] input {\n'
        "    min-height: 44px !important;"
        in styles
    )
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
    assert "from app.ui.incident_inbox import (" in source
    assert "incident_inbox_items(" in source
    assert "incident_counts(" in source
    assert "incident-inbox" in combined
    assert "incident-card" in combined
    assert "待處理事件" in source
    assert "/reports/observability/summary?limit=20" in source
    assert "報告生成觀測" in source
    assert "trace_captured_count" in source
    assert "keyword_fallback_count" in source
    assert 'summary.get("bottlenecks")' in source
    assert 'summary.get("recommendations")' in source
    assert "render_report_observability_panel(report_observability_summary)" in source
    assert "優先優化清單" in source
    assert "建議處理順序" in source
    assert "背景任務送出與執行狀態" in source
    assert "背景任務修復指引" in source
    assert "task_queue_health_rows(service_snapshot)" in source
    assert "task_queue_health_alert(service_snapshot)" in source
    assert "task_queue_repair_rows(service_snapshot)" in source
    assert "task_queue_smoke_command(service_snapshot)" in source
    assert "external_deployment_warning_rows(upgrade_audit)" in source
    assert "external_deployment_operator_summary(" in source
    assert "def _external_deployment_operator_summary_html(" in source
    assert "external-deployment-operator-summary" in combined
    assert "外部選配不是系統故障" in ui.MAINTENANCE_DEPLOYMENT_PRESENTER_SOURCE.read_text()
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
    assert "maintenance_retry_recommended_task" in source
    assert "recommended_retry_confirmed = st.checkbox(" in source
    assert "recommended_task_id = str(" in source
    assert 'key=f"maintenance_retry_recommended_confirm_{recommended_task_id}"' in source
    assert "selected_retry_confirmed = st.checkbox(" in source
    assert (
        'key=f"maintenance_retry_selected_confirm_{selected_retry_task_id}"'
        in source
    )
    assert "disabled=not recommended_retry_confirmed" in source
    assert "disabled=selected_retry_guarded or not selected_retry_confirmed" in source
    assert "task_retry_option_index(" in source
    assert "_submit_task_retry(str(selected_retry_task_id))" in source
    assert 'f"/tasks/{task_id}/retry"' in source
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
    assert "def maintenance_operation_post_run_diagnostic_action_rows(" in source
    assert 'LAST_MAINTENANCE_OPERATION_TASK_KEY = "last_maintenance_operation_task_id"' in source
    assert 'LAST_POST_RUN_DIAGNOSTIC_TASK_KEY = "last_post_run_diagnostic_task_id"' in source
    assert "本機依賴操作" in source
    assert "選擇維護操作" in source
    assert "後續驗證" in source
    assert '"可執行診斷"' in source
    assert "可直接執行的後續診斷" in source
    assert "maintenance_operation_post_run_diagnostic_action_rows(post_run_rows)" in source
    assert "maintenance_post_run_diagnostic_" in source
    assert 'key=f"maintenance_post_run_diagnostic_confirm_{action_id}"' in source
    assert 'f"我了解這會送出「{label}」後續診斷背景任務"' in source
    assert 'f"執行 {label}"' in source
    assert 'f"執行 {action_id}"' not in source
    assert "disabled=not action_confirmed" in source
    assert "confirm_maintenance_operation" in source
    assert "maintenance_run_operation" in source
    assert "st.session_state.get(LAST_MAINTENANCE_OPERATION_TASK_KEY)" in source
    assert "st.session_state.get(LAST_POST_RUN_DIAGNOSTIC_TASK_KEY)" in source
    assert "後續診斷結果" in source
    assert "summary_rows" in source
    assert "診斷摘要" in source
    assert 'f"/tasks/maintenance-operation/{selected_operation_id}"' in source
    assert "task_state_key=LAST_MAINTENANCE_OPERATION_TASK_KEY" in source
    assert 'refresh_key="refresh_maintenance_operation_task_status"' in source
    assert '"confirmed": True' in source
    assert "timeout=300" not in source
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
    assert source.count("render_external_deployment_panel(") >= 2
    assert 'if maintenance_focus == "external_deployment":' in source
    assert "external_deployment_rendered = True" in source
    assert "if not external_deployment_rendered:" in source
    assert '"settings:maintenance:local_defaults"' in source
    assert '"maintenance_local_defaults"' in source
    assert "render_submission_guard_panel(service_snapshot)" in source
    assert 'load_api_json_or_default(\n        "/services/external-deployment/env-check"' in source
    assert "maintenance_operations,\n            external_env_check,\n        )" in source
    assert 'load_api_json_or_default(\n        "/maintenance/diagnostics"' in source
    assert source.count("render_background_task_observability_panel(") >= 2
    assert "maintenance_diagnostics," in source
    assert "def maintenance_diagnostic_action_rows(" in source
    assert "維護診斷動作" in source
    assert "選擇診斷動作" in source
    assert "safe_to_run" in source
    assert "安全 no-op" in source
    assert "maintenance_run_diagnostic_action" in source
    assert "diagnostic_confirmed = st.checkbox(" in source
    assert 'key=f"maintenance_diagnostic_confirm_{selected_action_id}"' in source
    assert "disabled=not diagnostic_confirmed" in source
    assert 'f"我了解這會送出「{selected_label}」維護診斷背景任務"' in source
    assert 'f"執行 {selected_label}"' in source
    assert 'f"/tasks/maintenance-diagnostic/{selected_action_id}"' in source
    assert "task_state_key=MAINTENANCE_DIAGNOSTIC_TASK_KEY" in source
    assert 'refresh_key="refresh_maintenance_diagnostic_action_status"' in source
    assert "timeout=120" not in source
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
    assert "背景任務執行" in source
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
    assert "def task_failure_category_label(" in source
    assert "def task_failure_severity_label(" in source
    assert "def task_failure_next_steps_text(" in source
    assert '"category": task_failure_category_label(row.get("error_category"))' in source
    assert '"next_steps": task_failure_next_steps_text(row)' in source
    assert 'task_failure_category_label(task_status.get("error_category"))' in source
    assert '"action_route": task_failure_action_route(task_status)' in source
    assert "task_failure_action_route_detail(task_status)" in source
    assert '"next_steps": task_failure_next_steps_text(task_status)' in source
    assert "失敗診斷" in source
    assert "仍會嘗試送出" in source
    assert "背景執行 worker 未回應" in source
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
    assert "def data_task_followup_summary(" in source
    assert "def _render_data_task_followup_summary(" in source
    assert "data_task_followup_summary(task_status)" in source
    assert "def allowlist_scope_summary(" in source
    assert "def render_allowlist_scope_summary(" in source
    assert "allowlist-scope-summary" in combined
    assert "目前使用靜態白名單" in source
    assert "目前使用動態候選白名單" in source
    assert "系統設定的股票範圍" in source
    assert "data-task-followup-summary" in combined
    assert "資料任務後續處理" in source
    assert "資料補強完成" in source
    assert "等待資料補強完成" in source
    assert "資料補強未完成" in source
    assert "回報告中心確認最新版生命週期" in source
    assert 'key=f"{label}_followup_action"' in source
    assert 'task_state_key="last_async_task_id"' in source
    assert 'task_state_key="last_follow_up_task_id"' in source


def test_follow_up_controls_use_scoped_widget_keys() -> None:
    source = ui.read_ui_source()
    combined = source + "\n" + ui.STYLE_SOURCE.read_text()

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
    assert "followup_run_confirmed = st.checkbox(" in source
    assert 'key=f"followup_run_confirm_{key_suffix}"' in source
    assert "我了解這會送出自動補強背景任務" in source
    assert "避免誤觸補強" in source
    assert "def follow_up_submission_preflight_summary(" in source
    assert "def render_follow_up_submission_summary(" in source
    assert "follow_up_submission_preflight_summary(" in source
    assert "render_follow_up_submission_summary(" in source
    assert "follow-up-submission-summary" in combined
    assert "會使用背景任務、外部資料來源與可能的 AI 額度" in source
    assert "完成後套用補強結果並查看最新版生命週期" in source
    assert "disabled=not has_executable_actions or not followup_run_confirmed" in source
    assert 'key=f"followup_purpose_{report_id}"' not in source
