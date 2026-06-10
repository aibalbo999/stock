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
                "FastAPI main is a thin app entry; routers, app assembly, legacy helper exports, "
                "use-case services, and opt-in sync report network refresh wiring live in separate modules."
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
                "Background task implementation readiness covers Celery exports, named task wiring, "
                "status endpoints, structured submission errors, source diagnostics, and persisted "
                "failure diagnostics. Live Redis/Celery runtime readiness is reported separately for "
                "operator repair without turning an offline local dependency into an implementation "
                "failure."
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
            and frontend_status.get("ui_operator_quota_summary_enabled")
            and frontend_status.get("ui_operator_retryable_failure_primary_action_enabled")
            and frontend_status.get("ui_operator_stale_running_primary_action_enabled")
            and frontend_status.get("ui_operator_quota_missing_read_guard_enabled")
            and frontend_status.get("frontend_report_ui_status_extracted")
            and frontend_status.get("frontend_report_rendering_status_extracted")
            and frontend_status.get("frontend_report_workflow_status_extracted")
            and frontend_status.get("ui_report_lifecycle_data_gap_prefill_enabled")
            and frontend_status.get("ui_report_health_identity_enabled")
            and frontend_status.get("ui_report_health_action_enabled")
            and frontend_status.get("ui_report_quality_unknown_guard_enabled")
            and frontend_status.get("ui_report_latest_only_picker_enabled")
            and frontend_status.get("ui_report_advanced_controls_progressive_disclosure_enabled")
            and frontend_status.get("frontend_task_ui_status_extracted")
            and frontend_status.get("frontend_task_queue_status_extracted")
            and frontend_status.get("frontend_task_failure_status_extracted")
            and frontend_status.get("frontend_data_enrichment_status_extracted")
            and frontend_status.get("frontend_data_enrichment_tabs_status_extracted")
            and frontend_status.get("frontend_data_enrichment_runtime_status_extracted")
            and frontend_status.get("ui_operator_data_gap_prefill_enabled")
            and frontend_status.get("ui_data_enrichment_pending_operation_button_priority_enabled")
            and frontend_status.get("ui_data_enrichment_operation_readiness_enabled")
            and frontend_status.get("ui_data_enrichment_task_queue_guard_enabled")
            and frontend_status.get("ui_market_cache_operator_summary_enabled")
            and frontend_status.get("frontend_settings_ui_status_extracted")
            and frontend_status.get("frontend_settings_core_status_extracted")
            and frontend_status.get("frontend_maintenance_ui_status_extracted")
            and frontend_status.get("ui_incident_action_labels_enabled")
            and frontend_status.get("ui_settings_ai_quota_route_focus_enabled")
            and frontend_status.get("ui_settings_task_route_focus_enabled")
            and frontend_status.get("frontend_external_deployment_domain_status_extracted")
            and frontend_status.get("frontend_external_deployment_readiness_status_extracted")
            and frontend_status.get("frontend_runtime_identity_marker_enabled")
            and frontend_status.get("frontend_smoke_checks_runtime_identity_marker")
            and frontend_status.get("external_css_loaded")
            and frontend_status.get("external_report_css_loaded")
            and frontend_status.get("report_html_renderer_extracted")
            and frontend_status.get("ui_status_helpers_extracted")
            and frontend_status.get("ui_maintenance_panels_extracted")
            and frontend_status.get("ui_system_settings_tabs_extracted")
            and frontend_status.get("ui_api_client_extracted")
            and frontend_status.get("ui_api_loaders_extracted")
            and frontend_status.get("ui_background_task_client_extracted")
            and frontend_status.get("ui_task_queue_preflight_enabled")
            and frontend_status.get("ui_task_queue_preflight_cache_enabled")
            and frontend_status.get("ui_task_queue_worker_warning_enabled")
            and frontend_status.get("ui_task_queue_submission_smoke_hint_enabled")
            and frontend_status.get("ui_task_queue_health_panel_extracted")
            and frontend_status.get("ui_task_queue_repair_guidance_enabled")
            and frontend_status.get("ui_maintenance_diagnostic_actions_enabled")
            and frontend_status.get("ui_maintenance_safe_noop_diagnostics_enabled")
            and frontend_status.get("ui_external_deployment_diagnostics_enabled")
            and frontend_status.get("ui_external_deployment_readiness_checklist_enabled")
            and frontend_status.get("ui_external_deployment_diagnostics_extracted")
            and frontend_status.get("ui_local_dependency_repair_guidance_enabled")
            and frontend_status.get("ui_maintenance_operations_enabled")
            and frontend_status.get("ui_external_deployment_domain_helpers_extracted")
            and frontend_status.get("ui_task_failure_drilldown_enabled")
            and frontend_status.get("ui_task_failure_recommended_retry_enabled")
            and frontend_status.get("ui_task_observability_auto_expand_enabled")
            and frontend_status.get("ui_task_failure_diagnostics_extracted")
            and frontend_status.get("ui_task_failure_category_display_enabled")
            and frontend_status.get("ui_task_failure_trend_enabled")
            and frontend_status.get("ui_task_failure_alerts_enabled")
            and frontend_status.get("ui_task_status_panel_extracted")
            and frontend_status.get("ui_task_status_poll_backoff_enabled")
            and frontend_status.get("ui_task_status_autorefresh_feedback_enabled")
            and frontend_status.get("ui_task_status_failure_diagnostics_enabled")
            and frontend_status.get("ui_task_execution_context_enabled")
            and frontend_status.get("ui_llm_quota_panel_extracted")
            and frontend_status.get("ui_report_observability_panel_extracted")
            and frontend_status.get("ui_company_filing_runtime_panel_enabled")
            and frontend_status.get("ui_visual_rag_model_chain_panel_enabled")
            and frontend_status.get("ui_data_enrichment_tabs_extracted")
            and frontend_status.get("task_retry_uses_scoped_state_key")
            and frontend_status.get("ui_report_state_extracted")
            and frontend_status.get("ui_report_panels_extracted")
            and frontend_status.get("ui_report_follow_up_controls_extracted")
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
                "Streamlit uses a multi-page shell, explicit page imports, external CSS, "
                "extracted API/task/report helpers, and FastAPI/Celery task enqueue/status "
                "polling, frontend/API runtime identity smoke checks, queue health diagnostics, "
                "allowlisted maintenance diagnostic "
                "actions including safe no-op submission smoke, confirmed local dependency "
                "operations, categorized failed-task retry drilldown, and safe task execution "
                "context summaries instead of running long ingestion/report calls inline."
            ),
        ),
        "python_runtime": _capability(
            "ready"
            if python_runtime_status.get("current_runtime_supported")
            and python_runtime_status.get("project_targets_aligned")
            else "degraded",
            evidence=python_runtime_status,
            detail=(
                "Runtime preflight compares the active Python interpreter with the "
                "project's Python 3.11+ target declared in pyproject, .python-version, CI, and Docker."
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
            detail="Alembic is present; current DB may still need upgrade/stamp when up_to_date=false.",
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
                "Secret scanning prefers external tools such as detect-secrets/gitleaks, "
                "runs through a pre-commit gate, and only treats local regex as a degraded fallback."
            ),
        ),
    }
