from __future__ import annotations

from app.services.status_frontend_external_deployment import (
    frontend_external_deployment_status,
)
from app.services.status_frontend_sources import frontend_source_context
from app.services.status_frontend_tasks import frontend_task_ui_status


def frontend_status() -> dict:
    source_context = frontend_source_context()
    root = source_context.root
    ui_dir = source_context.ui_dir
    style_path = source_context.style_path
    report_style_path = source_context.report_style_path
    streamlit_source = source_context.streamlit_source
    ui_paths = source_context.ui_paths
    ui_source = source_context.ui_source
    page_source = source_context.page_source
    ui_sources = source_context.ui_sources
    dashboard_core_source = ui_sources["dashboard_core.py"]
    api_client_source = ui_sources["api_client.py"]
    api_loaders_source = ui_sources["api_loaders.py"]
    report_state_source = ui_sources["report_state.py"]
    report_panels_source = ui_sources["report_panels.py"]
    report_follow_up_controls_source = ui_sources["report_follow_up_controls.py"]
    report_markdown_source = ui_sources["report_markdown.py"]
    report_candidate_audit_source = ui_sources["report_candidate_audit.py"]
    report_formatters_source = ui_sources["report_formatters.py"]
    report_sections_source = ui_sources["report_sections.py"]
    report_html_source = ui_sources["report_html.py"]
    system_settings_maintenance_source = ui_sources["system_settings_maintenance.py"]
    maintenance_panels_source = ui_sources["maintenance_panels.py"]
    maintenance_deployment_panel_source = ui_sources["maintenance_deployment_panel.py"]
    maintenance_ai_panels_source = ui_sources["maintenance_ai_panels.py"]
    maintenance_task_panels_source = ui_sources["maintenance_task_panels.py"]
    maintenance_cleanup_panel_source = ui_sources["maintenance_cleanup_panel.py"]
    follow_up_status_source = ui_sources["follow_up_status.py"]
    llm_quota_panel_source = ui_sources["llm_quota_panel.py"]
    report_observability_panel_source = ui_sources["report_observability_panel.py"]
    maintenance_status_source = ui_sources["maintenance_status.py"]
    system_settings_source = ui_sources["system_settings.py"]
    system_settings_scope_source = ui_sources["system_settings_scope.py"]
    system_settings_schedule_source = ui_sources["system_settings_schedule.py"]
    data_enrichment_runtime_source = ui_sources["data_enrichment_runtime.py"]
    company_filing_runtime_rows_service_path = (
        root / "app" / "services" / "company_filing_runtime_rows.py"
    )
    company_filing_runtime_rows_service_source = (
        company_filing_runtime_rows_service_path.read_text()
        if company_filing_runtime_rows_service_path.exists()
        else ""
    )
    data_enrichment_source = source_context.data_enrichment_source
    pages = source_context.pages
    streamlit_pages_source = source_context.streamlit_pages_source
    frontend_blocking_call_scan_paths = source_context.frontend_blocking_call_scan_paths
    asyncio_run_locations = source_context.asyncio_run_locations
    long_blocking_post_locations = source_context.long_blocking_post_locations
    async_task_endpoints = [
        "/pipeline/run_discovered_async",
        "/reports/generate_async",
        "/tasks/data-operation",
        "/follow-up/run_async",
    ]
    sync_report_generate_used = any(
        pattern in ui_source
        for pattern in (
            'api_post("/reports/generate",',
            "api_post('/reports/generate',",
            'api_task_post("/reports/generate",',
            "api_task_post('/reports/generate',",
        )
    )
    return {
        "collector_path": "app/services/status_frontend.py",
        "frontend_source_context_extracted": source_context.__class__.__name__
        == "FrontendSourceContext"
        and "dashboard_core.py" in ui_sources
        and "api_loaders.py" in ui_sources
        and "maintenance_cleanup_panel.py" in ui_sources
        and bool(frontend_blocking_call_scan_paths),
        "frontend_source_context_path": "app/services/status_frontend_sources.py",
        "streamlit_app_lines": len(streamlit_source.splitlines()) if streamlit_source else None,
        "streamlit_entry_uses_navigation": "st.navigation" in streamlit_source
        and "st.Page" in streamlit_source,
        "page_count": len(pages),
        "pages": pages,
        "expected_pages_present": all(
            page in pages
            for page in [
                "01_分析工作區.py",
                "02_報告中心.py",
                "03_資料補強.py",
                "04_系統設定.py",
            ]
        ),
        "streamlit_page_import_contract_ready": (
            "from app.ui.dashboard_core import configure_page" in ui_source
            and "from app.ui.streamlit_dashboard import configure_page" in streamlit_pages_source
            and "render_analysis_workspace" in streamlit_pages_source
            and "render_report_center" in streamlit_pages_source
            and "render_data_enrichment" in streamlit_pages_source
            and "render_system_settings" in streamlit_pages_source
        ),
        "ui_modules_present": [path.name for path in ui_paths if path.exists()],
        "ui_wildcard_imports_removed": "import *" not in page_source
        and "F403" not in page_source
        and "F405" not in page_source,
        "dashboard_core_lines": len(dashboard_core_source.splitlines())
        if dashboard_core_source
        else None,
        "report_html_renderer_path": "app/ui/report_html.py",
        "report_html_renderer_lines": len(report_html_source.splitlines())
        if report_html_source
        else None,
        "report_html_renderer_extracted": (ui_dir / "report_html.py").exists()
        and "def report_html(" in report_html_source
        and "def report_html(" not in dashboard_core_source
        and "from app.ui.report_html import (" in ui_source,
        "ui_status_helpers_extracted": (ui_dir / "follow_up_status.py").exists()
        and (ui_dir / "maintenance_status.py").exists()
        and "def follow_up_result_message(" in follow_up_status_source
        and "def follow_up_result_message(" not in dashboard_core_source
        and "def upgrade_audit_html(" in maintenance_status_source
        and "def upgrade_audit_html(" not in dashboard_core_source
        and "from app.ui.follow_up_status import (" in ui_source
        and "from app.ui.maintenance_status import (" in ui_source,
        "ui_status_helper_paths": [
            "app/ui/follow_up_status.py",
            "app/ui/maintenance_status.py",
        ],
        "ui_maintenance_panels_extracted": (ui_dir / "maintenance_panels.py").exists()
        and (ui_dir / "maintenance_deployment_panel.py").exists()
        and (ui_dir / "maintenance_ai_panels.py").exists()
        and (ui_dir / "maintenance_task_panels.py").exists()
        and (ui_dir / "maintenance_cleanup_panel.py").exists()
        and "from app.ui.maintenance_deployment_panel import render_external_deployment_panel"
        in maintenance_panels_source
        and "from app.ui.maintenance_ai_panels import (" in maintenance_panels_source
        and "from app.ui.maintenance_task_panels import render_background_task_observability_panel"
        in maintenance_panels_source
        and "from app.ui.maintenance_cleanup_panel import render_maintenance_cleanup_panel"
        in maintenance_panels_source
        and "def render_external_deployment_panel(" in maintenance_deployment_panel_source
        and "service_snapshot: dict | None = None" in maintenance_deployment_panel_source
        and "local_dependency_status_rows(service_snapshot)" in maintenance_deployment_panel_source
        and "local_dependency_last_start_rows(service_snapshot)"
        in maintenance_deployment_panel_source
        and "local_dependency_repair_rows(service_snapshot)" in maintenance_deployment_panel_source
        and "def render_ai_usage_panel(" in maintenance_ai_panels_source
        and "def render_background_task_observability_panel(" in maintenance_task_panels_source
        and "def render_report_quality_panel(" in maintenance_panels_source
        and "def render_maintenance_cleanup_panel(" in maintenance_cleanup_panel_source
        and "from app.ui.maintenance_panels import (" in system_settings_maintenance_source
        and "render_external_deployment_panel(\n        upgrade_audit,"
        in system_settings_maintenance_source
        and 'maintenance_operations = load_api_json_or_default(\n        "/maintenance/operations"'
        in system_settings_maintenance_source
        and "maintenance_operations,\n    )" in system_settings_maintenance_source
        and "render_background_task_observability_panel(\n        service_snapshot,"
        in system_settings_maintenance_source
        and 'maintenance_diagnostics = load_api_json_or_default(\n        "/maintenance/diagnostics"'
        in system_settings_maintenance_source
        and "maintenance_diagnostics,\n    )" in system_settings_maintenance_source
        and "external_deployment_warning_rows(upgrade_audit)"
        not in system_settings_maintenance_source
        and 'st.expander("背景任務觀測"' not in system_settings_maintenance_source,
        "ui_maintenance_panels_path": "app/ui/maintenance_panels.py",
        "ui_maintenance_panel_module_paths": [
            "app/ui/maintenance_deployment_panel.py",
            "app/ui/maintenance_ai_panels.py",
            "app/ui/maintenance_task_panels.py",
            "app/ui/maintenance_cleanup_panel.py",
        ],
        "ui_system_settings_tabs_extracted": (ui_dir / "system_settings_scope.py").exists()
        and (ui_dir / "system_settings_schedule.py").exists()
        and "render_scope_tab(settings_whitelist)" in system_settings_source
        and "render_schedule_tab(sorted(settings_whitelist.allowed_tickers()))"
        in system_settings_source
        and "def render_scope_tab(" in system_settings_scope_source
        and "def render_schedule_tab(" in system_settings_schedule_source
        and 'api_put("/schedule"' in system_settings_schedule_source
        and "SupplyChainWhitelist" not in system_settings_schedule_source
        and 'api_put("/schedule"' not in system_settings_source
        and "st.dataframe(segment_rows" not in system_settings_source,
        "ui_system_settings_tab_paths": [
            "app/ui/system_settings_scope.py",
            "app/ui/system_settings_schedule.py",
        ],
        "ui_api_client_extracted": (ui_dir / "api_client.py").exists()
        and "def api_task_post(" in api_client_source
        and "def request_error_message(" in api_client_source
        and "def queue_data_operation(" in api_client_source
        and "def api_task_post(" not in dashboard_core_source
        and "from app.ui.api_client import (" in ui_source,
        "ui_api_client_path": "app/ui/api_client.py",
        "ui_api_loaders_extracted": (ui_dir / "api_loaders.py").exists()
        and "def load_api_json_or_default(" in api_loaders_source
        and "request_error_message(exc)" in api_loaders_source
        and "deepcopy(fallback)" in api_loaders_source
        and "from app.ui.api_loaders import load_api_json_or_default" in ui_source,
        "ui_api_loaders_path": "app/ui/api_loaders.py",
        **frontend_task_ui_status(source_context),
        **frontend_external_deployment_status(source_context),
        "ui_llm_quota_panel_extracted": (ui_dir / "llm_quota_panel.py").exists()
        and "def llm_quota_metric_values(" in llm_quota_panel_source
        and "def llm_quota_model_rows(" in llm_quota_panel_source
        and "def llm_quota_captions(" in llm_quota_panel_source
        and "額度重置" in llm_quota_panel_source
        and "from app.ui.llm_quota_panel import (" in ui_source
        and "llm_quota_metric_values(llm_quota)" in ui_source
        and "llm_quota_model_rows(llm_quota)" in ui_source,
        "ui_llm_quota_panel_path": "app/ui/llm_quota_panel.py",
        "ui_company_filing_runtime_panel_enabled": "def company_filing_runtime_rows("
        in data_enrichment_source
        and "from app.services.company_filing_runtime_rows import"
        in data_enrichment_runtime_source
        and "def company_filing_runtime_rows(" in company_filing_runtime_rows_service_source
        and (
            'api_get("/services/status"' in data_enrichment_source
            or 'load_api_json_or_default(\n        "/services/status"' in data_enrichment_source
        )
        and "API_TASK_PREFLIGHT_TIMEOUT_SECONDS" in data_enrichment_source
        and "公司文件補抓能力" in data_enrichment_source
        and "visual_rag_runtime_available" in company_filing_runtime_rows_service_source
        and "structured_api_configured" in company_filing_runtime_rows_service_source
        and "playwright_render_configured" in company_filing_runtime_rows_service_source,
        "ui_visual_rag_model_chain_panel_enabled": (
            "def company_filing_visual_rag_model_chain_rows(" in data_enrichment_source
        )
        and "def company_filing_visual_rag_model_chain_rows("
        in company_filing_runtime_rows_service_source
        and "visual_rag_model_chain" in company_filing_runtime_rows_service_source
        and "Visual RAG 模型鏈" in ui_source
        and "Visual RAG / PDF 圖片解析模型鏈" in ui_source,
        "ui_data_enrichment_tabs_extracted": (ui_dir / "data_enrichment_market.py").exists()
        and (ui_dir / "data_enrichment_manual.py").exists()
        and (ui_dir / "data_enrichment_rss.py").exists()
        and (ui_dir / "data_enrichment_runtime.py").exists()
        and "def render_market_data_tab(" in data_enrichment_source
        and "def render_manual_ingest_tab(" in data_enrichment_source
        and "def render_rss_ingest_tab(" in data_enrichment_source
        and "def company_filing_runtime_rows(" in data_enrichment_source
        and "render_market_data_tab(allowed_tickers)" in data_enrichment_source
        and "render_manual_ingest_tab(whitelist, allowed_tickers)" in data_enrichment_source
        and "render_rss_ingest_tab()" in data_enrichment_source,
        "ui_data_enrichment_module_paths": [
            "app/ui/data_enrichment_market.py",
            "app/ui/data_enrichment_manual.py",
            "app/ui/data_enrichment_rss.py",
            "app/ui/data_enrichment_runtime.py",
            "app/services/company_filing_runtime_rows.py",
        ],
        "ui_report_observability_summary_enabled": "/reports/observability/summary?limit=20"
        in ui_source
        and "報告生成觀測" in ui_source
        and "trace_captured_count" in ui_source
        and "keyword_fallback_count" in ui_source,
        "ui_report_observability_bottlenecks_enabled": "def report_observability_bottleneck_rows("
        in report_observability_panel_source
        and 'summary.get("bottlenecks")' in report_observability_panel_source
        and "優先優化清單" in report_observability_panel_source
        and "render_report_observability_panel(report_observability_summary)" in ui_source,
        "ui_report_observability_panel_extracted": (
            ui_dir / "report_observability_panel.py"
        ).exists()
        and "def report_observability_metric_values(" in report_observability_panel_source
        and "def report_observability_bottleneck_rows(" in report_observability_panel_source
        and "def render_report_observability_panel(" in report_observability_panel_source
        and "from app.ui.report_observability_panel import render_report_observability_panel"
        in ui_source
        and "render_report_observability_panel(report_observability_summary)" in ui_source
        and "report_obs_cols" not in ui_source,
        "ui_report_observability_panel_path": "app/ui/report_observability_panel.py",
        "ui_report_state_extracted": (ui_dir / "report_state.py").exists()
        and "def hydrate_active_report_result(" in report_state_source
        and "def parse_json_object(" in report_state_source
        and "def hydrate_active_report_result(" not in dashboard_core_source
        and "def parse_json_object(" not in dashboard_core_source
        and "from app.ui.report_state import " in ui_source,
        "ui_report_state_path": "app/ui/report_state.py",
        "ui_report_panels_extracted": (ui_dir / "report_panels.py").exists()
        and "def render_quality_gate(" in report_panels_source
        and "def render_source_audit(" in report_panels_source
        and "def render_company_data_audit(" in report_panels_source
        and "def render_follow_up_controls(" not in report_panels_source
        and "def render_quality_gate(" not in dashboard_core_source
        and "from app.ui.report_panels import (" in ui_source,
        "ui_report_panels_path": "app/ui/report_panels.py",
        "ui_report_follow_up_controls_extracted": (ui_dir / "report_follow_up_controls.py").exists()
        and "def render_follow_up_controls(" in report_follow_up_controls_source
        and "def render_follow_up_flash(" in report_follow_up_controls_source
        and "def render_follow_up_controls(" not in report_panels_source
        and "def render_follow_up_flash(" not in report_panels_source
        and "def render_follow_up_controls(" not in dashboard_core_source
        and "from app.ui.report_follow_up_controls import" in ui_source,
        "ui_report_follow_up_controls_path": "app/ui/report_follow_up_controls.py",
        "ui_report_markdown_helpers_extracted": (ui_dir / "report_markdown.py").exists()
        and "def markdown_table_rows(" in report_markdown_source
        and "def markdown_table_rows_by_header(" in report_markdown_source
        and "def first_tranche_allocation_label(" in report_markdown_source
        and "def markdown_table_rows(" not in report_html_source
        and "def first_tranche_allocation_label(" not in report_html_source
        and "from app.ui.report_markdown import (" in ui_source,
        "ui_report_markdown_helpers_path": "app/ui/report_markdown.py",
        "ui_report_candidate_audit_extracted": (ui_dir / "report_candidate_audit.py").exists()
        and "def candidate_audit_html(" in report_candidate_audit_source
        and "def candidate_source_matches_display_entity(" in report_candidate_audit_source
        and "def candidate_audit_html(" not in report_html_source
        and "def candidate_source_matches_display_entity(" not in report_html_source
        and "from app.ui.report_candidate_audit import" in ui_source,
        "ui_report_candidate_audit_path": "app/ui/report_candidate_audit.py",
        "ui_report_formatters_extracted": (ui_dir / "report_formatters.py").exists()
        and "def metric_count_from_payload(" in report_formatters_source
        and "def quality_issue_html(" in report_formatters_source
        and "def auto_follow_up_status_html(" in report_formatters_source
        and "def metric_count_from_payload(" not in report_html_source
        and "def quality_issue_html(" not in report_html_source
        and "def auto_follow_up_status_html(" not in report_html_source
        and "from app.ui.report_formatters import" in ui_source,
        "ui_report_formatters_path": "app/ui/report_formatters.py",
        "ui_report_sections_extracted": (ui_dir / "report_sections.py").exists()
        and "def comparison_matrix_html(" in report_sections_source
        and "def credibility_html(" in report_sections_source
        and "def follow_up_tasks_html(" in report_sections_source
        and "def comparison_matrix_html(" not in report_html_source
        and "def credibility_html(" not in report_html_source
        and "def follow_up_tasks_html(" not in report_html_source
        and "from app.ui.report_sections import (" in ui_source,
        "ui_report_sections_path": "app/ui/report_sections.py",
        "external_css_path": str(style_path.relative_to(root)),
        "external_css_loaded": style_path.exists()
        and "STYLE_PATH.read_text" in ui_source
        and "unsafe_allow_html=True" in ui_source,
        "external_report_css_path": str(report_style_path.relative_to(root)),
        "external_report_css_loaded": report_style_path.exists()
        and "REPORT_HTML_STYLE_PATH.read_text" in ui_source
        and "<style>{report_css}</style>" in ui_source
        and "<style>\n  :root" not in ui_source,
        "frontend_blocking_call_scan_paths": [
            str(path.relative_to(root)) for path in frontend_blocking_call_scan_paths
        ],
        "frontend_blocking_call_scan_file_count": len(frontend_blocking_call_scan_paths),
        "asyncio_run_count": sum(item["count"] for item in asyncio_run_locations),
        "asyncio_run_locations": asyncio_run_locations,
        "long_blocking_post_timeout_present": bool(long_blocking_post_locations),
        "long_blocking_post_timeout_locations": long_blocking_post_locations,
        "api_write_timeout_seconds": _frontend_constant_value(
            ui_source, "API_WRITE_TIMEOUT_SECONDS"
        ),
        "api_task_queue_timeout_seconds": _frontend_constant_value(
            ui_source,
            "API_TASK_QUEUE_TIMEOUT_SECONDS",
        ),
        "uses_task_enqueue_helper": "def api_task_post(" in ui_source,
        "async_task_endpoints": async_task_endpoints,
        "async_task_endpoint_coverage": {
            endpoint: endpoint in ui_source for endpoint in async_task_endpoints
        },
        "sync_report_generate_used": sync_report_generate_used,
        "data_operation_endpoint_used": "/tasks/data-operation" in ui_source,
    }


def _frontend_constant_value(source: str, name: str) -> int | None:
    prefix = f"{name} = "
    for line in source.splitlines():
        if line.startswith(prefix):
            try:
                return int(line.removeprefix(prefix).strip())
            except ValueError:
                return None
    return None
