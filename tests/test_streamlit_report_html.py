from __future__ import annotations

from pathlib import Path

DASHBOARD_SOURCE = Path("app/ui/streamlit_dashboard.py")
DASHBOARD_CORE_SOURCE = Path("app/ui/dashboard_core.py")
API_CLIENT_SOURCE = Path("app/ui/api_client.py")
BACKGROUND_TASKS_SOURCE = Path("app/ui/background_tasks.py")
TASK_STATUS_PANEL_SOURCE = Path("app/ui/task_status_panel.py")
REPORT_STATE_SOURCE = Path("app/ui/report_state.py")
REPORT_PANELS_SOURCE = Path("app/ui/report_panels.py")
REPORT_FOLLOW_UP_CONTROLS_SOURCE = Path("app/ui/report_follow_up_controls.py")
REPORT_MARKDOWN_SOURCE = Path("app/ui/report_markdown.py")
REPORT_CANDIDATE_AUDIT_SOURCE = Path("app/ui/report_candidate_audit.py")
REPORT_FORMATTERS_SOURCE = Path("app/ui/report_formatters.py")
REPORT_SECTIONS_SOURCE = Path("app/ui/report_sections.py")
REPORT_HTML_SOURCE = Path("app/ui/report_html.py")
FOLLOW_UP_STATUS_SOURCE = Path("app/ui/follow_up_status.py")
MAINTENANCE_STATUS_SOURCE = Path("app/ui/maintenance_status.py")
MAINTENANCE_PANELS_SOURCE = Path("app/ui/maintenance_panels.py")
MAINTENANCE_DEPLOYMENT_PANEL_SOURCE = Path("app/ui/maintenance_deployment_panel.py")
MAINTENANCE_AI_PANELS_SOURCE = Path("app/ui/maintenance_ai_panels.py")
MAINTENANCE_TASK_PANELS_SOURCE = Path("app/ui/maintenance_task_panels.py")
MAINTENANCE_CLEANUP_PANEL_SOURCE = Path("app/ui/maintenance_cleanup_panel.py")
REPORT_OBSERVABILITY_PANEL_SOURCE = Path("app/ui/report_observability_panel.py")
EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE = Path("app/ui/external_deployment_diagnostics.py")
TASK_QUEUE_DIAGNOSTICS_SOURCE = Path("app/ui/task_queue_diagnostics.py")
TASK_FAILURE_DIAGNOSTICS_SOURCE = Path("app/ui/task_failure_diagnostics.py")
UI_SOURCE_FILES = [
    DASHBOARD_SOURCE,
    DASHBOARD_CORE_SOURCE,
    API_CLIENT_SOURCE,
    BACKGROUND_TASKS_SOURCE,
    TASK_STATUS_PANEL_SOURCE,
    REPORT_STATE_SOURCE,
    REPORT_PANELS_SOURCE,
    REPORT_FOLLOW_UP_CONTROLS_SOURCE,
    REPORT_MARKDOWN_SOURCE,
    REPORT_CANDIDATE_AUDIT_SOURCE,
    REPORT_FORMATTERS_SOURCE,
    REPORT_SECTIONS_SOURCE,
    REPORT_HTML_SOURCE,
    FOLLOW_UP_STATUS_SOURCE,
    MAINTENANCE_STATUS_SOURCE,
    MAINTENANCE_PANELS_SOURCE,
    MAINTENANCE_DEPLOYMENT_PANEL_SOURCE,
    MAINTENANCE_AI_PANELS_SOURCE,
    MAINTENANCE_TASK_PANELS_SOURCE,
    MAINTENANCE_CLEANUP_PANEL_SOURCE,
    REPORT_OBSERVABILITY_PANEL_SOURCE,
    EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE,
    TASK_QUEUE_DIAGNOSTICS_SOURCE,
    TASK_FAILURE_DIAGNOSTICS_SOURCE,
    Path("app/ui/analysis_workspace.py"),
    Path("app/ui/report_center.py"),
    Path("app/ui/data_enrichment.py"),
    Path("app/ui/data_enrichment_common.py"),
    Path("app/ui/data_enrichment_manual.py"),
    Path("app/ui/data_enrichment_market.py"),
    Path("app/ui/data_enrichment_rss.py"),
    Path("app/ui/data_enrichment_runtime.py"),
    Path("app/ui/system_settings.py"),
    Path("app/ui/system_settings_maintenance.py"),
]
STYLE_SOURCE = Path("app/ui/styles/stock_dashboard.css")
REPORT_STYLE_SOURCE = Path("app/ui/styles/report_html.css")


def read_ui_source() -> str:
    return "\n".join(path.read_text() for path in UI_SOURCE_FILES)


def load_report_helpers() -> dict:
    candidate_audit_source = REPORT_CANDIDATE_AUDIT_SOURCE.read_text()
    report_source = REPORT_HTML_SOURCE.read_text()
    follow_up_source = FOLLOW_UP_STATUS_SOURCE.read_text()
    maintenance_source = MAINTENANCE_STATUS_SOURCE.read_text()
    external_deployment_source = EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    task_queue_diagnostics_source = TASK_QUEUE_DIAGNOSTICS_SOURCE.read_text()
    task_failure_diagnostics_source = TASK_FAILURE_DIAGNOSTICS_SOURCE.read_text()
    namespace = {
        "__file__": str(REPORT_CANDIDATE_AUDIT_SOURCE),
    }
    exec(candidate_audit_source, namespace)
    namespace["__file__"] = str(REPORT_HTML_SOURCE)
    exec(report_source, namespace)
    exec(follow_up_source, namespace)
    exec(task_queue_diagnostics_source, namespace)
    exec(task_failure_diagnostics_source, namespace)
    exec(maintenance_source, namespace)
    exec(external_deployment_source, namespace)
    return namespace


def test_streamlit_app_defers_annotation_evaluation_for_modern_python() -> None:
    source = Path("streamlit_app.py").read_text()
    dashboard_source = DASHBOARD_SOURCE.read_text()

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
    source = read_ui_source()
    styles = STYLE_SOURCE.read_text()
    report_styles = REPORT_STYLE_SOURCE.read_text()
    combined = source + "\n" + styles + "\n" + report_styles

    assert "workspace-topbar" in combined
    assert "workflow-strip" in combined
    assert "workspace-ledger" in combined
    assert "credibility_html" in source
    assert "credibility-grid" in combined
    assert "upgrade_audit_html" in source
    assert "from app.ui.maintenance_panels import (" in source
    assert "from app.ui.maintenance_deployment_panel import render_external_deployment_panel" in source
    assert "from app.ui.maintenance_ai_panels import (" in source
    assert "from app.ui.maintenance_task_panels import render_background_task_observability_panel" in source
    assert "from app.ui.maintenance_cleanup_panel import render_maintenance_cleanup_panel" in source
    assert "from app.ui.maintenance_status import (" in source
    assert "from app.ui.external_deployment_diagnostics import (" in source
    assert "from app.ui.task_queue_diagnostics import (" in source
    assert "from app.ui.task_failure_diagnostics import (" in source
    assert "from app.ui.report_observability_panel import render_report_observability_panel" in source
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
    assert 'def render_analysis_workspace() -> None:' in source
    assert 'def render_report_center() -> None:' in source
    assert 'def render_data_enrichment() -> None:' in source
    assert 'def render_system_settings() -> None:' in source
    assert 'def render_maintenance_tab() -> None:' in source
    assert 'def render_external_deployment_panel(upgrade_audit: dict) -> None:' in source
    assert 'def render_background_task_observability_panel(' in source
    assert 'def render_report_quality_panel(report_quality_summary: dict) -> None:' in source
    assert 'def render_maintenance_cleanup_panel() -> None:' in source
    assert 'def render_external_deployment_panel(' not in MAINTENANCE_PANELS_SOURCE.read_text()
    assert 'def render_ai_usage_panel(' not in MAINTENANCE_PANELS_SOURCE.read_text()
    assert 'def render_background_task_observability_panel(' not in MAINTENANCE_PANELS_SOURCE.read_text()
    assert 'def render_maintenance_cleanup_panel(' not in MAINTENANCE_PANELS_SOURCE.read_text()
    assert 'def render_market_data_tab(allowed_tickers: list[str]) -> None:' in source
    assert 'def render_manual_ingest_tab(whitelist: Any, allowed_tickers: list[str]) -> None:' in source
    assert 'def render_rss_ingest_tab() -> None:' in source
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
    assert "or schedule_task == \"latest_report_update\"" in source
    assert '"產業分類篩選"' in source
    assert 'st.columns([0.20, 0.80], gap="medium")' not in source
    assert "report_action_cols = st.columns([0.16, 0.16, 0.68], gap=\"small\")" in source
    assert ".report { max-width:1360px" in report_styles
    assert ".report-grid { display:block" in report_styles
    assert "<style>\n  :root" not in source
    assert "<style>{report_css}</style>" in source
    assert "REPORT_HTML_STYLE_PATH" in source
    assert "from app.ui.report_html import (" in source
    assert "def report_html(" not in DASHBOARD_CORE_SOURCE.read_text()
    assert "def report_html(" in REPORT_HTML_SOURCE.read_text()
    assert "def upgrade_audit_html(" not in DASHBOARD_CORE_SOURCE.read_text()
    assert "def upgrade_audit_html(" in MAINTENANCE_STATUS_SOURCE.read_text()
    assert "def follow_up_result_message(" not in DASHBOARD_CORE_SOURCE.read_text()
    assert "def follow_up_result_message(" in FOLLOW_UP_STATUS_SOURCE.read_text()
    assert "def api_task_post(" not in DASHBOARD_CORE_SOURCE.read_text()
    assert "def api_task_post(" in API_CLIENT_SOURCE.read_text()
    assert "def submit_background_task(" not in DASHBOARD_CORE_SOURCE.read_text()
    assert "def submit_background_task(" in BACKGROUND_TASKS_SOURCE.read_text()
    assert "def submit_data_operation_task(" in BACKGROUND_TASKS_SOURCE.read_text()
    assert "def task_queue_preflight_ready(" in BACKGROUND_TASKS_SOURCE.read_text()
    assert "def task_queue_worker_warning(" in BACKGROUND_TASKS_SOURCE.read_text()
    assert "def api_task_queue_status(" in API_CLIENT_SOURCE.read_text()
    assert "def task_queue_health_rows(" not in MAINTENANCE_STATUS_SOURCE.read_text()
    assert "def task_queue_health_alert(" not in MAINTENANCE_STATUS_SOURCE.read_text()
    assert "def task_queue_smoke_command(" not in MAINTENANCE_STATUS_SOURCE.read_text()
    assert "def task_queue_health_rows(" in TASK_QUEUE_DIAGNOSTICS_SOURCE.read_text()
    assert "def task_queue_health_alert(" in TASK_QUEUE_DIAGNOSTICS_SOURCE.read_text()
    assert "def task_queue_smoke_command(" in TASK_QUEUE_DIAGNOSTICS_SOURCE.read_text()
    assert "def external_deployment_warning_rows(" not in MAINTENANCE_STATUS_SOURCE.read_text()
    assert "def external_deployment_smoke_commands(" not in MAINTENANCE_STATUS_SOURCE.read_text()
    assert "def high_risk_filing_unlocker_rows(" in EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    assert "def external_deployment_warning_rows(" in EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    assert "def external_deployment_smoke_commands(" in EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    assert "def local_neo4j_operation_rows(" in EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    assert "def local_unlocker_operation_rows(" in EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    assert (
        "def structured_filing_api_operation_rows("
        in EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    )
    assert "def task_failure_drilldown_rows(" not in MAINTENANCE_STATUS_SOURCE.read_text()
    assert "def task_retry_options(" not in MAINTENANCE_STATUS_SOURCE.read_text()
    assert "def task_failure_drilldown_rows(" in TASK_FAILURE_DIAGNOSTICS_SOURCE.read_text()
    assert "def task_retry_options(" in TASK_FAILURE_DIAGNOSTICS_SOURCE.read_text()
    assert "def render_report_observability_panel(" in REPORT_OBSERVABILITY_PANEL_SOURCE.read_text()
    assert "def report_observability_metric_values(" in REPORT_OBSERVABILITY_PANEL_SOURCE.read_text()
    assert "def report_observability_bottleneck_rows(" in REPORT_OBSERVABILITY_PANEL_SOURCE.read_text()
    assert "report_obs_cols" not in source
    assert "def render_task_status_panel(" not in DASHBOARD_CORE_SOURCE.read_text()
    assert "def render_task_status_panel(" in TASK_STATUS_PANEL_SOURCE.read_text()
    report_center_source = Path("app/ui/report_center.py").read_text()
    assert "from app.ui.task_status_panel import render_task_status_panel" in report_center_source
    assert 'with st.expander("背景任務狀態", expanded=False):' in report_center_source
    assert "refresh_key=f\"history_run_task_status_{selected_run_id}\"" in report_center_source
    assert 'st.button("查詢背景任務狀態")' not in report_center_source
    assert 'st.json(api_get(f"/tasks/{selected_task_id}"))' not in report_center_source
    assert "def task_status_diagnostic_rows(" in TASK_STATUS_PANEL_SOURCE.read_text()
    assert "def hydrate_active_report_result(" not in DASHBOARD_CORE_SOURCE.read_text()
    assert "def hydrate_active_report_result(" in REPORT_STATE_SOURCE.read_text()
    assert "def parse_json_object(" not in DASHBOARD_CORE_SOURCE.read_text()
    assert "def parse_json_object(" in REPORT_STATE_SOURCE.read_text()
    assert "def render_follow_up_controls(" not in DASHBOARD_CORE_SOURCE.read_text()
    assert "def render_follow_up_controls(" not in REPORT_PANELS_SOURCE.read_text()
    assert "def render_follow_up_controls(" in REPORT_FOLLOW_UP_CONTROLS_SOURCE.read_text()
    assert "def render_follow_up_flash(" not in REPORT_PANELS_SOURCE.read_text()
    assert "def render_follow_up_flash(" in REPORT_FOLLOW_UP_CONTROLS_SOURCE.read_text()
    assert "def render_quality_gate(" not in DASHBOARD_CORE_SOURCE.read_text()
    assert "def render_quality_gate(" in REPORT_PANELS_SOURCE.read_text()
    assert "def markdown_table_rows(" not in REPORT_HTML_SOURCE.read_text()
    assert "def markdown_table_rows(" in REPORT_MARKDOWN_SOURCE.read_text()
    assert "def first_tranche_allocation_label(" not in REPORT_HTML_SOURCE.read_text()
    assert "def first_tranche_allocation_label(" in REPORT_MARKDOWN_SOURCE.read_text()
    assert "def candidate_audit_html(" not in REPORT_HTML_SOURCE.read_text()
    assert "def candidate_audit_html(" in REPORT_CANDIDATE_AUDIT_SOURCE.read_text()
    assert "def candidate_source_matches_display_entity(" not in REPORT_HTML_SOURCE.read_text()
    assert "def candidate_source_matches_display_entity(" in REPORT_CANDIDATE_AUDIT_SOURCE.read_text()
    assert "def metric_count_from_payload(" not in REPORT_HTML_SOURCE.read_text()
    assert "def metric_count_from_payload(" in REPORT_FORMATTERS_SOURCE.read_text()
    assert "def quality_issue_html(" not in REPORT_HTML_SOURCE.read_text()
    assert "def quality_issue_html(" in REPORT_FORMATTERS_SOURCE.read_text()
    assert "def auto_follow_up_status_html(" not in REPORT_HTML_SOURCE.read_text()
    assert "def auto_follow_up_status_html(" in REPORT_FORMATTERS_SOURCE.read_text()
    assert "def comparison_matrix_html(" not in REPORT_HTML_SOURCE.read_text()
    assert "def comparison_matrix_html(" in REPORT_SECTIONS_SOURCE.read_text()
    assert "def credibility_html(" not in REPORT_HTML_SOURCE.read_text()
    assert "def credibility_html(" in REPORT_SECTIONS_SOURCE.read_text()
    assert "def follow_up_tasks_html(" not in REPORT_HTML_SOURCE.read_text()
    assert "def follow_up_tasks_html(" in REPORT_SECTIONS_SOURCE.read_text()
    assert "grid-template-columns:minmax(240px,0.28fr)" not in source
    assert "上方選擇一份最新版報告後" in source
    assert 'api_get("/reports?limit=20")' in source
    assert "latest_by_topic(20)" not in source
    assert "選擇最新版報告" in source
    assert 'flex-wrap: wrap' in combined
    assert 'button[data-testid^="stBaseButton"]' in styles
    assert '[data-testid="stSliderThumbValue"]' in styles
    assert '[data-baseweb="tag"]' in styles
    assert 'min-height: 40px !important' in styles
    assert 'svg[role="button"]' in styles
    assert '[data-testid="stWidgetLabel"]' in styles
    assert '[data-testid="stDateInputField"]' in styles
    assert '[data-testid="stNumberInputField"]' in styles
    assert '[data-baseweb="input"]' in styles
    assert 'border-color: #64748b' in styles
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
    assert "external_deployment_warning_rows(upgrade_audit)" not in Path(
        "app/ui/system_settings_maintenance.py"
    ).read_text()
    assert 'st.expander("背景任務觀測"' not in Path("app/ui/system_settings_maintenance.py").read_text()
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
    assert "def external_deployment_warning_rows(" not in MAINTENANCE_STATUS_SOURCE.read_text()
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
    assert "st.session_state[\"last_data_task_id\"]" not in TASK_STATUS_PANEL_SOURCE.read_text()
    assert 'task_state_key="last_data_task_id"' in source
    assert 'task_state_key="last_async_task_id"' in source
    assert 'task_state_key="last_follow_up_task_id"' in source


def test_follow_up_controls_use_scoped_widget_keys() -> None:
    source = read_ui_source()

    assert 'def render_follow_up_controls(report_id: int, markdown: str, scope: str = "report")' in source
    assert 'key_suffix = f"{scope}_{report_id}"' in source
    assert 'key=f"followup_purpose_{key_suffix}"' in source
    assert 'scope="analysis_result"' in source
    assert 'scope="history_report"' in source
    assert "manual_tracking_selected" in source
    assert '"force_refresh": bool(force_refresh or manual_tracking_selected)' in source
    assert 'key=f"followup_purpose_{report_id}"' not in source


def test_candidate_source_display_filters_low_quality_forum_urls() -> None:
    helpers = load_report_helpers()

    assert helpers["candidate_source_matches_display_entity"](
        {"ticker": "1504", "name": "東元"},
        {
            "title": "1504 東元 一堆看新聞做股票不是真的分析走勢",
            "publisher": "CMoney",
            "url": "https://www.cmoney.tw/forum/stock/1504",
        },
    ) is False


def test_report_html_renders_comparison_matrix_cards() -> None:
    helpers = load_report_helpers()
    markdown = """
# AI 產業鏈 自動分析報告

## 個股比較矩陣
| 股票 | 判斷 | 最新可取得收盤價 | 追價風險標籤 | 目前情境升值分 | 目前情境降值分 | 目前估值位置 | 財務信心 | 核心提醒 |
|---|---|---|---|---:|---:|---|---|---|
| 3017 奇鋐 | 可小額分批研究 | 2026-05-22 收盤 100 | 可研究但勿追高 | 30 分 | 0 分 | 目前估值偏高 | 高 | 目前估值偏高，分批觀察 |
| 2382 廣達 | 觀察 / 等風險降低 | 2026-05-22 收盤 80 | 等風險下降 | 30 分 | 7 分 | 目前估值低於同業 | 高 | 先追蹤目前情境降值分 7 分 |

## 投資建議
| 股票 | 最新可取得收盤價 | 追價風險標籤 | 建議 | 理由 | 單檔上限 | 來源 |
|---|---|---|---|---|---:|---|
| 3017 奇鋐 | 2026-05-22 收盤 100 | 可研究但勿追高 | 可小額分批研究 | 測試 | 約 100,000 元 | 測試 |
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in html
    assert html.count('class="matrix-card') == 2
    assert "可研究 1" in html
    assert "觀察 1" in html
    assert "decision-action" in html
    assert "decision-watch" in html
    assert "valuation-high" in html
    assert "risk-high" in html
    assert "追價風險標籤" in html
    assert "可研究但勿追高" in html
    assert "等風險下降" in html
    assert "price-watch" in html
    assert "price-risk" in html
    assert "目前情境升值分" in html
    assert "目前情境降值分" in html


def test_report_html_renders_all_comparison_matrix_rows() -> None:
    helpers = load_report_helpers()
    rows = "\n".join(
        f"| {1000 + index} 測試{index} | 觀察 / 等風險降低 | 2026-05-22 收盤 {index} | 等風險下降 | 20 分 | 7 分 | 目前估值接近同業 | 高 | 測試 |"
        for index in range(1, 21)
    )
    markdown = f"""
# AI 產業鏈 自動分析報告

## 個股比較矩陣
| 股票 | 判斷 | 最新可取得收盤價 | 追價風險標籤 | 目前情境升值分 | 目前情境降值分 | 目前估值位置 | 財務信心 | 核心提醒 |
|---|---|---|---|---:|---:|---|---|---|
{rows}
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert html.count('class="matrix-card') == 20
    assert "共 20 檔" in html
    assert "觀察 20" in html
    assert "1020 測試20" in html


def test_report_html_renders_credibility_panel() -> None:
    helpers = load_report_helpers()
    markdown = """
# AI 產業鏈 自動分析報告

## 一頁摘要
| 項目 | 結果 |
|---|---|
| 本次股票範圍 | 1 檔 |

## 可信度檢查
本段先檢查報告本身的可信度。

| 檢查項目 | 狀態 | 本次證據 | 對投資判斷的影響 |
|---|---|---|---|
| 可追溯來源 | 可追溯 | 共 12 筆文本 | 沒有來源時只保留主題觀察。 |
| 來源多樣性 | 多來源 | 5 個發布者 | 避免單一觀點誤導。 |

### 個股可信度核對
| 股票 | 可信度 | 公司文本 | 歸因證據 | 最近來源日期 | 主要限制 |
|---|---|---:|---:|---|---|
| 2330 台積電 | 高 | 3 筆 / 3 來源 | 2 筆 | 2026-05-21 | 未發現重大資料缺口 |

### 可信度判讀規則
- 高可信：資料大致齊備。
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert "可信度檢查" in html
    assert "credibility-card" in html
    assert "credibility-company" in html
    assert "可追溯來源" in html
    assert "2330 台積電" in html
    assert "可信度判讀規則" in html


def test_report_html_prioritizes_zero_allocation_and_all_investment_rows() -> None:
    helpers = load_report_helpers()
    markdown = """
# AI 產業鏈 自動分析報告

## 一頁摘要
| 項目 | 結果 |
|---|---|
| 本次股票範圍 | 8 檔 |
| 可小額研究 | 0 檔 |
| 觀察/待補 | 7 檔 |
| 避開/降低曝險 | 1 檔 |

## 投資建議
| 股票 | 建議 | 理由 | 單檔上限 | 來源 |
|---|---|---|---:|---|
| 1001 A | 觀察 | 測試 | 不適用 / 0 元 | 測試 |
| 1002 B | 觀察 | 測試 | 不適用 / 0 元 | 測試 |
| 1003 C | 觀察 | 測試 | 不適用 / 0 元 | 測試 |
| 1004 D | 觀察 | 測試 | 不適用 / 0 元 | 測試 |
| 1005 E | 觀察 | 測試 | 不適用 / 0 元 | 測試 |
| 1006 F | 觀察 | 測試 | 不適用 / 0 元 | 測試 |
| 2421 建準 | 避開 / 降低曝險 | 目前情境降值分仍高 | 不適用 / 0 元 | 測試 |
| 3037 欣興 | 觀察 | 測試 | 不適用 / 0 元 | 測試 |

## 資金控管建議
### 首筆配置草案
目前無可配置標的。
"""

    html = helpers["report_html"](
        markdown,
        {
            "report_id": 1,
            "quality_gate": {
                "status": "ready",
                "action_policy": {"label": "品質可用", "max_deployable_amount": 700000},
            },
        },
    )

    assert "本次配置" in html
    assert "<strong>0 元</strong>" in html
    assert "可小額研究：0 檔" in html
    assert "避開/降低曝險：1 檔" in html
    assert "2421 建準" in html
    assert "避開 / 降低曝險" in html


def test_report_html_shows_all_first_tranche_allocation_rows() -> None:
    helpers = load_report_helpers()
    markdown = """
# 機器人 產業鏈 自動分析報告

## 一頁摘要
| 項目 | 結果 |
|---|---|
| 可小額研究 | 4 檔 |

## 資金控管建議
資金設定：總資金 1,000,000 元以內。
投資人設定：積極成長。
原則：先控風險再追報酬。

### 首筆配置草案
本輪首筆配置合計約 180,000 元；可投入上限 700,000 元。
- 2308 台達電：首筆配置約 50,000 元。
- 4583 大銀微系統：首筆配置約 40,000 元。
- 2359 所羅門：首筆配置約 40,000 元。
- 1504 東元：首筆配置約 50,000 元。
"""

    html = helpers["report_html"](markdown, {"report_id": 18, "quality_gate": {}})

    assert "本輪首筆配置合計約 180,000 元" in html
    assert "<strong>180,000 元</strong>" in html
    assert "1504 東元：首筆配置約 50,000 元" in html


def test_report_html_renders_auto_follow_up_status_and_reader_rail() -> None:
    helpers = load_report_helpers()
    html = helpers["report_html"](
        "# AI 產業鏈 自動分析報告\n",
        {
            "report_id": 8,
            "quality_gate": {"status": "caution"},
            "auto_follow_up": {
                "status": "started",
                "summary": {
                    "selected": {"total_count": 2},
                    "execution": {"stored_count": 5},
                },
                "rerun_report": {"report_id": 8},
            },
        },
    )

    assert "已自動補強並產生新版報告" in html
    assert "報告 #8" in html
    assert "decision-rail" in html
    assert 'aria-label="閱讀提示"' in html
    assert "先看本次配置與可研究檔數" in html


def test_report_html_marks_old_report_when_auto_follow_up_created_new_report() -> None:
    helpers = load_report_helpers()
    html = helpers["report_html"](
        "# AI 產業鏈 自動分析報告\n",
        {
            "report_id": 12,
            "quality_gate": {"status": "caution"},
            "auto_follow_up": {
                "status": "started",
                "source_report_id": 12,
                "source_report_topic": "AI 產業鏈",
                "source_report_tickers": ["2330"],
                "summary": {
                    "selected": {"total_count": 2},
                    "execution": {"stored_count": 5},
                },
                "rerun_report": {"report_id": 14, "request": {"topic": "AI 產業鏈"}},
            },
        },
    )

    assert "已有新版報告可查看" in html
    assert "目前畫面是報告 #12" in html
    assert "新版報告 #14" in html
    assert "避免把舊版內容誤認為已更新" in html


def test_report_html_does_not_mark_old_report_without_source_metadata() -> None:
    helpers = load_report_helpers()
    html = helpers["report_html"](
        "# 機器人 產業鏈 自動分析報告\n",
        {
            "report_id": 18,
            "topic": "機器人 產業鏈",
            "quality_gate": {"status": "ready"},
            "auto_follow_up": {
                "status": "started",
                "summary": {"selected": {"total_count": 2}},
                "rerun_report": {"report_id": 19},
            },
        },
    )

    assert "已有新版報告可查看" not in html
    assert "新版報告 #19" not in html


def test_report_html_does_not_mark_newer_report_when_current_topic_is_unknown() -> None:
    helpers = load_report_helpers()
    html = helpers["report_html"](
        "# 機器人 產業鏈 自動分析報告\n",
        {
            "report_id": 18,
            "quality_gate": {"status": "ready"},
            "auto_follow_up": {
                "status": "started",
                "source_report_id": 18,
                "summary": {"selected": {"total_count": 2}},
                "rerun_report": {"report_id": 19},
            },
        },
    )

    assert "已有新版報告可查看" not in html
    assert "新版報告 #19" not in html


def test_report_html_does_not_mark_old_report_when_source_topic_missing() -> None:
    helpers = load_report_helpers()
    html = helpers["report_html"](
        "# 機器人 產業鏈 自動分析報告\n",
        {
            "report_id": 18,
            "topic": "機器人 產業鏈",
            "quality_gate": {"status": "ready"},
            "auto_follow_up": {
                "status": "started",
                "source_report_id": 18,
                "summary": {"selected": {"total_count": 2}},
                "rerun_report": {
                    "report_id": 19,
                    "request": {"topic": "機器人 產業鏈"},
                },
            },
        },
    )

    assert "已有新版報告可查看" not in html
    assert "新版報告 #19" not in html


def test_report_html_does_not_mark_new_report_when_rerun_topic_is_unknown() -> None:
    helpers = load_report_helpers()
    html = helpers["report_html"](
        "# 機器人 產業鏈 自動分析報告\n",
        {
            "report_id": 18,
            "topic": "機器人 產業鏈",
            "quality_gate": {"status": "ready"},
            "auto_follow_up": {
                "status": "started",
                "source_report_id": 18,
                "source_report_topic": "機器人 產業鏈",
                "summary": {"selected": {"total_count": 2}},
                "rerun_report": {"report_id": 19},
            },
        },
    )

    assert "已有新版報告可查看" not in html
    assert "新版報告 #19" not in html


def test_report_html_ignores_auto_follow_up_from_another_source_report() -> None:
    helpers = load_report_helpers()
    html = helpers["report_html"](
        "# 機器人 產業鏈 自動分析報告\n",
        {
            "report_id": 18,
            "quality_gate": {"status": "ready"},
            "auto_follow_up": {
                "status": "started",
                "source_report_id": 19,
                "summary": {"selected": {"total_count": 2}},
                "rerun_report": {"report_id": 20},
            },
        },
    )

    assert "已有新版報告可查看" not in html
    assert "新版報告 #20" not in html


def test_report_html_ignores_auto_follow_up_when_rerun_topic_differs() -> None:
    helpers = load_report_helpers()
    html = helpers["report_html"](
        "# 機器人 產業鏈 自動分析報告\n",
        {
            "report_id": 18,
            "quality_gate": {"status": "ready"},
            "auto_follow_up": {
                "status": "started",
                "source_report_id": 18,
                "source_report_topic": "機器人 產業鏈",
                "summary": {"selected": {"total_count": 2}},
                "rerun_report": {
                    "report_id": 19,
                    "request": {"topic": "AI 伺服器", "tickers": ["2330"]},
                },
            },
        },
    )

    assert "已有新版報告可查看" not in html
    assert "新版報告 #19" not in html


def test_report_html_renders_auto_follow_up_unavailable_state() -> None:
    helpers = load_report_helpers()
    html = helpers["report_html"](
        "# AI 產業鏈 自動分析報告\n",
        {
            "report_id": 1,
            "quality_gate": {"status": "caution"},
            "auto_follow_up": {
                "status": "unavailable",
                "reason": "後端自動補強服務暫時無法連線。",
            },
        },
    )

    assert "自動補強暫時無法啟動" in html
    assert "後端自動補強服務暫時無法連線" in html


def test_report_html_accepts_legacy_auto_follow_up_bool_rerun_flag() -> None:
    helpers = load_report_helpers()
    html = helpers["report_html"](
        "# AI 產業鏈 自動分析報告\n",
        {
            "report_id": 1,
            "quality_gate": {"status": "caution"},
            "auto_follow_up": {
                "status": "running",
                "planned_actions": [{"action": "ingest_news"}],
                "rerun_report": True,
            },
        },
    )

    assert "自動補強執行中" in html
    assert "系統正在處理 1 項補強任務" in html


def test_report_html_renders_time_scope_panel_and_precise_metric_labels() -> None:
    helpers = load_report_helpers()
    markdown = """
# AI 產業鏈 自動分析報告

## 時間口徑說明
- 「目前」指本報告生成時間前已取得的資料，不代表未來一定維持。
- 「目前情境升值分／目前情境降值分」是排序分數，不是預期報酬率。
"""

    html = helpers["report_html"](
        markdown,
        {
            "report_id": 1,
            "request": {"lookback_days": 21},
            "quality_gate": {
                "metrics": {
                    "source_timestamp_coverage": 1,
                    "source_recent_coverage": 0.8,
                    "leading_signal_coverage": 0.5,
                }
            },
        },
    )

    assert "<h2>時間口徑</h2>" in html
    assert "近 21 天來源" in html
    assert "來源有日期" in html
    assert "近況訊號覆蓋" in html
    assert "不是預期報酬率" in html


def test_report_html_renders_investment_thesis_cards() -> None:
    helpers = load_report_helpers()
    markdown = """
# AI 產業鏈 自動分析報告

## 投資理由地圖
本段把每檔股票拆成「為什麼值得研究」與「為什麼可能不成立」。這是研究假設，不是報酬保證或買賣指令。

### 2330 台積電
- 目前判斷：可小額分批研究；資料等級：完整。
- 成長假設：有 3 筆公司相關文本，正向關鍵證據 2 項。
- 主要風險：風險證據未達 >5% 情境門檻。
- 具體投資理由：目前情境升值分 22 高於 10 的研究門檻。
- 需要再確認：下一期月營收、法說或官方文件是否延續目前假設
- 代表性來源：2026-05-20 測試新聞《台積電 AI 需求成長》
- 風險來源：2026-05-18 測試新聞《台積電 產能吃緊》
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert "投資理由地圖" in html
    assert 'class="thesis-card"' in html
    assert "值得研究的理由" in html
    assert "目前情境升值分 22" in html
    assert "不是未來報酬率、目標價或買賣指令" in html
    assert "風險來源：2026-05-18 測試新聞" in html


def test_report_html_renders_early_potential_radar_cards() -> None:
    helpers = load_report_helpers()
    markdown = """
# AI 產業鏈早期潛力股 自動分析報告

## 早期潛力雷達
本段專門找「截至目前報導較少、但近況訊號轉強」的研究線索；報導較少不是利多。

| 股票 | 早期線索分 | 截至目前報導熱度 | 目前情境升值分 | 目前情境降值分 | 為什麼可能還早 | 代表來源 |
|---|---:|---|---:|---:|---|---|
| 2356 英業達 | 28 | 報導較少 | 28 分 | 9 分 | 公司文本 2 筆 / 2 來源；月營收年增 36.5% | 2026-05-06 測試新聞《英業達 AI 伺服器展望》 |
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert "早期潛力雷達" in html
    assert 'class="radar-card attention-low"' in html
    assert "截至目前報導較少、但近況訊號轉強" in html
    assert "不是買賣指令" in html
    assert "不是自選股狀態" in html
    assert "英業達" in html


def test_report_html_does_not_render_empty_early_potential_card() -> None:
    helpers = load_report_helpers()
    markdown = """
# AI 產業鏈早期潛力股 自動分析報告

## 早期潛力雷達
本段專門找「截至目前報導較少、但近況訊號轉強」的研究線索。

目前沒有同時符合「報導較少」與「近況訊號轉強」的標的。
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert "早期潛力雷達" not in html
    assert 'class="radar-card' not in html
    assert "目前無足夠數據判斷 | 0" not in html


def test_report_html_renders_full_next_step_groups() -> None:
    helpers = load_report_helpers()
    watch_rows = "\n".join(
        f"- {1000 + index} 測試{index}：觀察 / 等風險降低；下一步補查 等待新證據。"
        for index in range(1, 20)
    )
    markdown = f"""
# AI 產業鏈 自動分析報告

## 下一步行動
1. 先處理資料缺口。
2. 只把資料完整且通過門檻的股票放進研究清單。

### 可立即研究
- 目前沒有同時通過資料完整度與風險門檻的標的。

### 待補資料 / 觀察
{watch_rows}

### 先避開
- 8046 南電：目前情境降值分 18 分，暫不列入買進研究。
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert "處理原則（2 項）" in html
    assert "待補資料 / 觀察（19 項）" in html
    assert "1019 測試19" in html
    assert "8046 南電" in html


def test_report_html_renders_quality_warnings() -> None:
    helpers = load_report_helpers()
    markdown = "# AI 產業鏈 自動分析報告\n"

    html = helpers["report_html"](
        markdown,
        {
            "report_id": 1,
            "quality_gate": {
                "status": "caution",
                "warnings": ["候選公司證據覆蓋率低於 60%，已由二次篩選收斂正式股票"],
                "blockers": [],
                "metrics": {
                    "formal_confidence_min": 76,
                    "formal_confidence_avg": 82.5,
                    "discovery_plan_status": "ready",
                    "discovery_plan_score": 100,
                },
                "remediation_actions": ["對弱證據候選補抓公司新聞、法說會與供應鏈資料後再做二次篩選。"],
                "action_policy": {"label": "需人工覆核"},
            },
        },
    )

    assert "品質警示" in html
    assert "警示：" in html
    assert "候選公司證據覆蓋率低於 60%" in html
    assert "建議補強" in html
    assert "弱證據候選補抓" in html
    assert "quality-issues" in html
    assert "quality-warnings" in html
    assert "最低信心" in html
    assert ">高 76<" in html
    assert "拆解任務品質" in html
    assert ">完整（100 分）<" in html


def test_report_html_renders_observations_without_warning_title() -> None:
    helpers = load_report_helpers()
    markdown = "# AI 產業鏈 自動分析報告\n"

    html = helpers["report_html"](
        markdown,
        {
            "report_id": 1,
            "quality_gate": {
                "status": "ready",
                "warnings": [],
                "blockers": [],
                "observations": ["LLM 補充分析已完成，且仍受來源與白名單驗證約束"],
            },
        },
    )

    assert "品質觀察" in html
    assert "品質警示" not in html
    assert "quality-observations" in html
    assert "panel quality-issues quality-warnings" not in html
    assert "觀察：" in html
    assert "模型補充分析已完成" in html


def test_report_html_labels_low_candidate_confidence() -> None:
    helpers = load_report_helpers()

    html = helpers["report_html"](
        "# AI 產業鏈 自動分析報告\n",
        {
            "report_id": 1,
            "quality_gate": {
                "status": "insufficient",
                "metrics": {"formal_confidence_min": 42},
                "blockers": ["正式分析股票含低信心證據公司"],
                "action_policy": {"label": "僅供研究，不允許投入資金"},
            },
        },
    )

    assert "最低信心" in html
    assert ">低 42<" in html
    assert "quality-blockers" in html


def test_maintenance_service_metrics_show_promotion_threshold() -> None:
    helpers = load_report_helpers()

    metrics = helpers["maintenance_service_metrics"](
        {"integrity": {"ok": True}},
        {
            "redis": {"ok": True},
            "task_queue": {"ready": True},
            "gemini": {"key_count": 5},
            "finmind": {"mode": "public_or_limited"},
            "candidate_confidence": {"high_threshold": 75},
        },
    )

    assert metrics["資料庫"] == "正常"
    assert metrics["Redis"] == "正常"
    assert metrics["背景任務"] == "可送出"
    assert metrics["AI Key"] == 5
    assert metrics["市場資料"] == "可用"
    assert metrics["升格門檻"] == "高 75"


def test_maintenance_service_metrics_show_worker_queue_warning_label() -> None:
    helpers = load_report_helpers()

    metrics = helpers["maintenance_service_metrics"](
        {"integrity": {"ok": True}},
        {
            "redis": {"ok": True},
            "task_queue": {"ready": True, "worker_ping_checked": True, "worker_online": False},
            "gemini": {"key_count": 5},
            "finmind": {"mode": "public_or_limited"},
            "candidate_confidence": {"high_threshold": 75},
        },
    )

    assert metrics["背景任務"] == "可排隊"


def test_task_queue_health_rows_show_worker_nodes_and_smoke_command() -> None:
    helpers = load_report_helpers()
    snapshot = {
        "task_queue": {
            "ready": True,
            "broker_configured": True,
            "broker_ok": True,
            "backend_ok": True,
            "broker_url": "redis://localhost:6379/0",
            "backend_url": "redis://localhost:6379/0",
            "submission_contract_ready": True,
            "worker_ping_checked": True,
            "worker_online": True,
            "worker_count": 1,
            "worker_nodes": ["celery@test.local"],
            "smoke_commands": [".venv/bin/python -m celery inspect ping"],
        }
    }

    rows = helpers["task_queue_health_rows"](snapshot)
    alert = helpers["task_queue_health_alert"](snapshot)

    assert rows[0]["項目"] == "Queue 提交"
    assert rows[0]["狀態"] == "可送出"
    assert rows[4]["項目"] == "Celery Worker"
    assert rows[4]["狀態"] == "在線"
    assert "celery@test.local" in rows[4]["說明"]
    assert alert == {
        "severity": "success",
        "message": "Queue 與 Celery worker 可用；目前 1 個 worker 節點回應。",
    }
    assert helpers["task_queue_smoke_command"](snapshot) == ".venv/bin/python -m celery inspect ping"


def test_task_queue_health_alert_warns_when_worker_is_offline_but_queue_can_submit() -> None:
    helpers = load_report_helpers()
    snapshot = {
        "task_queue": {
            "ready": True,
            "broker_configured": True,
            "broker_ok": True,
            "backend_ok": True,
            "submission_contract_ready": True,
            "worker_ping_checked": True,
            "worker_online": False,
            "worker_count": 0,
            "worker_nodes": [],
            "worker_ping_timeout_seconds": 1.0,
        }
    }

    rows = helpers["task_queue_health_rows"](snapshot)
    alert = helpers["task_queue_health_alert"](snapshot)

    assert rows[0]["狀態"] == "可排隊"
    assert "worker 未回應" in rows[0]["說明"]
    assert rows[4]["狀態"] == "未回應"
    assert "timeout 1.0s" in rows[4]["說明"]
    assert alert["severity"] == "warning"
    assert "Celery worker 未回應" in alert["message"]


def test_task_queue_health_alert_blocks_unready_queue() -> None:
    helpers = load_report_helpers()
    snapshot = {
        "task_queue": {
            "ready": False,
            "broker_configured": True,
            "broker_ok": False,
            "backend_ok": False,
            "submission_contract_ready": True,
            "redis_error": "connection refused",
            "broker_url": "redis://localhost:6379/0",
            "backend_url": "redis://localhost:6379/0",
        }
    }

    rows = helpers["task_queue_health_rows"](snapshot)
    alert = helpers["task_queue_health_alert"](snapshot)

    assert rows[0]["狀態"] == "檢查"
    assert "Redis broker 未連線" in rows[0]["說明"]
    assert "connection refused" in rows[1]["說明"]
    assert alert["severity"] == "error"
    assert "背景任務 queue 尚不可送出" in alert["message"]


def test_task_failure_drilldown_rows_and_retry_options_are_actionable() -> None:
    helpers = load_report_helpers()
    task_summary = {
        "recent_failures": [
            {
                "id": 22,
                "operation": "report_generation",
                "status": "failed",
                "task_id": "task-failed",
                "retryable": True,
                "retry_kind": "report_generation",
                "error_category": "quota",
                "error_severity": "warning",
                "error_summary": "模型/API 額度或速率限制",
                "next_steps": [
                    "查看 AI 額度與模型路由或資料源額度。",
                    "等待額度重置，或改用已設定的 fallback 模型/資料源後再重試。",
                ],
                "retry_endpoint": "POST /tasks/task-failed/retry",
                "next_action": "可從維護頁重試，或呼叫 POST /tasks/task-failed/retry",
                "error": "quota exhausted",
                "started_at": "2026-06-07T10:00:00",
            },
            {
                "id": 23,
                "operation": "after_close_report_update",
                "status": "failed",
                "task_id": "task-after-close",
                "retryable": False,
                "retry_kind": None,
                "next_action": "payload 不支援自動重試；請依錯誤內容手動重新送出。",
                "error": "missing target",
                "started_at": "2026-06-07T11:00:00",
            },
        ]
    }

    rows = helpers["task_failure_drilldown_rows"](task_summary)
    options = helpers["task_retry_options"](task_summary)

    assert rows[0]["run_id"] == 22
    assert rows[0]["category"] == "quota"
    assert rows[0]["severity"] == "warning"
    assert rows[0]["summary"] == "模型/API 額度或速率限制"
    assert rows[0]["next_steps"] == "查看 AI 額度與模型路由或資料源額度。；等待額度重置，或改用已設定的 fallback 模型/資料源後再重試。"
    assert rows[0]["retry"] == "可重試"
    assert rows[0]["retry_kind"] == "report_generation"
    assert rows[0]["next_action"] == "可從維護頁重試，或呼叫 POST /tasks/task-failed/retry"
    assert rows[1]["retry"] == "需人工"
    assert rows[1]["retry_kind"] == "-"
    assert rows[1]["next_steps"] == "-"
    assert options == [
        {
            "task_id": "task-failed",
            "label": "report_generation｜run #22｜task-failed",
            "operation": "report_generation",
            "run_id": 22,
            "retry_endpoint": "POST /tasks/task-failed/retry",
        }
    ]


def test_external_deployment_warning_rows_include_optional_and_smoke_commands() -> None:
    helpers = load_report_helpers()
    audit = {
        "failures": [
            {
                "area": "ai_rag",
                "capability": "neo4j_import",
                "label": "外部 Neo4j 匯入連線",
                "status": "degraded",
                "severity": "fail",
                "external_integration": True,
                "detail": "connection_failed:neo4j",
                "evidence": {
                    "payload_dry_run_cli": ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run --tickers 2330 --output graph_payload.json",
                    "smoke_cli": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json",
                    "import_smoke_cli": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --import-first --tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json",
                },
                "remediation": "啟動 Neo4j 並設定帳密。",
            }
        ],
        "warnings": [
            {
                "area": "data_business_logic",
                "capability": "company_filing_browser_or_proxy_fallback",
                "label": "公司文件 Proxy / Browser render / Playwright 後援",
                "status": "not_configured",
                "severity": "warn",
                "external_integration": True,
                "detail": "browser_or_proxy_fallback_configured=false",
                "evidence": {
                    "browser_render_runtime": {
                        "fallback_reason": "missing_browser_render_url",
                        "smoke_cli": ".venv/bin/python scripts/company_filing_render_smoke.py --url https://example.com/ --json",
                    },
                    "playwright_render_runtime": {
                        "smoke_cli": ".venv/bin/python scripts/company_filing_render_smoke.py --url https://mops.twse.com.tw/ --json",
                    },
                },
                "remediation": "設定 Browserless 或 Playwright。",
            }
        ],
        "optional_warnings": [
            {
                "area": "ai_rag",
                "capability": "graphrag_live_cypher_query",
                "label": "GraphRAG guarded live Cypher query",
                "status": "degraded",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "detail": "Neo4j is required for live guarded Cypher execution.",
                "evidence": {
                    "endpoint": "GET /supply-chain/graph/cypher-query",
                    "payload_dry_run_cli": ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run --tickers 2330 --output graph_payload.json",
                    "smoke_cli": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json",
                    "import_smoke_cli": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --import-first --tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json",
                },
                "remediation": "啟動 Neo4j 後驗證 live read-only query。",
            },
            {
                "area": "data_business_logic",
                "capability": "company_filing_structured_api_fallback",
                "label": "公司文件結構化 API 備援",
                "status": "not_configured",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "detail": "configured=false",
                "evidence": {
                    "runtime": {
                        "fallback_reason": "missing_structured_api_provider_or_url",
                        "smoke_cli": ".venv/bin/python scripts/structured_company_filing_smoke.py --ticker 2330 --company-name 台積電 --document-type investor_presentation --json",
                    }
                },
                "remediation": "設定 TEJ 或專業資料 API。",
            }
        ],
        "all_warnings": [
            {
                "area": "data_business_logic",
                "capability": "company_filing_structured_api_fallback",
                "external_integration": True,
                "severity": "warn",
            }
        ],
    }

    rows = helpers["external_deployment_warning_rows"](audit)
    commands = helpers["external_deployment_smoke_commands"](audit)

    assert [row["能力"] for row in rows] == [
        "外部 Neo4j 匯入連線",
        "公司文件 Proxy / Browser render / Playwright 後援",
        "GraphRAG guarded live Cypher query",
        "公司文件結構化 API 備援",
    ]
    assert rows[0]["警示層級"] == "需處理"
    assert rows[1]["警示層級"] == "注意"
    assert rows[2]["警示層級"] == "外部選配"
    assert "neo4j_graphrag_smoke.py" in rows[2]["診斷指令"]
    assert rows[3]["警示層級"] == "外部選配"
    assert "missing_browser_render_url" in rows[1]["說明"]
    assert "structured_company_filing_smoke.py" in rows[3]["診斷指令"]
    assert len(rows) == 4
    assert commands == [
        ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run --tickers 2330 --output graph_payload.json",
        ".venv/bin/python scripts/neo4j_graphrag_smoke.py --tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json",
        ".venv/bin/python scripts/neo4j_graphrag_smoke.py --import-first --tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json",
        ".venv/bin/python scripts/company_filing_render_smoke.py --url https://example.com/ --json",
        ".venv/bin/python scripts/company_filing_render_smoke.py --url https://mops.twse.com.tw/ --json",
        ".venv/bin/python scripts/structured_company_filing_smoke.py --ticker 2330 --company-name 台積電 --document-type investor_presentation --json",
    ]


def test_high_risk_filing_unlocker_rows_surface_policy_details() -> None:
    helpers = load_report_helpers()
    provider_env = "COMPANY_FILING_BROWSER_RENDER_PROVIDER" + "=flaresolverr"
    render_url_env = "COMPANY_FILING_BROWSER_RENDER_URL" + "=http://127.0.0.1:8191/v1"
    compose_render_url_env = "COMPANY_FILING_BROWSER_RENDER_URL" + "=http://flaresolverr:8191/v1"
    audit = {
        "optional_warnings": [
            {
                "area": "data_business_logic",
                "capability": "company_filing_high_risk_unlocker",
                "label": "MOPS/TWSE/TPEx 高風險文件 unlocker",
                "status": "not_configured",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "detail": "needs unlocker",
                "evidence": {
                    "configured_provider": "browserless",
                    "provider_tier": "browser_render",
                    "provider_capability": {
                        "provider": "browserless",
                        "tier": "browser_render",
                        "captcha_unlocker": False,
                    },
                    "browser_only_render_ready": True,
                    "unlocker_provider_ready": False,
                    "captcha_challenge_ready": False,
                    "fallback_reason": "browser_or_playwright_render_lacks_captcha_unlocker",
                    "domains": ["mops.twse.com.tw", "doc.twse.com.tw"],
                    "recommended_env": [provider_env, render_url_env],
                    "compose_recommended_env": [provider_env, compose_render_url_env],
                    "smoke_cli": (
                        ".venv/bin/python scripts/company_filing_render_smoke.py "
                        "--url https://mops.twse.com.tw/ --json"
                    ),
                },
                "remediation": "設定 FlareSolverr 或 managed unlocker。",
            }
        ]
    }

    rows = helpers["high_risk_filing_unlocker_rows"](audit)

    assert [row["項目"] for row in rows] == [
        "Provider",
        "高風險防護",
        "高風險網域",
        "建議 env",
        "MOPS smoke",
    ]
    assert rows[0]["狀態"] == "待配置"
    assert rows[0]["目前"] == "browserless"
    assert "captcha_unlocker=否" in rows[0]["細節"]
    assert "browser render fallback" in rows[1]["目前"]
    assert rows[1]["細節"] == "browser_or_playwright_render_lacks_captcha_unlocker"
    assert "mops.twse.com.tw" in rows[2]["目前"]
    assert provider_env in rows[3]["目前"]
    assert "# compose" in rows[3]["目前"]
    assert compose_render_url_env in rows[3]["目前"]
    assert "service DNS" in rows[3]["細節"]
    assert "https://mops.twse.com.tw/" in rows[4]["目前"]


def test_local_unlocker_operation_rows_include_actionable_commands() -> None:
    helpers = load_report_helpers()
    audit = {
        "optional_warnings": [
            {
                "area": "data_business_logic",
                "capability": "company_filing_high_risk_unlocker",
                "label": "MOPS/TWSE/TPEx 高風險文件 unlocker",
                "status": "not_configured",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "detail": "needs unlocker",
                "evidence": {
                    "configured_provider": "browserless",
                    "provider_tier": "browser_render",
                    "browser_only_render_ready": True,
                    "unlocker_provider_ready": False,
                    "captcha_challenge_ready": False,
                    "fallback_reason": "browser_or_playwright_render_lacks_captcha_unlocker",
                    "smoke_cli": (
                        ".venv/bin/python scripts/company_filing_render_smoke.py "
                        "--url https://mops.twse.com.tw/ --json"
                    ),
                },
                "remediation": "設定 FlareSolverr 或 managed unlocker。",
            }
        ]
    }

    rows = helpers["local_unlocker_operation_rows"](audit)

    assert [row["項目"] for row in rows] == [
        "一鍵啟動",
        "本機稽核",
        "Fallback 判斷",
        "容器診斷",
        "MOPS smoke",
    ]
    assert rows[0]["狀態"] == "建議升級"
    assert "scripts/start_system.py --start-dependencies --prefer-unlocker" in rows[0]["指令"]
    assert "--wait-local-flaresolverr 20" in rows[1]["指令"]
    assert "Browserless/Playwright" in rows[2]["說明"]
    assert rows[2]["指令"] == "-"
    assert "docker compose logs flaresolverr" in rows[3]["指令"]
    assert "https://mops.twse.com.tw/" in rows[4]["指令"]


def test_local_neo4j_operation_rows_include_actionable_commands() -> None:
    helpers = load_report_helpers()
    audit = {
        "optional_warnings": [
            {
                "area": "ai_rag",
                "capability": "neo4j_import",
                "label": "外部 Neo4j 匯入連線",
                "status": "degraded",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "detail": "missing Neo4j",
                "evidence": {
                    "ready": False,
                    "connection_ok": False,
                    "fallback_reason": "missing_settings:neo4j_uri",
                    "payload_export_ready": True,
                    "payload_node_count": 27,
                    "payload_structural_edge_count": 135,
                    "payload_peer_edge_count": 36,
                    "payload_statement_count": 5,
                    "payload_dry_run_cli": ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run",
                    "smoke_cli": (
                        ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
                        "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json"
                    ),
                    "import_smoke_cli": (
                        ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
                        "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 --import-first --json"
                    ),
                    "local_docker_defaults": {
                        "cli_start": ".venv/bin/python scripts/start_system.py --start-dependencies",
                    },
                },
            },
            {
                "area": "ai_rag",
                "capability": "graphrag_live_cypher_query",
                "label": "GraphRAG guarded live Cypher query",
                "status": "degraded",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "detail": "Neo4j not configured",
                "evidence": {
                    "neo4j_ready": False,
                    "local_dry_run_status": "executed_dry_run",
                    "plan_validation": {"valid": True, "read_only": True},
                    "payload_dry_run_cli": ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run",
                    "smoke_cli": (
                        ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
                        "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json"
                    ),
                },
            },
        ]
    }

    rows = helpers["local_neo4j_operation_rows"](audit)

    assert [row["項目"] for row in rows] == [
        "一鍵啟動",
        "本機稽核",
        "Payload dry-run",
        "Live query smoke",
        "Import-first smoke",
        "容器診斷",
    ]
    assert rows[0]["狀態"] == "待啟動"
    assert "scripts/start_system.py --start-dependencies" in rows[0]["指令"]
    assert "--local-neo4j-defaults --wait-local-neo4j 20" in rows[1]["指令"]
    assert "scripts.import_supply_chain_graph_neo4j --dry-run" in rows[2]["指令"]
    assert "nodes=27" in rows[2]["說明"]
    assert "neo4j_graphrag_smoke.py" in rows[3]["指令"]
    assert "--import-first" in rows[4]["指令"]
    assert "docker compose logs neo4j" in rows[5]["指令"]
    assert "missing_settings:neo4j_uri" in rows[5]["說明"]


def test_structured_filing_api_operation_rows_include_actionable_commands() -> None:
    helpers = load_report_helpers()
    audit = {
        "optional_warnings": [
            {
                "area": "data_business_logic",
                "capability": "company_filing_structured_api_fallback",
                "label": "公司文件結構化 API 備援",
                "status": "not_configured",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "detail": "configured=false",
                "evidence": {
                    "configured": False,
                    "provider": None,
                    "provider_profile_key": "custom",
                    "supported_provider_examples": [
                        "tej",
                        "scrapingbee_dataset",
                        "brightdata_dataset",
                        "custom",
                    ],
                    "required_document_fields": [
                        "title/name/headline/doc_title",
                        "text/content/body/abstract/summary",
                        "ticker_or_company_mention",
                        "document_type_match",
                    ],
                    "response_row_aliases": ["documents", "data", "results"],
                    "runtime": {
                        "configured": False,
                        "fallback_reason": "missing_structured_api_provider_or_url",
                        "provider": None,
                        "provider_profile_key": "custom",
                        "provider_profile": {
                            "provider": "custom",
                            "profile_key": "custom",
                        },
                        "request_contract": {
                            "method": "GET",
                            "auth_mode": "bearer_optional",
                            "document_type_param": "document_types",
                            "query_param_keys": [
                                "ticker",
                                "company_name",
                                "limit",
                                "document_types",
                            ],
                            "response_rows": ["documents", "data", "results"],
                        },
                        "required_document_fields": [
                            "title/name/headline/doc_title",
                            "text/content/body/abstract/summary",
                            "ticker_or_company_mention",
                            "document_type_match",
                        ],
                        "response_row_aliases": ["documents", "data", "results"],
                        "sample_contract_cli": (
                            ".venv/bin/python scripts/structured_company_filing_smoke.py "
                            "--sample-json examples/structured_company_filing_sample.json "
                            "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
                        ),
                        "sample_contract": {
                            "status": "ready",
                            "ready": True,
                            "mode": "sample_json_contract",
                            "raw_row_count": 1,
                            "document_count": 1,
                            "error_count": 0,
                        },
                        "smoke_cli": (
                            ".venv/bin/python scripts/structured_company_filing_smoke.py "
                            "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
                        ),
                    },
                },
                "remediation": "設定 TEJ 或專業資料 API。",
            }
        ]
    }

    rows = helpers["structured_filing_api_operation_rows"](audit)

    assert [row["項目"] for row in rows] == [
        "Provider profile",
        "Sample contract",
        "Live smoke",
        "Request contract",
        "Required fields",
        "Fallback 判斷",
    ]
    assert rows[0]["狀態"] == "待設定"
    assert "COMPANY_FILING_STRUCTURED_API_PROVIDER=custom" in rows[0]["指令"]
    assert "supported=tej、scrapingbee_dataset、brightdata_dataset、custom" in rows[0]["說明"]
    assert rows[1]["狀態"] == "ready"
    assert "--sample-json examples/structured_company_filing_sample.json" in rows[1]["指令"]
    assert "raw_rows=1；documents=1；errors=0" in rows[1]["說明"]
    assert rows[2]["狀態"] == "待設定"
    assert "structured_company_filing_smoke.py" in rows[2]["指令"]
    assert rows[3]["狀態"] == "GET"
    assert "auth=bearer_optional" in rows[3]["說明"]
    assert "ticker,company_name,limit,document_types" in rows[3]["說明"]
    assert "title/name/headline/doc_title" in rows[4]["說明"]
    assert rows[5]["狀態"] == "not_configured"
    assert "missing_structured_api_provider_or_url" in rows[5]["說明"]


def test_upgrade_audit_html_is_readable_and_not_color_only() -> None:
    helpers = load_report_helpers()

    audit = {
        "overall_status": "ready",
        "strict_external": False,
        "summary": {
            "total_checks": 23,
            "ready": 18,
            "warnings": 0,
            "optional_warnings": 5,
            "total_warnings": 5,
            "failures": 0,
            "implementation_status": "ready",
            "deployment_status": "caution",
        },
        "implementation": {"status": "ready", "ready": 18, "total_checks": 18, "warnings": 0, "failures": 0},
        "deployment": {"status": "caution", "ready": 0, "total_checks": 5, "warnings": 5, "failures": 0},
        "areas": {
            "ai_rag": {"ready": 9, "warnings": 2, "failures": 0, "checks": 11},
            "architecture": {"ready": 4, "warnings": 0, "failures": 0, "checks": 4},
            "data_business_logic": {"ready": 5, "warnings": 3, "failures": 0, "checks": 8},
        },
        "checks": [
            {
                "area": "ai_rag",
                "capability": "neo4j_import",
                "label": "外部 Neo4j 匯入連線",
                "severity": "warn",
                "status": "degraded",
                "detail": "missing_settings:neo4j_uri",
                "remediation": "設定 NEO4J_URI。",
            },
            {
                "area": "ai_rag",
                "capability": "visual_rag",
                "label": "Visual RAG / VLM 財報解析",
                "severity": "warn",
                "status": "not_configured",
                "detail": "visual_rag_disabled",
                "remediation": "安裝 .[visual] 並設定 vision LLM。",
            },
            {
                "area": "data_business_logic",
                "capability": "company_filing_pdf_table_parser_runtime",
                "label": "PDF 表格 parser runtime",
                "severity": "warn",
                "status": "not_configured",
                "detail": "missing_table_pdf_parser_dependency:pdfplumber_or_unstructured",
                "remediation": "安裝 .[pdf]。",
            },
            {
                "area": "data_business_logic",
                "capability": "company_filing_browser_or_proxy_fallback",
                "label": "公司文件 Proxy / Browser render / Playwright 後援",
                "severity": "warn",
                "status": "not_configured",
                "detail": "browser_or_proxy_fallback_configured=false",
                "remediation": "設定 COMPANY_FILING_PROXY_URLS。",
            },
            {
                "area": "data_business_logic",
                "capability": "company_filing_structured_api_fallback",
                "label": "公司文件結構化 API 備援",
                "severity": "warn",
                "status": "not_configured",
                "detail": "configured=false",
                "remediation": "設定 TEJ 或專業資料 API。",
            }
        ],
    }

    html = helpers["upgrade_audit_html"](audit)
    rows = helpers["upgrade_audit_rows"](audit)

    assert "升級稽核" in html
    assert "核心升級" in html
    assert "外部整合" in html
    assert "注意" in html
    assert "通過" in html
    assert "一般檢查" in html
    assert "18/23" in html
    assert "核心 18/18 通過，外部 0/5 通過" in html
    assert "外部選配 5 項" in html
    assert "AI / RAG" in html
    assert rows[0] == {
        "面向": "AI / RAG",
        "能力": "外部 Neo4j 匯入連線",
        "結果": "注意",
        "目前狀態": "degraded",
        "說明": "missing_settings:neo4j_uri",
        "處理方向": "設定 NEO4J_URI。",
    }
    assert rows[1]["能力"] == "Visual RAG / VLM 財報解析"
    assert rows[1]["處理方向"] == "安裝 .[visual] 並設定 vision LLM。"
    assert rows[2]["能力"] == "PDF 表格 parser runtime"
    assert rows[2]["處理方向"] == "安裝 .[pdf]。"
    assert rows[3]["能力"] == "公司文件 Proxy / Browser render / Playwright 後援"
    assert rows[3]["處理方向"] == "設定 COMPANY_FILING_PROXY_URLS。"
    assert rows[4]["能力"] == "公司文件結構化 API 備援"


def test_report_html_renders_follow_up_tasks() -> None:
    helpers = load_report_helpers()
    markdown = """
# AI 產業鏈 自動分析報告

## 自動補強任務
| 任務 | 股票 | 優先級 | 頻率 | 觸發原因 |
|---|---|---|---|---|
| 刷新股價/量能 | 2330 | high | weekly | 領先訊號偏空，需重新檢查 |
| 刷新月營收 | 2382 | high | monthly | 補齊月營收與公司文本 |
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert "系統會自動補強" in html
    assert "刷新股價/量能" in html
    assert "刷新月營收" in html
    assert "task-card" in html


def test_report_html_renders_candidate_audit_from_markdown() -> None:
    helpers = load_report_helpers()
    markdown = """
# AI 產業鏈 自動分析報告

## 候選公司審計
| 項目 | 數量 |
|---|---:|
| AI 初始候選 | 3 |
| 正式分析 | 1 |

| 股票 | 產業位置 | 狀態 | 證據 | 排除 / 升格原因 | 下一步 |
|---|---|---|---:|---|---|
| 2382 廣達 | 系統組裝 | 正式分析 | 2 篇 / 2 來源 | 通過正式分析門檻 | 納入正式分析 |
| 3324 雙鴻 | 散熱模組 | 弱證據觀察 | 1 篇 / 1 來源 | 弱證據：來源不足 | 補抓公司新聞 |
| 2308 台達電 | 電源與散熱 | 待補證據 | 0 篇 / 0 來源 | 缺少公司主題證據 | 重新補抓 |
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert "候選公司審計" in html
    assert "正式分析 1" in html
    assert "弱證據 1" in html
    assert "待補證據 1" in html
    assert "3324 雙鴻" in html
    assert "audit-card audit-weak" in html


def test_report_html_renders_candidate_audit_from_result_payload() -> None:
    helpers = load_report_helpers()

    html = helpers["report_html"](
        "# AI 產業鏈 自動分析報告",
        {
            "report_id": 1,
            "quality_gate": {},
            "candidate_whitelist": [
                {
                    "ticker": "2382",
                    "name": "廣達",
                    "segment": "系統組裝",
                    "status": "evidence_supported",
                    "evidence_count": 2,
                    "evidence_source_count": 2,
                    "validation_reason": "通過正式分析門檻",
                    "next_action": "納入正式分析",
                    "evidence_sources": [
                        {
                            "title": "廣達 AI 伺服器訂單",
                            "publisher": "測試新聞",
                            "published_at": "2026-05-24",
                        }
                    ],
                    "evidence_confidence_score": 92,
                    "evidence_confidence_label": "高",
                },
                {
                    "ticker": "3324",
                    "name": "雙鴻",
                    "segment": "散熱模組",
                    "status": "weak_evidence",
                    "evidence_count": 1,
                    "evidence_source_count": 1,
                    "validation_reason": "弱證據：來源不足",
                    "next_action": "補抓公司新聞",
                },
                {
                    "ticker": "3059",
                    "name": "華晶科",
                    "segment": "3D 感測相機",
                    "status": "evidence_limited",
                    "evidence_count": 4,
                    "evidence_source_count": 2,
                    "validation_reason": "已自動補查，仍未達正式分析門檻。",
                    "next_action": "後續只有在新增公司公告時才重新評估。",
                    "latest_evidence_date": "2025-08-08",
                    "evidence_age_days": 296,
                    "evidence_stale": True,
                    "evidence_sources": [
                        {
                            "title": "華晶科 股東會年報",
                            "publisher": "公開資訊觀測站 MOPS",
                            "published_at": "2025-08-08",
                            "url": "https://example.com/3059",
                        }
                    ],
                    "evidence_confidence_score": 63,
                    "evidence_confidence_label": "中",
                },
            ],
        },
    )

    assert "候選公司審計" in html
    assert "候選清單</span><strong>3</strong>" in html
    assert "候選卡片 3" in html
    assert "2382 廣達" in html
    assert "3324 雙鴻" in html
    assert "3059 華晶科" in html
    assert "廣達 AI 伺服器訂單" in html
    assert "測試新聞" in html
    assert "高 92" in html
    assert "超過 180 天新鮮度門檻" in html


def test_report_html_uses_quality_promoted_count_when_report_payload_has_no_promoted_list() -> None:
    helpers = load_report_helpers()

    html = helpers["report_html"](
        "# AI 產業鏈早期潛力股 自動分析報告",
        {
            "report_id": 1,
            "quality_gate": {
                "status": "ready",
                "metrics": {"promoted_count": 10},
            },
            "candidate_whitelist": [],
        },
    )

    assert "正式分析股票</span><strong>10</strong>" in html
    assert "正式分析只代表資料通過門檻，不等於買進名單" in html


def test_candidate_revalidation_summary_counts_statuses() -> None:
    helpers = load_report_helpers()

    summary = helpers["candidate_revalidation_summary"](
        {
            "rerun_report": {
                "candidate_revalidation": {
                    "changed": True,
                    "promoted_tickers": ["2382", "3324"],
                    "document_query_count": 9,
                    "document_count": 24,
                    "newly_promoted": ["3324"],
                    "no_longer_promoted": [],
                    "status_changes": [
                        {
                            "ticker": "3324",
                            "previous_status": "weak_evidence",
                            "current_status": "evidence_supported",
                        }
                    ],
                    "candidate_whitelist": [
                        {
                            "ticker": "2382",
                            "name": "廣達",
                            "segment": "系統組裝",
                            "status": "evidence_supported",
                            "evidence_count": 2,
                            "evidence_source_count": 2,
                        },
                        {
                            "ticker": "3324",
                            "name": "雙鴻",
                            "segment": "散熱模組",
                            "status": "evidence_supported",
                            "evidence_count": 3,
                            "evidence_source_count": 2,
                        },
                        {
                            "ticker": "2308",
                            "name": "台達電",
                            "segment": "電源與散熱",
                            "status": "needs_evidence",
                            "evidence_count": 0,
                            "evidence_source_count": 0,
                        },
                    ],
                }
            }
        }
    )

    assert summary["changed"] is True
    assert summary["total"] == 3
    assert summary["promoted_count"] == 2
    assert summary["weak_count"] == 0
    assert summary["needs_evidence_count"] == 1
    assert summary["document_query_count"] == 9
    assert summary["document_count"] == 24
    assert summary["newly_promoted"] == ["3324"]
    assert summary["status_changes"][0]["previous_status"] == "weak_evidence"
    assert summary["rows"][1]["股票"] == "3324 雙鴻"


def test_follow_up_result_message_explains_skipped_rerun() -> None:
    helpers = load_report_helpers()

    level, message = helpers["follow_up_result_message"](
        {
            "rerun_report": {
                "status": "skipped",
                "reason": "補資料後仍有關鍵缺口，先不重新產生報告。",
                "blockers": ["公司公開文件仍不足：2382"],
            }
        },
        "執行 2 項任務，補入/更新 0 筆資料，錯誤 0 項",
    )

    assert level == "warning"
    assert "先不重新產生報告" in message
    assert "公司公開文件仍不足：2382" in message


def test_follow_up_result_message_reports_new_report() -> None:
    helpers = load_report_helpers()

    level, message = helpers["follow_up_result_message"](
        {"rerun_report": {"report_id": 9}},
        "執行 2 項任務",
    )

    assert level == "success"
    assert "新報告 #9" in message


def test_follow_up_blocker_action_rows_use_next_actions() -> None:
    helpers = load_report_helpers()

    rows = helpers["follow_up_blocker_action_rows"](
        {
            "results": {
                "ingest_company_filings:2382": {
                    "next_actions": [
                        {
                            "ticker": "2382",
                            "company_name": "廣達",
                            "action": "manual_company_filing_import",
                            "missing_required_types": ["annual_report"],
                            "missing_recommended_types": ["investor_presentation"],
                            "reason": "請補官方文件：annual_report",
                        }
                    ]
                }
            },
            "rerun_report": {"status": "skipped", "blockers": ["公司公開文件仍不足：2382"]},
        }
    )

    assert rows == [
        {
            "股票": "2382",
            "公司": "廣達",
            "下一步": "人工匯入官方文件",
            "缺必要文件": "annual_report",
            "缺建議文件": "investor_presentation",
            "目前": "-",
            "要求": "-",
            "原因": "請補官方文件：annual_report",
        }
    ]


def test_follow_up_blocker_action_rows_prefer_rerun_next_actions() -> None:
    helpers = load_report_helpers()

    rows = helpers["follow_up_blocker_action_rows"](
        {
            "results": {
                "ingest_company_filings:9999": {
                    "next_actions": [
                        {
                            "ticker": "9999",
                            "action": "manual_company_filing_import",
                            "reason": "舊結果",
                        }
                    ]
                }
            },
            "rerun_report": {
                "status": "skipped",
                "next_actions": [
                    {
                        "ticker": "2382",
                        "company_name": "廣達",
                        "action": "manual_company_filing_import",
                        "missing_required_types": ["annual_report"],
                        "reason": "請補官方文件：annual_report",
                    }
                ],
            },
        }
    )

    assert rows[0]["股票"] == "2382"
    assert rows[0]["原因"] == "請補官方文件：annual_report"


def test_follow_up_blocker_action_rows_label_visual_rag_actions() -> None:
    helpers = load_report_helpers()

    rows = helpers["follow_up_blocker_action_rows"](
        {
            "results": {
                "ingest_company_filings:2382": {
                    "next_actions": [
                        {
                            "ticker": "2382",
                            "company_name": "廣達",
                            "action": "configure_company_filing_visual_rag",
                            "reason": "請確認 PyMuPDF、VLM key 與模型。",
                        },
                        {
                            "ticker": "3324",
                            "company_name": "雙鴻",
                            "action": "review_visual_rag_or_manual_import",
                            "reason": "Visual RAG 額度用完。",
                        },
                    ]
                }
            }
        }
    )

    assert [row["下一步"] for row in rows] == [
        "設定 Visual RAG",
        "檢查 Visual RAG/人工匯入",
    ]


def test_follow_up_blocker_action_rows_show_completion_gap() -> None:
    helpers = load_report_helpers()

    rows = helpers["follow_up_blocker_action_rows"](
        {
            "rerun_report": {
                "status": "skipped",
                "next_actions": [
                    {
                        "ticker": "2330",
                        "action": "complete_follow_up_check",
                        "observed": {"stored_count": 90, "error_count": 1},
                        "required": {"min_days": 120, "error_count": 0},
                        "reason": "refresh_market:2330 未達完成條件",
                    }
                ],
            }
        }
    )

    assert rows[0]["下一步"] == "補齊未達標資料"
    assert rows[0]["目前"] == "已取得 90；錯誤 1"
    assert rows[0]["要求"] == "至少天數 120；錯誤 0"


def test_follow_up_check_value_text_formats_lists_and_booleans() -> None:
    helpers = load_report_helpers()

    text = helpers["follow_up_check_value_text"](
        {"blocked_tickers": ["2382", "3324"], "manual_review": True}
    )

    assert text == "仍缺公司 2382、3324；需人工覆核 是"


def test_follow_up_blocker_action_rows_fall_back_to_blockers() -> None:
    helpers = load_report_helpers()

    rows = helpers["follow_up_blocker_action_rows"](
        {"rerun_report": {"status": "skipped", "blockers": ["公司公開文件仍不足：2382"]}}
    )

    assert rows[0]["下一步"] == "補齊資料後再重跑"
    assert rows[0]["原因"] == "公司公開文件仍不足：2382"
