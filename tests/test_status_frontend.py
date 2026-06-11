from pathlib import Path

from app.services.status_frontend import frontend_status


def test_frontend_status_mpa_background_task_and_css_evidence(service_status_snapshot) -> None:
    status = service_status_snapshot
    service_status_source = Path("app/services/service_status.py").read_text()
    status_frontend_source = Path("app/services/status_frontend.py").read_text()
    status_frontend_sources_source = Path("app/services/status_frontend_sources.py").read_text()
    status_frontend_data_enrichment_source = Path(
        "app/services/status_frontend_data_enrichment.py"
    ).read_text()
    status_frontend_data_enrichment_runtime_source = Path(
        "app/services/status_frontend_data_enrichment_runtime.py"
    ).read_text()
    status_frontend_data_enrichment_tabs_source = Path(
        "app/services/status_frontend_data_enrichment_tabs.py"
    ).read_text()
    status_frontend_external_source = Path(
        "app/services/status_frontend_external_deployment.py"
    ).read_text()
    status_frontend_external_domains_source = Path(
        "app/services/status_frontend_external_deployment_domains.py"
    ).read_text()
    status_frontend_external_readiness_source = Path(
        "app/services/status_frontend_external_deployment_readiness.py"
    ).read_text()
    external_deployment_profiles_source = Path(
        "app/services/external_deployment_profiles.py"
    ).read_text()
    status_frontend_report_rendering_source = Path(
        "app/services/status_frontend_report_rendering.py"
    ).read_text()
    status_frontend_report_workflow_source = Path(
        "app/services/status_frontend_report_workflow.py"
    ).read_text()
    status_frontend_reports_source = Path("app/services/status_frontend_reports.py").read_text()
    status_frontend_runtime_source = Path("app/services/status_frontend_runtime.py").read_text()
    status_frontend_operator_source = Path(
        "app/services/status_frontend_operator_workbench.py"
    ).read_text()
    status_frontend_maintenance_source = Path(
        "app/services/status_frontend_maintenance.py"
    ).read_text()
    status_frontend_settings_core_source = Path(
        "app/services/status_frontend_settings_core.py"
    ).read_text()
    status_frontend_settings_source = Path("app/services/status_frontend_settings.py").read_text()
    status_frontend_task_failures_source = Path(
        "app/services/status_frontend_task_failures.py"
    ).read_text()
    status_frontend_task_queue_source = Path(
        "app/services/status_frontend_task_queue.py"
    ).read_text()
    status_frontend_tasks_source = Path("app/services/status_frontend_tasks.py").read_text()

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
    assert "def frontend_runtime_status(" in status_frontend_runtime_source
    assert "frontend_runtime_status(source_context)" in status_frontend_source
    assert "def frontend_operator_workbench_status(" in status_frontend_operator_source
    assert "frontend_operator_workbench_status(source_context)" in status_frontend_source
    assert '"frontend_blocking_call_scan_paths"' not in status_frontend_source
    assert '"asyncio_run_count"' not in status_frontend_source
    assert '"async_task_endpoint_coverage"' not in status_frontend_source
    assert '"sync_report_generate_used"' not in status_frontend_source
    assert "def _frontend_constant_value(" not in status_frontend_source
    assert "def frontend_data_enrichment_status(" in status_frontend_data_enrichment_source
    assert "frontend_data_enrichment_status(source_context)" in status_frontend_source
    assert "def frontend_data_enrichment_tabs_status(" in (
        status_frontend_data_enrichment_tabs_source
    )
    assert "frontend_data_enrichment_tabs_status(source_context)" in (
        status_frontend_data_enrichment_source
    )
    assert "def frontend_data_enrichment_runtime_status(" in (
        status_frontend_data_enrichment_runtime_source
    )
    assert "frontend_data_enrichment_runtime_status(source_context)" in (
        status_frontend_data_enrichment_source
    )
    assert '"ui_company_filing_runtime_panel_enabled"' not in status_frontend_source
    assert '"ui_data_enrichment_tabs_extracted"' not in status_frontend_source
    assert '"ui_data_enrichment_tabs_extracted"' not in (status_frontend_data_enrichment_source)
    assert '"ui_company_filing_runtime_panel_enabled"' not in (
        status_frontend_data_enrichment_source
    )
    assert '"ui_visual_rag_model_chain_panel_enabled"' not in (
        status_frontend_data_enrichment_source
    )
    assert "def frontend_external_deployment_status(" in status_frontend_external_source
    assert "frontend_external_deployment_status(source_context)" in status_frontend_source
    assert '"ui_external_deployment_diagnostics_enabled"' not in status_frontend_source
    assert "def frontend_external_deployment_domain_status(" in (
        status_frontend_external_domains_source
    )
    assert "frontend_external_deployment_domain_status(source_context)" in (
        status_frontend_external_source
    )
    assert "def frontend_external_deployment_readiness_status(" in (
        status_frontend_external_readiness_source
    )
    assert "frontend_external_deployment_readiness_status(source_context)" in (
        status_frontend_external_source
    )
    assert "EXTERNAL_READINESS_METADATA = {" in external_deployment_profiles_source
    assert "EXTERNAL_ENABLEMENT_METADATA = {" in external_deployment_profiles_source
    assert "EXTERNAL_LOCAL_ACTION_METADATA = {" in external_deployment_profiles_source
    assert "EXTERNAL_SMOKE_COMMAND_KEYS = frozenset(" in external_deployment_profiles_source
    assert '"ui_external_deployment_diagnostics_enabled"' not in (status_frontend_external_source)
    assert '"ui_external_deployment_readiness_checklist_enabled"' not in (
        status_frontend_external_source
    )
    assert '"ui_maintenance_operations_enabled"' not in status_frontend_external_source
    assert "def frontend_report_ui_status(" in status_frontend_reports_source
    assert "frontend_report_ui_status(source_context)" in status_frontend_source
    assert "def frontend_report_rendering_status(" in status_frontend_report_rendering_source
    assert "frontend_report_rendering_status(source_context)" in status_frontend_reports_source
    assert "def frontend_report_workflow_status(" in status_frontend_report_workflow_source
    assert "frontend_report_workflow_status(source_context)" in status_frontend_reports_source
    assert '"report_html_renderer_extracted"' not in status_frontend_reports_source
    assert '"ui_report_observability_summary_enabled"' not in status_frontend_reports_source
    assert '"ui_report_state_extracted"' not in status_frontend_reports_source
    assert '"ui_report_sections_extracted"' not in status_frontend_reports_source
    assert '"external_report_css_loaded"' not in status_frontend_reports_source
    assert '"ui_report_observability_summary_enabled"' not in status_frontend_source
    assert '"ui_report_sections_extracted"' not in status_frontend_source
    assert "def frontend_settings_ui_status(" in status_frontend_settings_source
    assert "frontend_settings_ui_status(source_context)" in status_frontend_source
    assert "def frontend_settings_core_status(" in status_frontend_settings_core_source
    assert "frontend_settings_core_status(source_context)" in status_frontend_settings_source
    assert "def frontend_maintenance_ui_status(" in status_frontend_maintenance_source
    assert "frontend_maintenance_ui_status(source_context)" in status_frontend_settings_source
    assert '"ui_status_helpers_extracted"' not in status_frontend_settings_source
    assert '"ui_maintenance_panels_extracted"' not in status_frontend_settings_source
    assert '"ui_system_settings_tabs_extracted"' not in status_frontend_settings_source
    assert '"ui_api_client_extracted"' not in status_frontend_settings_source
    assert '"ui_api_loaders_extracted"' not in status_frontend_settings_source
    assert '"ui_llm_quota_panel_extracted"' not in status_frontend_settings_source
    assert '"ui_maintenance_panels_extracted"' not in status_frontend_source
    assert '"ui_system_settings_tabs_extracted"' not in status_frontend_source
    assert '"ui_api_client_extracted"' not in status_frontend_source
    assert '"ui_api_loaders_extracted"' not in status_frontend_source
    assert '"ui_llm_quota_panel_extracted"' not in status_frontend_source
    assert "def frontend_task_ui_status(" in status_frontend_tasks_source
    assert "frontend_task_ui_status(source_context)" in status_frontend_source
    assert "def frontend_task_queue_status(" in status_frontend_task_queue_source
    assert "frontend_task_queue_status(source_context)" in status_frontend_tasks_source
    assert "def frontend_task_failure_status(" in status_frontend_task_failures_source
    assert "frontend_task_failure_status(source_context)" in status_frontend_tasks_source
    assert '"ui_background_task_client_extracted"' not in status_frontend_tasks_source
    assert '"ui_task_queue_preflight_enabled"' not in status_frontend_tasks_source
    assert '"ui_task_failure_drilldown_enabled"' not in status_frontend_tasks_source
    assert '"ui_task_status_panel_extracted"' not in status_frontend_tasks_source
    assert '"ui_maintenance_diagnostic_actions_enabled"' not in status_frontend_tasks_source
    assert '"ui_task_failure_drilldown_enabled"' not in status_frontend_source
    assert '"ui_task_queue_preflight_enabled"' not in status_frontend_source
    assert "def _literal_occurrence_locations(" not in status_frontend_source
    assert status["frontend"]["frontend_source_context_extracted"] is True
    assert status["frontend"]["frontend_source_context_path"] == (
        "app/services/status_frontend_sources.py"
    )
    assert status["frontend"]["frontend_runtime_status_extracted"] is True
    assert status["frontend"]["frontend_runtime_status_path"] == (
        "app/services/status_frontend_runtime.py"
    )
    assert status["frontend"]["frontend_operator_workbench_status_extracted"] is True
    assert status["frontend"]["frontend_operator_workbench_status_path"] == (
        "app/services/status_frontend_operator_workbench.py"
    )
    assert status["frontend"]["ui_analysis_submission_quota_confirmation_enabled"] is True
    assert status["frontend"]["ui_analysis_submission_preflight_summary_enabled"] is True
    assert status["frontend"]["ui_data_task_followup_summary_enabled"] is True
    assert status["frontend"]["ui_operator_quota_summary_enabled"] is True
    assert status["frontend"]["ui_operator_quota_step_caption_enabled"] is True
    assert status["frontend"]["ui_analysis_submission_quota_pressure_guidance_enabled"] is True
    assert status["frontend"]["ui_operator_retryable_failure_primary_action_enabled"] is True
    assert status["frontend"]["ui_operator_stale_running_primary_action_enabled"] is True
    assert status["frontend"]["ui_operator_quota_missing_read_guard_enabled"] is True
    assert status["frontend"]["ui_operator_market_freshness_primary_action_enabled"] is True
    assert status["frontend"]["ui_operator_secondary_action_labels_enabled"] is True
    assert status["frontend"]["ui_operator_source_labels_enabled"] is True
    assert status["frontend"]["ui_operator_local_defaults_secondary_action_enabled"] is True
    assert status["frontend"]["ui_operator_free_validation_secondary_action_enabled"] is True
    assert status["frontend"]["ui_operator_service_status_unknown_guard_enabled"] is True
    assert status["frontend"]["ui_operator_task_summary_unknown_guard_enabled"] is True
    assert status["frontend"]["ui_operator_running_task_overall_message_enabled"] is True
    assert status["frontend"]["ui_operator_running_task_primary_action_enabled"] is True
    assert status["frontend"]["ui_operator_running_task_report_card_enabled"] is True
    assert status["frontend"]["ui_operator_running_task_pending_card_enabled"] is True
    assert status["frontend"]["ui_operator_running_task_queue_card_enabled"] is True
    assert (
        status["frontend"][
            "ui_operator_historical_failure_secondary_when_latest_task_healthy_enabled"
        ]
        is True
    )
    assert (
        status["frontend"][
            "ui_operator_overall_historical_failure_ready_when_latest_task_healthy_enabled"
        ]
        is True
    )
    assert (
        status["frontend"][
            "ui_operator_missing_report_prioritized_before_historical_failure_enabled"
        ]
        is True
    )
    assert status["frontend"]["ui_operator_latest_failure_overall_message_enabled"] is True
    assert (
        status["frontend"][
            "ui_operator_card_historical_failure_trackable_when_latest_task_healthy_enabled"
        ]
        is True
    )
    assert status["frontend"]["frontend_runtime_identity_marker_enabled"] is True
    assert status["frontend"]["frontend_runtime_identity_marker_path"] == (
        "app/ui/dashboard_core.py"
    )
    assert status["frontend"]["ui_streamlit_operator_chrome_hidden"] is True
    assert status["frontend"]["ui_touch_targets_min_size_enabled"] is True
    assert status["frontend"]["ui_sidebar_nav_touch_targets_min_size_enabled"] is True
    assert status["frontend"]["ui_selectbox_touch_targets_min_size_enabled"] is True
    assert status["frontend"]["ui_form_input_touch_targets_min_size_enabled"] is True
    assert status["frontend"]["ui_choice_control_touch_targets_min_size_enabled"] is True
    assert status["frontend"]["ui_expander_touch_targets_min_size_enabled"] is True
    assert status["frontend"]["ui_streamlit_heading_anchor_noise_hidden"] is True
    assert status["frontend"]["frontend_smoke_checks_runtime_identity_marker"] is True
    assert status["frontend"]["frontend_data_enrichment_status_extracted"] is True
    assert status["frontend"]["frontend_data_enrichment_status_path"] == (
        "app/services/status_frontend_data_enrichment.py"
    )
    assert status["frontend"]["frontend_data_enrichment_tabs_status_extracted"] is True
    assert status["frontend"]["frontend_data_enrichment_tabs_status_path"] == (
        "app/services/status_frontend_data_enrichment_tabs.py"
    )
    assert status["frontend"]["frontend_data_enrichment_runtime_status_extracted"] is True
    assert status["frontend"]["frontend_data_enrichment_runtime_status_path"] == (
        "app/services/status_frontend_data_enrichment_runtime.py"
    )
    assert status["frontend"]["ui_operator_data_gap_prefill_enabled"] is True
    assert (
        status["frontend"]["ui_data_enrichment_pending_operation_button_priority_enabled"]
        is True
    )
    assert status["frontend"]["ui_data_enrichment_pending_handoff_banner_enabled"] is True
    assert status["frontend"]["ui_data_enrichment_operation_readiness_enabled"] is True
    assert status["frontend"]["ui_data_enrichment_submission_preflight_summary_enabled"] is True
    assert status["frontend"]["ui_data_enrichment_task_queue_guard_enabled"] is True
    assert status["frontend"]["ui_data_enrichment_market_submission_confirmation_enabled"] is True
    assert status["frontend"]["ui_manual_news_import_confirmation_enabled"] is True
    assert status["frontend"]["ui_manual_company_filing_import_confirmation_enabled"] is True
    assert status["frontend"]["ui_company_filing_url_import_confirmation_enabled"] is True
    assert status["frontend"]["ui_rss_fetch_confirmation_enabled"] is True
    assert status["frontend"]["ui_manual_data_ingest_preflight_summary_enabled"] is True
    assert status["frontend"]["ui_rss_data_ingest_preflight_summary_enabled"] is True
    assert status["frontend"]["ui_data_enrichment_allowlist_scope_summary_enabled"] is True
    assert status["frontend"]["ui_data_enrichment_pending_ticker_allowlist_guard_enabled"] is True
    assert status["frontend"]["ui_market_cache_operator_summary_enabled"] is True
    assert status["frontend"]["frontend_external_deployment_status_extracted"] is True
    assert status["frontend"]["frontend_external_deployment_status_path"] == (
        "app/services/status_frontend_external_deployment.py"
    )
    assert status["frontend"]["frontend_external_deployment_domain_status_extracted"] is True
    assert status["frontend"]["frontend_external_deployment_domain_status_path"] == (
        "app/services/status_frontend_external_deployment_domains.py"
    )
    assert status["frontend"]["frontend_external_deployment_readiness_status_extracted"] is True
    assert status["frontend"]["frontend_external_deployment_readiness_status_path"] == (
        "app/services/status_frontend_external_deployment_readiness.py"
    )
    assert status["frontend"]["frontend_report_ui_status_extracted"] is True
    assert status["frontend"]["frontend_report_ui_status_path"] == (
        "app/services/status_frontend_reports.py"
    )
    assert status["frontend"]["frontend_report_rendering_status_extracted"] is True
    assert status["frontend"]["frontend_report_rendering_status_path"] == (
        "app/services/status_frontend_report_rendering.py"
    )
    assert status["frontend"]["frontend_report_workflow_status_extracted"] is True
    assert status["frontend"]["frontend_report_workflow_status_path"] == (
        "app/services/status_frontend_report_workflow.py"
    )
    assert status["frontend"]["ui_report_lifecycle_data_gap_prefill_enabled"] is True
    assert status["frontend"]["ui_report_delete_confirmation_gate_enabled"] is True
    assert status["frontend"]["ui_run_delete_confirmation_gate_enabled"] is True
    assert status["frontend"]["ui_report_delete_scope_caption_enabled"] is True
    assert status["frontend"]["ui_report_reader_decision_summary_enabled"] is True
    assert status["frontend"]["ui_report_latest_only_scope_note_enabled"] is True
    assert status["frontend"]["frontend_settings_ui_status_extracted"] is True
    assert status["frontend"]["frontend_settings_ui_status_path"] == (
        "app/services/status_frontend_settings.py"
    )
    assert status["frontend"]["frontend_settings_core_status_extracted"] is True
    assert status["frontend"]["frontend_settings_core_status_path"] == (
        "app/services/status_frontend_settings_core.py"
    )
    assert status["frontend"]["frontend_maintenance_ui_status_extracted"] is True
    assert status["frontend"]["frontend_maintenance_ui_status_path"] == (
        "app/services/status_frontend_maintenance.py"
    )
    assert status["frontend"]["ui_incident_action_labels_enabled"] is True
    assert status["frontend"]["ui_incident_report_lifecycle_enabled"] is True
    assert status["frontend"]["ui_incident_priority_summary_enabled"] is True
    assert status["frontend"]["ui_incident_historical_context_enabled"] is True
    assert status["frontend"]["ui_incident_header_current_context_enabled"] is True
    assert status["frontend"]["ui_incident_grouped_summary_enabled"] is True
    assert status["frontend"]["ui_incident_grouped_action_controls_enabled"] is True
    assert status["frontend"]["ui_incident_route_captions_enabled"] is True
    assert status["frontend"]["ui_optimization_progress_operator_summary_enabled"] is True
    assert status["frontend"]["ui_optimization_progress_metric_labels_enabled"] is True
    assert status["frontend"]["ui_optimization_progress_next_action_labels_enabled"] is True
    assert (
        status["frontend"]["ui_optimization_progress_compact_action_rows_enabled"]
        is True
    )
    assert (
        status["frontend"]["ui_optimization_progress_paid_external_only_summary_enabled"]
        is True
    )
    assert status["frontend"]["ui_optimization_progress_scope_summary_enabled"] is True
    assert status["frontend"]["ui_settings_ai_quota_route_focus_enabled"] is True
    assert status["frontend"]["ui_settings_task_route_focus_enabled"] is True
    assert status["frontend"]["ui_settings_local_defaults_route_focus_enabled"] is True
    assert status["frontend"]["ui_settings_structured_api_route_focus_enabled"] is True
    assert status["frontend"]["ui_settings_structured_api_focus_context_enabled"] is True
    assert status["frontend"]["frontend_task_ui_status_extracted"] is True
    assert status["frontend"]["frontend_task_ui_status_path"] == (
        "app/services/status_frontend_tasks.py"
    )
    assert status["frontend"]["frontend_task_queue_status_extracted"] is True
    assert status["frontend"]["frontend_task_queue_status_path"] == (
        "app/services/status_frontend_task_queue.py"
    )
    assert status["frontend"]["frontend_task_failure_status_extracted"] is True
    assert status["frontend"]["frontend_task_failure_status_path"] == (
        "app/services/status_frontend_task_failures.py"
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
    assert status["frontend"]["ui_submission_guard_panel_enabled"] is True
    assert '"完整"' in status_frontend_maintenance_source
    assert '"需處理"' in status_frontend_maintenance_source
    assert '"已保護"' in status_frontend_maintenance_source
    assert '"缺保護"' in status_frontend_maintenance_source
    assert '"未知"' in status_frontend_maintenance_source
    assert status["frontend"]["ui_maintenance_panels_path"] == "app/ui/maintenance_panels.py"
    assert status["frontend"]["ui_maintenance_panel_module_paths"] == [
        "app/ui/maintenance_deployment_panel.py",
        "app/ui/maintenance_ai_panels.py",
        "app/ui/maintenance_task_panels.py",
        "app/ui/maintenance_cleanup_panel.py",
    ]
    assert status["frontend"]["ui_maintenance_cleanup_confirmation_gate_enabled"] is True
    assert status["frontend"]["ui_system_settings_tabs_extracted"] is True
    assert status["frontend"]["ui_system_settings_tab_paths"] == [
        "app/ui/system_settings_scope.py",
        "app/ui/system_settings_schedule.py",
    ]
    assert status["frontend"]["ui_scope_static_whitelist_source_summary_enabled"] is True
    assert status["frontend"]["ui_schedule_settings_save_confirmation_enabled"] is True
    assert status["frontend"]["ui_api_client_extracted"] is True
    assert status["frontend"]["ui_api_client_path"] == "app/ui/api_client.py"
    assert status["frontend"]["ui_api_loaders_extracted"] is True
    assert status["frontend"]["ui_api_loaders_path"] == "app/ui/api_loaders.py"
    assert status["frontend"]["ui_background_task_client_extracted"] is True
    assert status["frontend"]["ui_background_task_client_path"] == "app/ui/background_tasks.py"
    assert status["frontend"]["ui_api_error_operator_guidance_enabled"] is True
    assert status["frontend"]["ui_task_queue_preflight_enabled"] is True
    assert status["frontend"]["ui_task_queue_preflight_cache_enabled"] is True
    assert status["frontend"]["ui_task_queue_preflight_degrades_open"] is True
    assert status["frontend"]["ui_task_queue_worker_warning_enabled"] is True
    assert status["frontend"]["ui_task_queue_submission_smoke_hint_enabled"] is True
    assert status["frontend"]["ui_task_queue_operator_hint_enabled"] is True
    assert status["frontend"]["ui_task_queue_health_panel_extracted"] is True
    assert status["frontend"]["ui_task_queue_repair_guidance_enabled"] is True
    assert status["frontend"]["ui_task_queue_processing_readiness_displayed"] is True
    assert status["frontend"]["ui_maintenance_diagnostic_actions_enabled"] is True
    assert status["frontend"]["ui_maintenance_diagnostic_confirmation_gate_enabled"] is True
    assert status["frontend"]["ui_maintenance_safe_noop_diagnostics_enabled"] is True
    assert status["frontend"]["ui_maintenance_diagnostic_actions_path"] == (
        "app/ui/maintenance_task_panels.py"
    )
    assert (
        status["frontend"]["ui_task_queue_diagnostics_path"] == "app/ui/task_queue_diagnostics.py"
    )
    assert status["frontend"]["ui_external_deployment_diagnostics_enabled"] is True
    assert status["frontend"]["ui_external_deployment_readiness_checklist_enabled"] is True
    assert status["frontend"]["ui_external_deployment_operator_summary_enabled"] is True
    assert status["frontend"]["ui_external_deployment_profile_catalog_extracted"] is True
    assert status["frontend"]["ui_external_deployment_profile_catalog_path"] == (
        "app/services/external_deployment_profiles.py"
    )
    assert status["frontend"]["ui_external_deployment_diagnostics_extracted"] is True
    assert status["frontend"]["ui_local_dependency_start_history_enabled"] is True
    assert status["frontend"]["ui_local_dependency_repair_guidance_enabled"] is True
    assert status["frontend"]["ui_maintenance_operations_enabled"] is True
    assert status["frontend"]["ui_maintenance_operation_confirmation_gate_enabled"] is True
    assert (
        status["frontend"]["ui_maintenance_post_run_diagnostic_confirmation_gate_enabled"]
        is True
    )
    assert status["frontend"]["ui_maintenance_operations_path"] == (
        "app/ui/maintenance_deployment_presenter.py"
    )
    assert status["frontend"]["frontend_submission_guard_status_extracted"] is True
    assert status["frontend"]["frontend_submission_guard_status_path"] == (
        "app/services/status_frontend_submission_guards.py"
    )
    assert status["frontend"]["ui_risky_submission_guard_coverage_enabled"] is True
    assert status["frontend"]["ui_risky_submission_guard_total_count"] == 16
    assert status["frontend"]["ui_risky_submission_guard_ready_count"] == 16
    assert status["frontend"]["ui_risky_submission_guard_missing"] == []
    guard_rows = status["frontend"]["ui_risky_submission_guard_rows"]
    assert {
        "analysis_submission",
        "market_data_operation",
        "manual_news_import",
        "manual_company_filing_import",
        "company_filing_url_import",
        "rss_fetch",
        "report_follow_up_run",
        "report_delete",
        "run_delete",
        "maintenance_cleanup",
        "maintenance_operation",
        "maintenance_diagnostic",
        "maintenance_post_run_diagnostic",
        "maintenance_task_retry",
        "task_status_operation",
        "schedule_settings_save",
    } == {row["id"] for row in guard_rows}
    assert status["frontend"]["ui_external_deployment_diagnostics_path"] == (
        "app/ui/external_deployment_diagnostics.py"
    )
    assert status["frontend"]["ui_external_deployment_domain_helpers_extracted"] is True
    assert status["frontend"]["ui_external_deployment_domain_helper_paths"] == [
        "app/ui/external_deployment_common.py",
        "app/services/external_deployment_readiness.py",
        "app/services/external_deployment_profiles.py",
        "app/ui/external_deployment_env_keys.py",
        "app/services/external_deployment_env_gaps.py",
        "app/ui/external_deployment_unlocker.py",
        "app/ui/external_deployment_neo4j.py",
        "app/ui/external_deployment_structured_api.py",
    ]
    assert status["frontend"]["ui_task_failure_drilldown_enabled"] is True
    assert status["frontend"]["ui_task_failure_recommended_retry_enabled"] is True
    assert status["frontend"]["ui_task_observability_auto_expand_enabled"] is True
    assert status["frontend"]["ui_task_failure_diagnostics_extracted"] is True
    assert status["frontend"]["ui_task_failure_diagnostics_path"] == (
        "app/ui/task_failure_diagnostics.py"
    )
    assert status["frontend"]["ui_task_failure_category_display_enabled"] is True
    assert status["frontend"]["ui_task_failure_trend_enabled"] is True
    assert status["frontend"]["ui_task_failure_alerts_enabled"] is True
    assert status["frontend"]["ui_maintenance_task_retry_confirmation_gate_enabled"] is True
    assert status["frontend"]["ui_task_status_panel_extracted"] is True
    assert status["frontend"]["ui_task_status_poll_backoff_enabled"] is True
    assert status["frontend"]["ui_task_status_autorefresh_feedback_enabled"] is True
    assert status["frontend"]["ui_task_status_failure_diagnostics_enabled"] is True
    assert status["frontend"]["ui_task_execution_context_enabled"] is True
    assert status["frontend"]["ui_task_status_operation_confirmation_gate_enabled"] is True
    assert status["frontend"]["ui_task_status_operation_preflight_summary_enabled"] is True
    assert status["frontend"]["ui_task_status_operation_label_inference_enabled"] is True
    assert status["frontend"]["ui_task_status_terminal_task_action_guard_enabled"] is True
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
        "app/services/company_filing_runtime_rows.py",
    ]
    assert status["frontend"]["ui_task_status_panel_path"] == "app/ui/task_status_panel.py"
    assert status["frontend"]["ui_report_observability_summary_enabled"] is True
    assert status["frontend"]["ui_report_observability_bottlenecks_enabled"] is True
    assert status["frontend"]["ui_report_observability_recommendations_enabled"] is True
    assert status["frontend"]["ui_report_observability_graphrag_metrics_enabled"] is True
    assert status["frontend"]["ui_report_health_identity_enabled"] is True
    assert status["frontend"]["ui_report_health_action_enabled"] is True
    assert status["frontend"]["ui_report_quality_unknown_guard_enabled"] is True
    assert status["frontend"]["ui_report_market_freshness_action_enabled"] is True
    assert status["frontend"]["ui_report_latest_only_picker_enabled"] is True
    assert status["frontend"]["ui_report_empty_create_analysis_action_enabled"] is True
    assert status["frontend"]["ui_report_empty_running_task_state_enabled"] is True
    assert status["frontend"]["ui_report_advanced_controls_progressive_disclosure_enabled"] is True
    assert status["frontend"]["ui_report_follow_up_submission_confirmation_enabled"] is True
    assert status["frontend"]["ui_report_follow_up_submission_preflight_summary_enabled"] is True
    assert status["frontend"]["task_retry_uses_scoped_state_key"] is True
    assert status["frontend"]["ui_report_state_extracted"] is True
    assert status["frontend"]["ui_report_state_path"] == "app/ui/report_state.py"
    assert status["frontend"]["ui_report_panels_extracted"] is True
    assert status["frontend"]["ui_report_preview_iframe_renderer_enabled"] is True
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
    assert frontend_arch["evidence"]["frontend_runtime_status_extracted"] is True
    assert frontend_arch["evidence"]["frontend_operator_workbench_status_extracted"] is True
    assert frontend_arch["evidence"]["ui_analysis_submission_quota_confirmation_enabled"] is True
    assert frontend_arch["evidence"]["ui_analysis_submission_preflight_summary_enabled"] is True
    assert (
        frontend_arch["evidence"]["ui_analysis_submission_quota_pressure_guidance_enabled"]
        is True
    )
    assert frontend_arch["evidence"]["ui_data_task_followup_summary_enabled"] is True
    assert frontend_arch["evidence"]["ui_operator_quota_summary_enabled"] is True
    assert frontend_arch["evidence"]["ui_operator_quota_step_caption_enabled"] is True
    assert (
        frontend_arch["evidence"]["ui_operator_retryable_failure_primary_action_enabled"]
        is True
    )
    assert (
        frontend_arch["evidence"]["ui_operator_stale_running_primary_action_enabled"]
        is True
    )
    assert frontend_arch["evidence"]["ui_operator_quota_missing_read_guard_enabled"] is True
    assert (
        frontend_arch["evidence"]["ui_operator_market_freshness_primary_action_enabled"]
        is True
    )
    assert frontend_arch["evidence"]["ui_operator_source_labels_enabled"] is True
    assert (
        frontend_arch["evidence"]["ui_operator_local_defaults_secondary_action_enabled"]
        is True
    )
    assert (
        frontend_arch["evidence"]["ui_operator_free_validation_secondary_action_enabled"]
        is True
    )
    assert frontend_arch["evidence"]["ui_operator_service_status_unknown_guard_enabled"] is True
    assert frontend_arch["evidence"]["ui_operator_task_summary_unknown_guard_enabled"] is True
    assert (
        frontend_arch["evidence"]["ui_operator_running_task_overall_message_enabled"] is True
    )
    assert (
        frontend_arch["evidence"]["ui_operator_running_task_primary_action_enabled"] is True
    )
    assert frontend_arch["evidence"]["ui_operator_running_task_report_card_enabled"] is True
    assert frontend_arch["evidence"]["ui_operator_running_task_pending_card_enabled"] is True
    assert frontend_arch["evidence"]["ui_operator_running_task_queue_card_enabled"] is True
    assert (
        frontend_arch["evidence"][
            "ui_operator_historical_failure_secondary_when_latest_task_healthy_enabled"
        ]
        is True
    )
    assert (
        frontend_arch["evidence"][
            "ui_operator_overall_historical_failure_ready_when_latest_task_healthy_enabled"
        ]
        is True
    )
    assert (
        frontend_arch["evidence"][
            "ui_operator_missing_report_prioritized_before_historical_failure_enabled"
        ]
        is True
    )
    assert frontend_arch["evidence"]["ui_operator_latest_failure_overall_message_enabled"] is True
    assert (
        frontend_arch["evidence"][
            "ui_operator_card_historical_failure_trackable_when_latest_task_healthy_enabled"
        ]
        is True
    )
    assert frontend_arch["evidence"]["frontend_runtime_identity_marker_enabled"] is True
    assert frontend_arch["evidence"]["frontend_smoke_checks_runtime_identity_marker"] is True
    assert frontend_arch["evidence"]["frontend_data_enrichment_status_extracted"] is True
    assert frontend_arch["evidence"]["frontend_report_ui_status_extracted"] is True
    assert frontend_arch["evidence"]["frontend_report_rendering_status_extracted"] is True
    assert frontend_arch["evidence"]["frontend_report_workflow_status_extracted"] is True
    assert frontend_arch["evidence"]["ui_report_lifecycle_data_gap_prefill_enabled"] is True
    assert frontend_arch["evidence"]["ui_report_health_identity_enabled"] is True
    assert frontend_arch["evidence"]["ui_report_health_action_enabled"] is True
    assert frontend_arch["evidence"]["ui_report_reader_decision_summary_enabled"] is True
    assert frontend_arch["evidence"]["ui_report_quality_unknown_guard_enabled"] is True
    assert frontend_arch["evidence"]["ui_report_market_freshness_action_enabled"] is True
    assert frontend_arch["evidence"]["ui_report_latest_only_picker_enabled"] is True
    assert frontend_arch["evidence"]["ui_report_latest_only_scope_note_enabled"] is True
    assert (
        frontend_arch["evidence"]["ui_report_empty_create_analysis_action_enabled"]
        is True
    )
    assert frontend_arch["evidence"]["ui_report_empty_running_task_state_enabled"] is True
    assert frontend_arch["evidence"]["ui_run_delete_confirmation_gate_enabled"] is True
    assert frontend_arch["evidence"]["ui_report_delete_scope_caption_enabled"] is True
    assert (
        frontend_arch["evidence"]["ui_report_advanced_controls_progressive_disclosure_enabled"]
        is True
    )
    assert frontend_arch["evidence"]["frontend_settings_ui_status_extracted"] is True
    assert frontend_arch["evidence"]["frontend_settings_core_status_extracted"] is True
    assert frontend_arch["evidence"]["frontend_maintenance_ui_status_extracted"] is True
    assert frontend_arch["evidence"]["ui_incident_action_labels_enabled"] is True
    assert frontend_arch["evidence"]["ui_incident_priority_summary_enabled"] is True
    assert frontend_arch["evidence"]["ui_incident_historical_context_enabled"] is True
    assert frontend_arch["evidence"]["ui_incident_header_current_context_enabled"] is True
    assert frontend_arch["evidence"]["ui_incident_grouped_summary_enabled"] is True
    assert frontend_arch["evidence"]["ui_incident_grouped_action_controls_enabled"] is True
    assert frontend_arch["evidence"]["ui_incident_route_captions_enabled"] is True
    assert frontend_arch["evidence"]["ui_optimization_progress_operator_summary_enabled"] is True
    assert frontend_arch["evidence"]["ui_optimization_progress_metric_labels_enabled"] is True
    assert (
        frontend_arch["evidence"]["ui_optimization_progress_next_action_labels_enabled"]
        is True
    )
    assert (
        frontend_arch["evidence"]["ui_optimization_progress_compact_action_rows_enabled"]
        is True
    )
    assert (
        frontend_arch["evidence"][
            "ui_optimization_progress_paid_external_only_summary_enabled"
        ]
        is True
    )
    assert frontend_arch["evidence"]["ui_optimization_progress_scope_summary_enabled"] is True
    assert frontend_arch["evidence"]["ui_settings_ai_quota_route_focus_enabled"] is True
    assert frontend_arch["evidence"]["ui_settings_task_route_focus_enabled"] is True
    assert frontend_arch["evidence"]["ui_settings_local_defaults_route_focus_enabled"] is True
    assert frontend_arch["evidence"]["ui_settings_structured_api_route_focus_enabled"] is True
    assert (
        frontend_arch["evidence"]["ui_settings_structured_api_focus_context_enabled"]
        is True
    )
    assert frontend_arch["evidence"]["frontend_task_ui_status_extracted"] is True
    assert frontend_arch["evidence"]["frontend_task_queue_status_extracted"] is True
    assert frontend_arch["evidence"]["ui_api_error_operator_guidance_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_queue_operator_hint_enabled"] is True
    assert frontend_arch["evidence"]["frontend_task_failure_status_extracted"] is True
    assert frontend_arch["evidence"]["frontend_external_deployment_status_extracted"] is True
    assert frontend_arch["evidence"]["frontend_data_enrichment_tabs_status_extracted"] is True
    assert frontend_arch["evidence"]["frontend_data_enrichment_runtime_status_extracted"] is True
    assert frontend_arch["evidence"]["ui_operator_data_gap_prefill_enabled"] is True
    assert (
        frontend_arch["evidence"][
            "ui_data_enrichment_pending_operation_button_priority_enabled"
        ]
        is True
    )
    assert (
        frontend_arch["evidence"]["ui_data_enrichment_pending_handoff_banner_enabled"]
        is True
    )
    assert frontend_arch["evidence"]["ui_data_enrichment_operation_readiness_enabled"] is True
    assert (
        frontend_arch["evidence"][
            "ui_data_enrichment_submission_preflight_summary_enabled"
        ]
        is True
    )
    assert frontend_arch["evidence"]["ui_data_enrichment_task_queue_guard_enabled"] is True
    assert (
        frontend_arch["evidence"][
            "ui_data_enrichment_market_submission_confirmation_enabled"
        ]
        is True
    )
    assert frontend_arch["evidence"]["ui_manual_news_import_confirmation_enabled"] is True
    assert (
        frontend_arch["evidence"]["ui_manual_company_filing_import_confirmation_enabled"]
        is True
    )
    assert (
        frontend_arch["evidence"]["ui_company_filing_url_import_confirmation_enabled"]
        is True
    )
    assert frontend_arch["evidence"]["ui_rss_fetch_confirmation_enabled"] is True
    assert (
        frontend_arch["evidence"]["ui_manual_data_ingest_preflight_summary_enabled"]
        is True
    )
    assert frontend_arch["evidence"]["ui_rss_data_ingest_preflight_summary_enabled"] is True
    assert (
        frontend_arch["evidence"]["ui_data_enrichment_allowlist_scope_summary_enabled"]
        is True
    )
    assert (
        frontend_arch["evidence"]["ui_data_enrichment_pending_ticker_allowlist_guard_enabled"]
        is True
    )
    assert frontend_arch["evidence"]["ui_market_cache_operator_summary_enabled"] is True
    assert frontend_arch["evidence"]["frontend_external_deployment_domain_status_extracted"] is True
    assert (
        frontend_arch["evidence"]["frontend_external_deployment_readiness_status_extracted"] is True
    )
    assert frontend_arch["evidence"]["report_html_renderer_extracted"] is True
    assert frontend_arch["evidence"]["ui_status_helpers_extracted"] is True
    assert frontend_arch["evidence"]["ui_maintenance_panels_extracted"] is True
    assert frontend_arch["evidence"]["ui_submission_guard_panel_enabled"] is True
    assert (
        frontend_arch["evidence"]["ui_maintenance_cleanup_confirmation_gate_enabled"]
        is True
    )
    assert frontend_arch["evidence"]["ui_system_settings_tabs_extracted"] is True
    assert (
        frontend_arch["evidence"]["ui_scope_static_whitelist_source_summary_enabled"]
        is True
    )
    assert (
        frontend_arch["evidence"]["ui_schedule_settings_save_confirmation_enabled"]
        is True
    )
    assert frontend_arch["evidence"]["ui_api_client_extracted"] is True
    assert frontend_arch["evidence"]["ui_api_loaders_extracted"] is True
    assert frontend_arch["evidence"]["ui_background_task_client_extracted"] is True
    assert frontend_arch["evidence"]["ui_task_queue_preflight_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_queue_preflight_cache_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_queue_worker_warning_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_queue_submission_smoke_hint_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_queue_health_panel_extracted"] is True
    assert frontend_arch["evidence"]["ui_task_queue_repair_guidance_enabled"] is True
    assert frontend_arch["evidence"]["ui_maintenance_diagnostic_actions_enabled"] is True
    assert frontend_arch["evidence"]["ui_maintenance_diagnostic_confirmation_gate_enabled"] is True
    assert frontend_arch["evidence"]["ui_maintenance_safe_noop_diagnostics_enabled"] is True
    assert frontend_arch["evidence"]["ui_external_deployment_diagnostics_enabled"] is True
    assert frontend_arch["evidence"]["ui_external_deployment_readiness_checklist_enabled"] is True
    assert frontend_arch["evidence"]["ui_external_deployment_operator_summary_enabled"] is True
    assert frontend_arch["evidence"]["ui_external_deployment_profile_catalog_extracted"] is True
    assert frontend_arch["evidence"]["ui_external_deployment_diagnostics_extracted"] is True
    assert frontend_arch["evidence"]["ui_local_dependency_repair_guidance_enabled"] is True
    assert frontend_arch["evidence"]["ui_maintenance_operations_enabled"] is True
    assert frontend_arch["evidence"]["ui_maintenance_operation_confirmation_gate_enabled"] is True
    assert (
        frontend_arch["evidence"][
            "ui_maintenance_post_run_diagnostic_confirmation_gate_enabled"
        ]
        is True
    )
    assert frontend_arch["evidence"]["ui_risky_submission_guard_coverage_enabled"] is True
    assert frontend_arch["evidence"]["ui_risky_submission_guard_missing"] == []
    assert frontend_arch["evidence"]["ui_external_deployment_domain_helpers_extracted"] is True
    assert frontend_arch["evidence"]["ui_task_failure_drilldown_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_failure_recommended_retry_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_observability_auto_expand_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_failure_diagnostics_extracted"] is True
    assert frontend_arch["evidence"]["ui_task_failure_category_display_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_failure_action_routes_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_retry_guard_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_failure_trend_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_failure_alerts_enabled"] is True
    assert frontend_arch["evidence"]["ui_maintenance_task_retry_confirmation_gate_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_status_panel_extracted"] is True
    assert frontend_arch["evidence"]["ui_task_status_poll_backoff_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_status_autorefresh_feedback_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_status_failure_diagnostics_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_status_operation_confirmation_gate_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_status_operation_preflight_summary_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_status_operation_label_inference_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_status_terminal_task_action_guard_enabled"] is True
    assert frontend_arch["evidence"]["ui_llm_quota_panel_extracted"] is True
    assert frontend_arch["evidence"]["ui_report_observability_panel_extracted"] is True
    assert frontend_arch["evidence"]["ui_report_observability_recommendations_enabled"] is True
    assert frontend_arch["evidence"]["ui_report_observability_graphrag_metrics_enabled"] is True
    assert frontend_arch["evidence"]["ui_company_filing_runtime_panel_enabled"] is True
    assert frontend_arch["evidence"]["ui_visual_rag_model_chain_panel_enabled"] is True
    assert frontend_arch["evidence"]["ui_data_enrichment_tabs_extracted"] is True
    assert frontend_arch["evidence"]["task_retry_uses_scoped_state_key"] is True
    assert frontend_arch["evidence"]["ui_report_state_extracted"] is True
    assert frontend_arch["evidence"]["ui_report_panels_extracted"] is True
    assert frontend_arch["evidence"]["ui_report_preview_iframe_renderer_enabled"] is True
    assert frontend_arch["evidence"]["ui_report_follow_up_controls_extracted"] is True
    assert (
        frontend_arch["evidence"]["ui_report_follow_up_submission_confirmation_enabled"]
        is True
    )
    assert (
        frontend_arch["evidence"]["ui_report_follow_up_submission_preflight_summary_enabled"]
        is True
    )
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
