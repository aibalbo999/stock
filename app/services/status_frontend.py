from __future__ import annotations

from pathlib import Path


def frontend_status() -> dict:
    root = Path(__file__).resolve().parents[2]
    streamlit_path = root / "streamlit_app.py"
    pages_dir = root / "pages"
    ui_dir = root / "app" / "ui"
    style_path = ui_dir / "styles" / "stock_dashboard.css"
    report_style_path = ui_dir / "styles" / "report_html.css"
    streamlit_source = _read_text(streamlit_path)
    ui_paths = [
        ui_dir / "dashboard_core.py",
        ui_dir / "api_client.py",
        ui_dir / "background_tasks.py",
        ui_dir / "task_status_panel.py",
        ui_dir / "report_state.py",
        ui_dir / "report_panels.py",
        ui_dir / "report_follow_up_controls.py",
        ui_dir / "report_markdown.py",
        ui_dir / "report_candidate_audit.py",
        ui_dir / "report_formatters.py",
        ui_dir / "report_sections.py",
        ui_dir / "report_html.py",
        ui_dir / "follow_up_status.py",
        ui_dir / "maintenance_status.py",
        ui_dir / "analysis_workspace.py",
        ui_dir / "report_center.py",
        ui_dir / "data_enrichment.py",
        ui_dir / "data_enrichment_common.py",
        ui_dir / "data_enrichment_manual.py",
        ui_dir / "data_enrichment_market.py",
        ui_dir / "data_enrichment_rss.py",
        ui_dir / "data_enrichment_runtime.py",
        ui_dir / "system_settings.py",
        ui_dir / "system_settings_maintenance.py",
        ui_dir / "streamlit_dashboard.py",
    ]
    ui_source = "\n".join(_read_text(path) for path in ui_paths)
    page_source = "\n".join(
        _read_text(path)
        for path in [
            ui_dir / "analysis_workspace.py",
            ui_dir / "report_center.py",
            ui_dir / "data_enrichment.py",
            ui_dir / "data_enrichment_common.py",
            ui_dir / "data_enrichment_manual.py",
            ui_dir / "data_enrichment_market.py",
            ui_dir / "data_enrichment_rss.py",
            ui_dir / "data_enrichment_runtime.py",
            ui_dir / "system_settings.py",
            ui_dir / "system_settings_maintenance.py",
            ui_dir / "streamlit_dashboard.py",
        ]
    )
    dashboard_core_source = _read_text(ui_dir / "dashboard_core.py")
    api_client_source = _read_text(ui_dir / "api_client.py")
    background_tasks_source = _read_text(ui_dir / "background_tasks.py")
    task_status_panel_source = _read_text(ui_dir / "task_status_panel.py")
    report_state_source = _read_text(ui_dir / "report_state.py")
    report_panels_source = _read_text(ui_dir / "report_panels.py")
    report_follow_up_controls_source = _read_text(ui_dir / "report_follow_up_controls.py")
    report_markdown_source = _read_text(ui_dir / "report_markdown.py")
    report_candidate_audit_source = _read_text(ui_dir / "report_candidate_audit.py")
    report_formatters_source = _read_text(ui_dir / "report_formatters.py")
    report_sections_source = _read_text(ui_dir / "report_sections.py")
    report_html_source = _read_text(ui_dir / "report_html.py")
    follow_up_status_source = _read_text(ui_dir / "follow_up_status.py")
    maintenance_status_source = _read_text(ui_dir / "maintenance_status.py")
    data_enrichment_source = "\n".join(
        _read_text(path)
        for path in [
            ui_dir / "data_enrichment.py",
            ui_dir / "data_enrichment_common.py",
            ui_dir / "data_enrichment_manual.py",
            ui_dir / "data_enrichment_market.py",
            ui_dir / "data_enrichment_rss.py",
            ui_dir / "data_enrichment_runtime.py",
        ]
    )
    pages = sorted(path.name for path in pages_dir.glob("*.py")) if pages_dir.exists() else []
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
        "ui_modules_present": [path.name for path in ui_paths if path.exists()],
        "ui_wildcard_imports_removed": "import *" not in page_source
        and "F403" not in page_source
        and "F405" not in page_source,
        "dashboard_core_lines": len(dashboard_core_source.splitlines()) if dashboard_core_source else None,
        "report_html_renderer_path": "app/ui/report_html.py",
        "report_html_renderer_lines": len(report_html_source.splitlines()) if report_html_source else None,
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
        "ui_api_client_extracted": (ui_dir / "api_client.py").exists()
        and "def api_task_post(" in api_client_source
        and "def request_error_message(" in api_client_source
        and "def queue_data_operation(" in api_client_source
        and "def api_task_post(" not in dashboard_core_source
        and "from app.ui.api_client import (" in ui_source,
        "ui_api_client_path": "app/ui/api_client.py",
        "ui_background_task_client_extracted": (ui_dir / "background_tasks.py").exists()
        and "def submit_background_task(" in background_tasks_source
        and "def submit_api_task(" in background_tasks_source
        and "def submit_data_operation_task(" in background_tasks_source
        and "def submit_background_task(" not in dashboard_core_source
        and "from app.ui.background_tasks import" in ui_source,
        "ui_background_task_client_path": "app/ui/background_tasks.py",
        "ui_task_queue_preflight_enabled": "def task_queue_preflight_ready(" in background_tasks_source
        and "api_task_queue_status" in background_tasks_source
        and "API_TASK_PREFLIGHT_TIMEOUT_SECONDS" in api_client_source
        and "preflight: bool = True" in background_tasks_source,
        "ui_task_queue_preflight_cache_enabled": "def cached_task_queue_status("
        in background_tasks_source
        and "TASK_QUEUE_PREFLIGHT_CACHE_KEY" in background_tasks_source
        and "TASK_QUEUE_PREFLIGHT_READY_TTL_SECONDS" in background_tasks_source
        and "TASK_QUEUE_PREFLIGHT_UNREADY_TTL_SECONDS" in background_tasks_source,
        "ui_task_queue_preflight_degrades_open": "仍會嘗試送出" in background_tasks_source,
        "ui_task_queue_worker_warning_enabled": "def task_queue_worker_warning(" in background_tasks_source
        and "Celery worker 未回應" in background_tasks_source,
        "ui_task_queue_health_panel_extracted": "def task_queue_health_rows(" in maintenance_status_source
        and "def task_queue_health_alert(" in maintenance_status_source
        and "def task_queue_smoke_command(" in maintenance_status_source
        and "task_queue_health_rows(service_snapshot)" in ui_source
        and "task_queue_health_alert(service_snapshot)" in ui_source
        and "task_queue_smoke_command(service_snapshot)" in ui_source,
        "ui_external_deployment_diagnostics_enabled": "def external_deployment_warning_rows("
        in maintenance_status_source
        and "def external_deployment_smoke_commands(" in maintenance_status_source
        and "optional_warnings" in maintenance_status_source
        and "external_deployment_warning_rows(upgrade_audit)" in ui_source
        and "external_deployment_smoke_commands(upgrade_audit)" in ui_source
        and "def local_neo4j_operation_rows(" in maintenance_status_source
        and "local_neo4j_operation_rows(upgrade_audit)" in ui_source
        and "本機 Neo4j / GraphRAG 操作提示" in ui_source
        and "def local_unlocker_operation_rows(" in maintenance_status_source
        and "local_unlocker_operation_rows(upgrade_audit)" in ui_source
        and "本機 unlocker 操作提示" in ui_source
        and "def structured_filing_api_operation_rows(" in maintenance_status_source
        and "structured_filing_api_operation_rows(upgrade_audit)" in ui_source
        and "結構化文件 API 操作提示" in ui_source
        and "單項診斷指令" in ui_source
        and "external_integrations_smoke.py --strict --json" in ui_source,
        "ui_task_failure_drilldown_enabled": "def task_failure_drilldown_rows(" in maintenance_status_source
        and "def task_retry_options(" in maintenance_status_source
        and "task_failure_drilldown_rows(task_summary)" in ui_source
        and "task_retry_options(task_summary)" in ui_source
        and 'api_task_post(\n                                f"/tasks/{selected_retry_task_id}/retry"' in ui_source
        and "render_task_status_panel(" in ui_source,
        "ui_task_failure_category_display_enabled": '"category": row.get("error_category")' in maintenance_status_source
        and '"severity": row.get("error_severity")' in maintenance_status_source
        and '"summary": row.get("error_summary")' in maintenance_status_source
        and '"next_steps": _task_next_steps_text(row)' in maintenance_status_source
        and 'task_summary.get("by_error_category")' in ui_source
        and "失敗原因分類" in ui_source,
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
        "ui_task_status_failure_diagnostics_enabled": "def task_status_diagnostic_rows(" in task_status_panel_source
        and "失敗診斷" in task_status_panel_source
        and '"category": task_status.get("error_category")' in task_status_panel_source
        and '"next_steps": _task_status_next_steps_text(task_status)' in task_status_panel_source,
        "ui_company_filing_runtime_panel_enabled": "def company_filing_runtime_rows(" in data_enrichment_source
        and 'api_get("/services/status"' in data_enrichment_source
        and "API_TASK_PREFLIGHT_TIMEOUT_SECONDS" in data_enrichment_source
        and "公司文件補抓能力" in data_enrichment_source
        and "visual_rag_runtime_available" in data_enrichment_source
        and "structured_api_configured" in data_enrichment_source
        and "playwright_render_configured" in data_enrichment_source,
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
        ],
        "ui_task_status_panel_path": "app/ui/task_status_panel.py",
        "ui_report_observability_summary_enabled": "/reports/observability/summary?limit=20" in ui_source
        and "報告生成觀測" in ui_source
        and "trace_captured_count" in ui_source
        and "keyword_fallback_count" in ui_source,
        "ui_report_observability_bottlenecks_enabled": 'report_observability_summary.get("bottlenecks")'
        in ui_source
        and "優先優化清單" in ui_source,
        "task_retry_uses_scoped_state_key": "task_state_key" in task_status_panel_source
        and 'st.session_state["last_data_task_id"]' not in task_status_panel_source,
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
        "asyncio_run_count": ui_source.count("asyncio.run") + streamlit_source.count("asyncio.run"),
        "long_blocking_post_timeout_present": "timeout=900" in ui_source,
        "api_write_timeout_seconds": _frontend_constant_value(ui_source, "API_WRITE_TIMEOUT_SECONDS"),
        "api_task_queue_timeout_seconds": _frontend_constant_value(
            ui_source,
            "API_TASK_QUEUE_TIMEOUT_SECONDS",
        ),
        "uses_task_enqueue_helper": "def api_task_post(" in ui_source,
        "uses_background_task_submit_helper": "submit_api_task(" in ui_source
        and "submit_data_operation_task(" in ui_source,
        "uses_task_queue_preflight": "task_queue_preflight_ready(" in background_tasks_source
        and "api_task_queue_status" in background_tasks_source,
        "uses_task_status_panel": "def render_task_status_panel(" in ui_source
        and '"fragment"' in ui_source
        and "run_every" in ui_source,
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


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
