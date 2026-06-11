from __future__ import annotations

from app.services.status_capability_helpers import capability as _capability


def architecture_capabilities(
    *,
    api_status: dict,
    workflow_status: dict,
    task_queue_status: dict,
    frontend_status: dict,
    python_runtime_status: dict,
    database_status: dict,
    migration_status: dict,
    security_scan_status: dict,
) -> dict:
    background_task_submission_ready = bool(
        api_status.get("background_task_submission_handlers_extracted")
        or api_status.get("operation_task_submission_handlers_extracted")
    )
    background_task_control_ready = bool(
        api_status.get("background_task_control_handlers_extracted")
    )
    background_task_queue_implementation_ready = bool(
        task_queue_status.get("submission_contract_ready")
        and task_queue_status.get("task_queue_source_diagnostics_extracted")
        and task_queue_status.get("task_async_bridge_guard_present")
        and task_queue_status.get("app_asyncio_run_policy_ready")
        and task_queue_status.get("compose_runtime_env_passthrough_ready")
        and api_status.get("structured_task_submission_errors")
        and background_task_submission_ready
        and background_task_control_ready
        and api_status.get("task_failure_diagnostics_shared_service")
        and api_status.get("task_failure_diagnostics_persisted_to_run_payload")
    )
    background_task_queue_runtime_ready = bool(task_queue_status.get("ready"))
    return {
        "thin_api_controller": _capability(
            "ready"
            if (api_status.get("main_py_lines") or 10_000) <= 220
            and api_status.get("api_source_context_extracted")
            and api_status["route_module_count"] >= 7
            and api_status.get("app_factory_present")
            and api_status.get("main_uses_app_factory")
            and api_status.get("api_service_factory_architecture_status_extracted")
            and api_status.get("api_compatibility_architecture_status_extracted")
            and api_status.get("compatibility_exports_present")
            and api_status.get("main_uses_compatibility_exports")
            and api_status.get("compatibility_export_domain_builders_extracted")
            and api_status.get("compatibility_helpers_present")
            and api_status.get("main_uses_compatibility_helpers")
            and api_status.get("compatibility_helper_domain_builders_extracted")
            and api_status.get("compatibility_service_present")
            and api_status.get("api_runtime_present")
            and api_status.get("main_uses_api_runtime")
            and api_status.get("api_tasking_architecture_status_extracted")
            and api_status.get("task_uses_api_runtime")
            and api_status.get("task_exports_present")
            and api_status.get("api_runtime_uses_task_exports")
            and not api_status.get("task_imports_api_main")
            and not api_status.get("compatibility_exports_imports_tasks")
            and api_status.get("main_direct_domain_import_count") == 0
            and api_status.get("structured_task_submission_errors")
            and background_task_submission_ready
            and background_task_control_ready
            and api_status.get("sync_report_network_refresh_opt_in")
            and api_status.get("sync_report_background_task_hint_present")
            and api_status.get("report_service_factory_extracted")
            and api_status.get("data_service_factory_extracted")
            and api_status.get("workflow_service_factory_extracted")
            and api_status.get("ai_graph_service_factory_extracted")
            and api_status.get("compatibility_service_domain_mixins_extracted")
            and not api_status.get("main_imports_legacy_facade")
            and api_status.get("legacy_facade_api_reference_count") == 0
            else "degraded",
            evidence=api_status,
            detail=(
                "FastAPI main 只保留薄入口；router、app 組裝、legacy helper export、"
                "use-case service，以及同步報告網路刷新 opt-in wiring 都已拆到獨立模組。"
            ),
        ),
        "workflow_orchestration": _capability(
            "ready" if workflow_status.get("ready") else "degraded",
            evidence={
                "engine": workflow_status.get("engine"),
                "mode": workflow_status.get("mode"),
                "checkpoint_store": workflow_status.get("checkpoint_store"),
                "local_fallback_enabled": workflow_status.get("local_fallback_enabled"),
                "fallback_reason": workflow_status.get("fallback_reason"),
            },
        ),
        "background_task_queue": _capability(
            "ready"
            if background_task_queue_implementation_ready
            else "degraded",
            evidence={
                "implementation_ready": background_task_queue_implementation_ready,
                "runtime_ready": background_task_queue_runtime_ready,
                "ready": task_queue_status.get("ready"),
                "submission_contract_ready": task_queue_status.get("submission_contract_ready"),
                "broker_configured": task_queue_status.get("broker_configured"),
                "broker_ok": task_queue_status.get("broker_ok"),
                "backend_ok": task_queue_status.get("backend_ok"),
                "celery_app_available": task_queue_status.get("celery_app_available"),
                "processing_ready": task_queue_status.get("processing_ready"),
                "worker_ping_checked": task_queue_status.get("worker_ping_checked"),
                "worker_online": task_queue_status.get("worker_online"),
                "worker_count": task_queue_status.get("worker_count"),
                "worker_nodes": task_queue_status.get("worker_nodes"),
                "worker_ping_error": task_queue_status.get("worker_ping_error"),
                "worker_ping_skipped_reason": task_queue_status.get("worker_ping_skipped_reason"),
                "required_task_exports": task_queue_status.get("required_task_exports"),
                "exported_tasks_present": task_queue_status.get("exported_tasks_present"),
                "missing_task_exports": task_queue_status.get("missing_task_exports"),
                "task_names_match_expected": task_queue_status.get("task_names_match_expected"),
                "task_queue_source_diagnostics_extracted": task_queue_status.get(
                    "task_queue_source_diagnostics_extracted"
                ),
                "task_queue_source_diagnostics_path": task_queue_status.get(
                    "task_queue_source_diagnostics_path"
                ),
                "task_async_bridge_guard_present": task_queue_status.get(
                    "task_async_bridge_guard_present"
                ),
                "task_async_bridge": task_queue_status.get("task_async_bridge"),
                "app_asyncio_run_policy_ready": task_queue_status.get(
                    "app_asyncio_run_policy_ready"
                ),
                "app_asyncio_run_policy": task_queue_status.get("app_asyncio_run_policy"),
                "compose_runtime_env_passthrough_ready": task_queue_status.get(
                    "compose_runtime_env_passthrough_ready"
                ),
                "compose_runtime_env": task_queue_status.get("compose_runtime_env"),
                "submission_endpoints": task_queue_status.get("submission_endpoints"),
                "status_endpoints": task_queue_status.get("status_endpoints"),
                "structured_task_submission_errors": api_status.get(
                    "structured_task_submission_errors"
                ),
                "background_task_submission_handlers_extracted": api_status.get(
                    "background_task_submission_handlers_extracted"
                ),
                "background_task_submission_helper_path": api_status.get(
                    "background_task_submission_helper_path"
                ),
                "background_task_control_handlers_extracted": api_status.get(
                    "background_task_control_handlers_extracted"
                ),
                "background_task_control_endpoint_coverage": api_status.get(
                    "background_task_control_endpoint_coverage"
                ),
                "operation_task_submission_handlers_extracted": api_status.get(
                    "operation_task_submission_handlers_extracted"
                ),
                "operation_task_submission_helper_path": api_status.get(
                    "operation_task_submission_helper_path"
                ),
                "task_failure_diagnostics_shared_service": api_status.get(
                    "task_failure_diagnostics_shared_service"
                ),
                "task_failure_diagnostics_persisted_to_run_payload": api_status.get(
                    "task_failure_diagnostics_persisted_to_run_payload"
                ),
                "smoke_commands": task_queue_status.get("smoke_commands"),
                "runtime_repair_plan": task_queue_status.get("repair_plan"),
            },
            detail=(
                "背景任務實作就緒檢查涵蓋 Celery export、具名 task wiring、狀態端點、"
                "結構化送出錯誤、來源診斷與持久化失敗診斷。Live Redis/Celery runtime "
                "就緒度會分開回報，讓操作者修復 runtime，而不把離線本機依賴誤判成實作失敗。"
            ),
        ),
        "streamlit_mpa_background_tasks": _capability(
            "ready"
            if frontend_status.get("streamlit_entry_uses_navigation")
            and int(frontend_status.get("page_count") or 0) >= 4
            and frontend_status.get("expected_pages_present")
            and frontend_status.get("streamlit_page_import_contract_ready")
            and frontend_status.get("frontend_source_context_extracted")
            and frontend_status.get("frontend_runtime_status_extracted")
            and frontend_status.get("frontend_operator_workbench_status_extracted")
            and frontend_status.get("ui_analysis_workspace_presenter_extracted")
            and frontend_status.get("ui_analysis_submission_quota_confirmation_enabled")
            and frontend_status.get("ui_analysis_submission_preflight_summary_enabled")
            and frontend_status.get("ui_data_task_followup_summary_enabled")
            and frontend_status.get(
                "ui_data_task_followup_failure_operator_guidance_enabled"
            )
            and frontend_status.get("ui_operator_quota_summary_enabled")
            and frontend_status.get("ui_operator_quota_step_caption_enabled")
            and frontend_status.get("ui_operator_task_state_helpers_extracted")
            and frontend_status.get("ui_operator_retryable_failure_primary_action_enabled")
            and frontend_status.get("ui_operator_stale_running_primary_action_enabled")
            and frontend_status.get("ui_operator_quota_missing_read_guard_enabled")
            and frontend_status.get("ui_operator_market_freshness_primary_action_enabled")
            and frontend_status.get("ui_operator_secondary_action_labels_enabled")
            and frontend_status.get("ui_operator_source_labels_enabled")
            and frontend_status.get("ui_operator_local_defaults_secondary_action_enabled")
            and frontend_status.get("ui_operator_free_validation_secondary_action_enabled")
            and frontend_status.get("ui_operator_service_status_unknown_guard_enabled")
            and frontend_status.get("ui_operator_task_summary_unknown_guard_enabled")
            and frontend_status.get("ui_operator_running_task_overall_message_enabled")
            and frontend_status.get("ui_operator_running_task_primary_action_enabled")
            and frontend_status.get("ui_operator_running_task_report_card_enabled")
            and frontend_status.get("ui_operator_running_task_pending_card_enabled")
            and frontend_status.get("ui_operator_running_task_queue_card_enabled")
            and frontend_status.get(
                "ui_operator_historical_failure_secondary_when_latest_task_healthy_enabled"
            )
            and frontend_status.get(
                "ui_operator_overall_historical_failure_ready_when_latest_task_healthy_enabled"
            )
            and frontend_status.get(
                "ui_operator_missing_report_prioritized_before_historical_failure_enabled"
            )
            and frontend_status.get("ui_operator_latest_failure_overall_message_enabled")
            and frontend_status.get(
                "ui_operator_card_historical_failure_trackable_when_latest_task_healthy_enabled"
            )
            and frontend_status.get("frontend_report_ui_status_extracted")
            and frontend_status.get("frontend_report_rendering_status_extracted")
            and frontend_status.get("frontend_report_workflow_status_extracted")
            and frontend_status.get("ui_report_center_presenter_extracted")
            and frontend_status.get("ui_report_lifecycle_data_gap_prefill_enabled")
            and frontend_status.get("ui_report_health_identity_enabled")
            and frontend_status.get("ui_report_health_action_enabled")
            and frontend_status.get("ui_report_reader_decision_summary_enabled")
            and frontend_status.get("ui_report_quality_unknown_guard_enabled")
            and frontend_status.get("ui_report_market_freshness_action_enabled")
            and frontend_status.get("ui_report_latest_only_picker_enabled")
            and frontend_status.get("ui_report_empty_create_analysis_action_enabled")
            and frontend_status.get("ui_report_empty_running_task_state_enabled")
            and frontend_status.get("ui_run_delete_confirmation_gate_enabled")
            and frontend_status.get("ui_report_delete_scope_caption_enabled")
            and frontend_status.get("ui_report_advanced_controls_progressive_disclosure_enabled")
            and frontend_status.get("ui_report_run_history_operator_labels_enabled")
            and frontend_status.get("ui_report_run_detail_error_operator_label_enabled")
            and frontend_status.get("frontend_task_ui_status_extracted")
            and frontend_status.get("frontend_task_queue_status_extracted")
            and frontend_status.get("frontend_task_failure_status_extracted")
            and frontend_status.get("frontend_data_enrichment_status_extracted")
            and frontend_status.get("frontend_data_enrichment_tabs_status_extracted")
            and frontend_status.get("frontend_data_enrichment_runtime_status_extracted")
            and frontend_status.get("ui_data_enrichment_market_presenter_extracted")
            and frontend_status.get("ui_data_enrichment_manual_presenter_extracted")
            and frontend_status.get("ui_operator_data_gap_prefill_enabled")
            and frontend_status.get("ui_data_enrichment_pending_operation_button_priority_enabled")
            and frontend_status.get("ui_data_enrichment_pending_handoff_banner_enabled")
            and frontend_status.get("ui_data_enrichment_operation_readiness_enabled")
            and frontend_status.get(
                "ui_data_enrichment_submission_preflight_summary_enabled"
            )
            and frontend_status.get("ui_data_enrichment_task_queue_guard_enabled")
            and frontend_status.get("ui_data_enrichment_market_submission_confirmation_enabled")
            and frontend_status.get("ui_manual_news_import_confirmation_enabled")
            and frontend_status.get("ui_manual_company_filing_import_confirmation_enabled")
            and frontend_status.get("ui_company_filing_url_import_confirmation_enabled")
            and frontend_status.get("ui_rss_fetch_confirmation_enabled")
            and frontend_status.get("ui_manual_data_ingest_preflight_summary_enabled")
            and frontend_status.get("ui_rss_data_ingest_preflight_summary_enabled")
            and frontend_status.get("ui_data_enrichment_allowlist_scope_summary_enabled")
            and frontend_status.get("ui_data_enrichment_pending_ticker_allowlist_guard_enabled")
            and frontend_status.get("ui_market_cache_operator_summary_enabled")
            and frontend_status.get("frontend_settings_ui_status_extracted")
            and frontend_status.get("frontend_settings_core_status_extracted")
            and frontend_status.get("frontend_maintenance_ui_status_extracted")
            and frontend_status.get("ui_incident_action_labels_enabled")
            and frontend_status.get("ui_incident_report_lifecycle_enabled")
            and frontend_status.get("ui_incident_priority_summary_enabled")
            and frontend_status.get("ui_incident_historical_context_enabled")
            and frontend_status.get("ui_incident_header_current_context_enabled")
            and frontend_status.get("ui_incident_grouped_summary_enabled")
            and frontend_status.get("ui_incident_grouped_action_controls_enabled")
            and frontend_status.get("ui_incident_route_captions_enabled")
            and frontend_status.get("ui_optimization_progress_operator_summary_enabled")
            and frontend_status.get("ui_optimization_progress_metric_labels_enabled")
            and frontend_status.get("ui_optimization_progress_next_action_labels_enabled")
            and frontend_status.get("ui_optimization_progress_compact_action_rows_enabled")
            and frontend_status.get(
                "ui_optimization_progress_paid_external_only_summary_enabled"
            )
            and frontend_status.get(
                "ui_optimization_progress_paid_external_free_validation_summary_enabled"
            )
            and frontend_status.get("ui_optimization_progress_scope_summary_enabled")
            and frontend_status.get("ui_settings_ai_quota_route_focus_enabled")
            and frontend_status.get("ui_settings_task_route_focus_enabled")
            and frontend_status.get("ui_settings_local_defaults_route_focus_enabled")
            and frontend_status.get("ui_settings_structured_api_route_focus_enabled")
            and frontend_status.get("ui_settings_structured_api_focus_context_enabled")
            and frontend_status.get("frontend_external_deployment_domain_status_extracted")
            and frontend_status.get("frontend_external_deployment_readiness_status_extracted")
            and frontend_status.get("frontend_runtime_identity_marker_enabled")
            and frontend_status.get("frontend_smoke_checks_runtime_identity_marker")
            and frontend_status.get("external_css_loaded")
            and frontend_status.get("external_report_css_loaded")
            and frontend_status.get("report_html_renderer_extracted")
            and frontend_status.get("ui_status_helpers_extracted")
            and frontend_status.get("ui_maintenance_panels_extracted")
            and frontend_status.get("ui_submission_guard_panel_enabled")
            and frontend_status.get("ui_maintenance_overview_metric_operator_labels_enabled")
            and frontend_status.get("ui_maintenance_cleanup_confirmation_gate_enabled")
            and frontend_status.get("ui_system_settings_tabs_extracted")
            and frontend_status.get("ui_scope_static_whitelist_source_summary_enabled")
            and frontend_status.get("ui_schedule_settings_save_confirmation_enabled")
            and frontend_status.get("ui_api_client_extracted")
            and frontend_status.get("ui_api_loaders_extracted")
            and frontend_status.get("ui_background_task_client_extracted")
            and frontend_status.get("ui_api_error_operator_guidance_enabled")
            and frontend_status.get("ui_task_queue_preflight_enabled")
            and frontend_status.get("ui_task_queue_preflight_cache_enabled")
            and frontend_status.get("ui_task_queue_worker_warning_enabled")
            and frontend_status.get("ui_task_queue_submission_smoke_hint_enabled")
            and frontend_status.get("ui_task_queue_operator_hint_enabled")
            and frontend_status.get("ui_task_queue_health_panel_extracted")
            and frontend_status.get("ui_task_queue_health_operator_labels_enabled")
            and frontend_status.get("ui_task_queue_repair_guidance_enabled")
            and frontend_status.get("ui_maintenance_diagnostic_actions_enabled")
            and frontend_status.get("ui_maintenance_diagnostic_action_operator_labels_enabled")
            and frontend_status.get("ui_maintenance_diagnostic_effect_operator_labels_enabled")
            and frontend_status.get("ui_maintenance_diagnostic_confirmation_gate_enabled")
            and frontend_status.get("ui_maintenance_safe_noop_diagnostics_enabled")
            and frontend_status.get("ui_external_deployment_diagnostics_enabled")
            and frontend_status.get("ui_external_deployment_readiness_checklist_enabled")
            and frontend_status.get("ui_external_deployment_operator_summary_enabled")
            and frontend_status.get("ui_external_deployment_diagnostics_extracted")
            and frontend_status.get("ui_local_dependency_repair_guidance_enabled")
            and frontend_status.get("ui_maintenance_operations_enabled")
            and frontend_status.get("ui_maintenance_operation_rows_operator_labels_enabled")
            and frontend_status.get("ui_maintenance_operation_confirmation_gate_enabled")
            and frontend_status.get(
                "ui_maintenance_post_run_diagnostic_confirmation_gate_enabled"
            )
            and frontend_status.get("ui_risky_submission_guard_coverage_enabled")
            and frontend_status.get("ui_external_deployment_domain_helpers_extracted")
            and frontend_status.get("ui_structured_filing_api_operation_operator_labels_enabled")
            and frontend_status.get("ui_structured_filing_api_free_validation_steps_enabled")
            and frontend_status.get("ui_structured_filing_api_free_validation_code_block_enabled")
            and frontend_status.get("ui_unlocker_operation_operator_labels_enabled")
            and frontend_status.get("ui_neo4j_operation_operator_labels_enabled")
            and frontend_status.get("ui_task_failure_drilldown_enabled")
            and frontend_status.get("ui_task_failure_recommended_retry_enabled")
            and frontend_status.get("ui_task_observability_auto_expand_enabled")
            and frontend_status.get("ui_task_failure_diagnostics_extracted")
            and frontend_status.get("ui_task_failure_category_display_enabled")
            and frontend_status.get("ui_task_failure_operator_labels_enabled")
            and frontend_status.get("ui_task_observability_summary_operator_labels_enabled")
            and frontend_status.get("ui_task_observability_alert_operator_guidance_enabled")
            and frontend_status.get("ui_task_observability_alert_queue_operator_labels_enabled")
            and frontend_status.get("ui_task_failure_trend_enabled")
            and frontend_status.get("ui_task_failure_alerts_enabled")
            and frontend_status.get("ui_maintenance_task_retry_confirmation_gate_enabled")
            and frontend_status.get("ui_task_status_panel_extracted")
            and frontend_status.get("ui_task_status_presenter_extracted")
            and frontend_status.get("ui_task_status_poll_backoff_enabled")
            and frontend_status.get("ui_task_status_autorefresh_feedback_enabled")
            and frontend_status.get("ui_task_status_failure_diagnostics_enabled")
            and frontend_status.get("ui_task_status_operation_confirmation_gate_enabled")
            and frontend_status.get("ui_task_status_operation_preflight_summary_enabled")
            and frontend_status.get("ui_task_status_operation_label_inference_enabled")
            and frontend_status.get("ui_task_status_operator_context_labels_enabled")
            and frontend_status.get("ui_task_status_metric_operator_labels_enabled")
            and frontend_status.get("ui_task_status_terminal_task_action_guard_enabled")
            and frontend_status.get("ui_task_execution_context_enabled")
            and frontend_status.get("ui_llm_quota_panel_extracted")
            and frontend_status.get("ui_llm_quota_model_row_operator_labels_enabled")
            and frontend_status.get("ui_llm_quota_caption_operator_labels_enabled")
            and frontend_status.get("ui_llm_usage_routing_operator_labels_enabled")
            and frontend_status.get("ui_llm_usage_alert_operator_labels_enabled")
            and frontend_status.get("ui_llm_usage_summary_row_operator_labels_enabled")
            and frontend_status.get("ui_report_observability_panel_extracted")
            and frontend_status.get("ui_report_observability_metric_operator_labels_enabled")
            and frontend_status.get("ui_report_observability_row_operator_labels_enabled")
            and frontend_status.get("ui_report_observability_alert_operator_messages_enabled")
            and frontend_status.get(
                "ui_report_observability_recommendation_operator_text_enabled"
            )
            and frontend_status.get("ui_company_filing_runtime_panel_enabled")
            and frontend_status.get("ui_visual_rag_model_chain_panel_enabled")
            and frontend_status.get("ui_data_enrichment_tabs_extracted")
            and frontend_status.get("task_retry_uses_scoped_state_key")
            and frontend_status.get("ui_report_state_extracted")
            and frontend_status.get("ui_report_panels_extracted")
            and frontend_status.get("ui_report_preview_iframe_renderer_enabled")
            and frontend_status.get("ui_report_follow_up_controls_extracted")
            and frontend_status.get("ui_report_follow_up_submission_confirmation_enabled")
            and frontend_status.get("ui_report_follow_up_submission_preflight_summary_enabled")
            and frontend_status.get("ui_report_follow_up_action_operator_labels_enabled")
            and frontend_status.get("ui_report_markdown_helpers_extracted")
            and frontend_status.get("ui_report_candidate_audit_extracted")
            and frontend_status.get("ui_report_formatters_extracted")
            and frontend_status.get("ui_report_sections_extracted")
            and frontend_status.get("ui_wildcard_imports_removed")
            and frontend_status.get("uses_task_enqueue_helper")
            and frontend_status.get("uses_background_task_submit_helper")
            and frontend_status.get("uses_task_queue_preflight")
            and frontend_status.get("uses_task_status_panel")
            and frontend_status.get("asyncio_run_count") == 0
            and not frontend_status.get("long_blocking_post_timeout_present")
            and not frontend_status.get("sync_report_generate_used")
            else "degraded",
            evidence=frontend_status,
            detail=(
                "Streamlit 已採多頁 shell、明確 page import、外部 CSS、抽出的 API/task/report helper，"
                "並透過 FastAPI/Celery 送出任務與輪詢狀態；另有前端/API runtime identity smoke、"
                "佇列健康診斷、allowlist 維護診斷動作（含安全空跑送出）、已確認的本機依賴操作、"
                "分類失敗任務重試 drilldown，以及安全任務執行脈絡摘要，避免在前端 inline 執行長時間 ingestion/report 呼叫。"
            ),
        ),
        "python_runtime": _capability(
            "ready"
            if python_runtime_status.get("current_runtime_supported")
            and python_runtime_status.get("project_targets_aligned")
            else "degraded",
            evidence=python_runtime_status,
            detail=(
                "Runtime preflight 會比對目前 Python interpreter 是否符合 pyproject、"
                ".python-version、CI 與 Docker 宣告的 Python 3.11+ 目標。"
            ),
        ),
        "database_migrations": _capability(
            "ready"
            if migration_status.get("ok")
            and migration_status.get("head_revision")
            and migration_status.get("up_to_date")
            else "degraded",
            evidence={
                "init_mode": database_status.get("init_mode"),
                "head_revision": migration_status.get("head_revision"),
                "current_revision": migration_status.get("current_revision"),
                "up_to_date": migration_status.get("up_to_date"),
                "version_table_present": migration_status.get("version_table_present"),
            },
            detail="Alembic 已存在；若 up_to_date=false，目前資料庫可能仍需 upgrade 或 stamp。",
        ),
        "secret_scanning": _capability(
            "ready"
            if security_scan_status.get("external_engine_integration")
            and security_scan_status.get("external_engine_available")
            and security_scan_status.get("default_engine_external")
            and security_scan_status.get("detect_secrets_dependency_declared")
            and security_scan_status.get("external_engine_structured_findings")
            and security_scan_status.get("gitleaks_json_report_supported")
            and security_scan_status.get("local_regex_fallback_enabled")
            and security_scan_status.get("pre_commit_dependency_declared")
            and security_scan_status.get("pre_commit_secret_scan_gate_ready")
            else "degraded",
            evidence=security_scan_status,
            detail=(
                "密鑰掃描優先使用 detect-secrets/gitleaks 等外部工具，並透過 pre-commit gate 執行；"
                "本機 regex 只作為 degraded fallback。"
            ),
        ),
    }
