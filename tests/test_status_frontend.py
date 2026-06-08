from pathlib import Path

from app.services.status_frontend import frontend_status


def test_frontend_status_mpa_background_task_and_css_evidence(service_status_snapshot) -> None:
    status = service_status_snapshot
    service_status_source = Path("app/services/service_status.py").read_text()
    status_frontend_source = Path("app/services/status_frontend.py").read_text()
    status_frontend_sources_source = Path("app/services/status_frontend_sources.py").read_text()

    assert "frontend" in status
    assert status["frontend"]["streamlit_entry_uses_navigation"] is True
    assert status["frontend"]["collector_path"] == "app/services/status_frontend.py"
    assert frontend_status()["collector_path"] == "app/services/status_frontend.py"
    assert (
        "from app.services.status_frontend import frontend_status as collect_frontend_status"
        in (service_status_source)
    )
    assert "def _frontend_status(" not in service_status_source
    assert "def frontend_status(" in status_frontend_source
    assert "def frontend_source_context(" in status_frontend_sources_source
    assert "def _literal_occurrence_locations(" not in status_frontend_source
    assert status["frontend"]["frontend_source_context_extracted"] is True
    assert status["frontend"]["frontend_source_context_path"] == (
        "app/services/status_frontend_sources.py"
    )
    assert status["frontend"]["page_count"] >= 4
    assert status["frontend"]["expected_pages_present"] is True
    assert status["frontend"]["streamlit_page_import_contract_ready"] is True
    assert status["frontend"]["report_html_renderer_extracted"] is True
    assert status["frontend"]["report_html_renderer_path"] == "app/ui/report_html.py"
    assert status["frontend"]["ui_status_helpers_extracted"] is True
    assert status["frontend"]["ui_status_helper_paths"] == [
        "app/ui/follow_up_status.py",
        "app/ui/maintenance_status.py",
    ]
    assert status["frontend"]["ui_maintenance_panels_extracted"] is True
    assert status["frontend"]["ui_maintenance_panels_path"] == "app/ui/maintenance_panels.py"
    assert status["frontend"]["ui_maintenance_panel_module_paths"] == [
        "app/ui/maintenance_deployment_panel.py",
        "app/ui/maintenance_ai_panels.py",
        "app/ui/maintenance_task_panels.py",
        "app/ui/maintenance_cleanup_panel.py",
    ]
    assert status["frontend"]["ui_system_settings_tabs_extracted"] is True
    assert status["frontend"]["ui_system_settings_tab_paths"] == [
        "app/ui/system_settings_scope.py",
        "app/ui/system_settings_schedule.py",
    ]
    assert status["frontend"]["ui_api_client_extracted"] is True
    assert status["frontend"]["ui_api_client_path"] == "app/ui/api_client.py"
    assert status["frontend"]["ui_api_loaders_extracted"] is True
    assert status["frontend"]["ui_api_loaders_path"] == "app/ui/api_loaders.py"
    assert status["frontend"]["ui_background_task_client_extracted"] is True
    assert status["frontend"]["ui_background_task_client_path"] == "app/ui/background_tasks.py"
    assert status["frontend"]["ui_task_queue_preflight_enabled"] is True
    assert status["frontend"]["ui_task_queue_preflight_cache_enabled"] is True
    assert status["frontend"]["ui_task_queue_preflight_degrades_open"] is True
    assert status["frontend"]["ui_task_queue_worker_warning_enabled"] is True
    assert status["frontend"]["ui_task_queue_health_panel_extracted"] is True
    assert status["frontend"]["ui_task_queue_repair_guidance_enabled"] is True
    assert status["frontend"]["ui_task_queue_processing_readiness_displayed"] is True
    assert (
        status["frontend"]["ui_task_queue_diagnostics_path"] == "app/ui/task_queue_diagnostics.py"
    )
    assert status["frontend"]["ui_external_deployment_diagnostics_enabled"] is True
    assert status["frontend"]["ui_external_deployment_readiness_checklist_enabled"] is True
    assert status["frontend"]["ui_external_deployment_diagnostics_extracted"] is True
    assert status["frontend"]["ui_local_dependency_start_history_enabled"] is True
    assert status["frontend"]["ui_external_deployment_diagnostics_path"] == (
        "app/ui/external_deployment_diagnostics.py"
    )
    assert status["frontend"]["ui_external_deployment_domain_helpers_extracted"] is True
    assert status["frontend"]["ui_external_deployment_domain_helper_paths"] == [
        "app/ui/external_deployment_common.py",
        "app/ui/external_deployment_unlocker.py",
        "app/ui/external_deployment_neo4j.py",
        "app/ui/external_deployment_structured_api.py",
    ]
    assert status["frontend"]["ui_task_failure_drilldown_enabled"] is True
    assert status["frontend"]["ui_task_failure_diagnostics_extracted"] is True
    assert status["frontend"]["ui_task_failure_diagnostics_path"] == (
        "app/ui/task_failure_diagnostics.py"
    )
    assert status["frontend"]["ui_task_failure_category_display_enabled"] is True
    assert status["frontend"]["ui_task_failure_trend_enabled"] is True
    assert status["frontend"]["ui_task_failure_alerts_enabled"] is True
    assert status["frontend"]["ui_task_status_panel_extracted"] is True
    assert status["frontend"]["ui_task_status_poll_backoff_enabled"] is True
    assert status["frontend"]["ui_task_status_autorefresh_feedback_enabled"] is True
    assert status["frontend"]["ui_task_status_failure_diagnostics_enabled"] is True
    assert status["frontend"]["ui_llm_quota_panel_extracted"] is True
    assert status["frontend"]["ui_llm_quota_panel_path"] == "app/ui/llm_quota_panel.py"
    assert status["frontend"]["ui_report_observability_panel_extracted"] is True
    assert status["frontend"]["ui_report_observability_panel_path"] == (
        "app/ui/report_observability_panel.py"
    )
    assert status["frontend"]["ui_company_filing_runtime_panel_enabled"] is True
    assert status["frontend"]["ui_visual_rag_model_chain_panel_enabled"] is True
    assert status["frontend"]["ui_data_enrichment_tabs_extracted"] is True
    assert status["frontend"]["ui_data_enrichment_module_paths"] == [
        "app/ui/data_enrichment_market.py",
        "app/ui/data_enrichment_manual.py",
        "app/ui/data_enrichment_rss.py",
        "app/ui/data_enrichment_runtime.py",
    ]
    assert status["frontend"]["ui_task_status_panel_path"] == "app/ui/task_status_panel.py"
    assert status["frontend"]["ui_report_observability_summary_enabled"] is True
    assert status["frontend"]["ui_report_observability_bottlenecks_enabled"] is True
    assert status["frontend"]["task_retry_uses_scoped_state_key"] is True
    assert status["frontend"]["ui_report_state_extracted"] is True
    assert status["frontend"]["ui_report_state_path"] == "app/ui/report_state.py"
    assert status["frontend"]["ui_report_panels_extracted"] is True
    assert status["frontend"]["ui_report_panels_path"] == "app/ui/report_panels.py"
    assert status["frontend"]["ui_report_follow_up_controls_extracted"] is True
    assert status["frontend"]["ui_report_follow_up_controls_path"] == (
        "app/ui/report_follow_up_controls.py"
    )
    assert status["frontend"]["ui_report_markdown_helpers_extracted"] is True
    assert status["frontend"]["ui_report_markdown_helpers_path"] == "app/ui/report_markdown.py"
    assert status["frontend"]["ui_report_candidate_audit_extracted"] is True
    assert (
        status["frontend"]["ui_report_candidate_audit_path"] == "app/ui/report_candidate_audit.py"
    )
    assert status["frontend"]["ui_report_formatters_extracted"] is True
    assert status["frontend"]["ui_report_formatters_path"] == "app/ui/report_formatters.py"
    assert status["frontend"]["ui_report_sections_extracted"] is True
    assert status["frontend"]["ui_report_sections_path"] == "app/ui/report_sections.py"
    assert status["frontend"]["ui_wildcard_imports_removed"] is True
    assert status["frontend"]["dashboard_core_lines"] < 1500
    assert status["frontend"]["external_css_loaded"] is True
    assert status["frontend"]["external_report_css_loaded"] is True
    assert status["frontend"]["external_report_css_path"] == "app/ui/styles/report_html.css"
    assert status["frontend"]["uses_task_enqueue_helper"] is True
    assert status["frontend"]["uses_background_task_submit_helper"] is True
    assert status["frontend"]["uses_task_queue_preflight"] is True
    assert status["frontend"]["uses_task_status_panel"] is True
    blocking_scan_paths = set(status["frontend"]["frontend_blocking_call_scan_paths"])
    expected_ui_scan_paths = {path.as_posix() for path in sorted(Path("app/ui").glob("*.py"))}
    assert expected_ui_scan_paths <= blocking_scan_paths
    assert "streamlit_app.py" in status["frontend"]["frontend_blocking_call_scan_paths"]
    assert "pages/01_分析工作區.py" in status["frontend"]["frontend_blocking_call_scan_paths"]
    assert "pages/04_系統設定.py" in status["frontend"]["frontend_blocking_call_scan_paths"]
    assert "app/ui/__init__.py" in status["frontend"]["frontend_blocking_call_scan_paths"]
    assert "app/ui/background_tasks.py" in status["frontend"]["frontend_blocking_call_scan_paths"]
    assert status["frontend"]["frontend_blocking_call_scan_file_count"] == len(
        status["frontend"]["frontend_blocking_call_scan_paths"]
    )
    assert status["frontend"]["asyncio_run_count"] == 0
    assert status["frontend"]["asyncio_run_locations"] == []
    assert status["frontend"]["long_blocking_post_timeout_present"] is False
    assert status["frontend"]["long_blocking_post_timeout_locations"] == []
    assert status["frontend"]["sync_report_generate_used"] is False
    assert status["frontend"]["api_task_queue_timeout_seconds"] == 20


def test_streamlit_architecture_capability_evidence(service_status_snapshot) -> None:
    status = service_status_snapshot
    frontend_arch = status["upgrade_capability_matrix"]["architecture"][
        "streamlit_mpa_background_tasks"
    ]

    assert frontend_arch["status"] == "ready"
    assert frontend_arch["evidence"]["streamlit_entry_uses_navigation"] is True
    assert frontend_arch["evidence"]["expected_pages_present"] is True
    assert frontend_arch["evidence"]["streamlit_page_import_contract_ready"] is True
    assert frontend_arch["evidence"]["frontend_source_context_extracted"] is True
    assert frontend_arch["evidence"]["report_html_renderer_extracted"] is True
    assert frontend_arch["evidence"]["ui_status_helpers_extracted"] is True
    assert frontend_arch["evidence"]["ui_maintenance_panels_extracted"] is True
    assert frontend_arch["evidence"]["ui_system_settings_tabs_extracted"] is True
    assert frontend_arch["evidence"]["ui_api_client_extracted"] is True
    assert frontend_arch["evidence"]["ui_api_loaders_extracted"] is True
    assert frontend_arch["evidence"]["ui_background_task_client_extracted"] is True
    assert frontend_arch["evidence"]["ui_task_queue_preflight_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_queue_preflight_cache_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_queue_worker_warning_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_queue_health_panel_extracted"] is True
    assert frontend_arch["evidence"]["ui_task_queue_repair_guidance_enabled"] is True
    assert frontend_arch["evidence"]["ui_external_deployment_diagnostics_enabled"] is True
    assert frontend_arch["evidence"]["ui_external_deployment_readiness_checklist_enabled"] is True
    assert frontend_arch["evidence"]["ui_external_deployment_diagnostics_extracted"] is True
    assert frontend_arch["evidence"]["ui_external_deployment_domain_helpers_extracted"] is True
    assert frontend_arch["evidence"]["ui_task_failure_drilldown_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_failure_diagnostics_extracted"] is True
    assert frontend_arch["evidence"]["ui_task_failure_category_display_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_failure_action_routes_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_retry_guard_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_failure_trend_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_failure_alerts_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_status_panel_extracted"] is True
    assert frontend_arch["evidence"]["ui_task_status_poll_backoff_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_status_autorefresh_feedback_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_status_failure_diagnostics_enabled"] is True
    assert frontend_arch["evidence"]["ui_llm_quota_panel_extracted"] is True
    assert frontend_arch["evidence"]["ui_report_observability_panel_extracted"] is True
    assert frontend_arch["evidence"]["ui_company_filing_runtime_panel_enabled"] is True
    assert frontend_arch["evidence"]["ui_visual_rag_model_chain_panel_enabled"] is True
    assert frontend_arch["evidence"]["ui_data_enrichment_tabs_extracted"] is True
    assert frontend_arch["evidence"]["task_retry_uses_scoped_state_key"] is True
    assert frontend_arch["evidence"]["ui_report_state_extracted"] is True
    assert frontend_arch["evidence"]["ui_report_panels_extracted"] is True
    assert frontend_arch["evidence"]["ui_report_follow_up_controls_extracted"] is True
    assert frontend_arch["evidence"]["ui_report_markdown_helpers_extracted"] is True
    assert frontend_arch["evidence"]["ui_report_candidate_audit_extracted"] is True
    assert frontend_arch["evidence"]["ui_report_formatters_extracted"] is True
    assert frontend_arch["evidence"]["ui_report_sections_extracted"] is True
    assert frontend_arch["evidence"]["ui_wildcard_imports_removed"] is True
    assert frontend_arch["evidence"]["external_report_css_loaded"] is True
    assert "pages/03_資料補強.py" in frontend_arch["evidence"]["frontend_blocking_call_scan_paths"]
    assert "app/ui/__init__.py" in frontend_arch["evidence"]["frontend_blocking_call_scan_paths"]
    assert frontend_arch["evidence"]["frontend_blocking_call_scan_file_count"] == len(
        frontend_arch["evidence"]["frontend_blocking_call_scan_paths"]
    )
    assert frontend_arch["evidence"]["asyncio_run_count"] == 0
    assert frontend_arch["evidence"]["asyncio_run_locations"] == []
    assert frontend_arch["evidence"]["uses_background_task_submit_helper"] is True
    assert frontend_arch["evidence"]["uses_task_queue_preflight"] is True
    assert frontend_arch["evidence"]["long_blocking_post_timeout_present"] is False
    assert frontend_arch["evidence"]["long_blocking_post_timeout_locations"] == []
    assert frontend_arch["evidence"]["sync_report_generate_used"] is False
    assert all(frontend_arch["evidence"]["async_task_endpoint_coverage"].values())
