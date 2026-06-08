from __future__ import annotations

from app.services.status_api_architecture_sources import ApiArchitectureSourceContext


def api_tasking_architecture_status(source_context: ApiArchitectureSourceContext) -> dict:
    sources = source_context.sources
    report_generation_api_source = sources["report_generation_api"]
    report_service_factory_source = sources["report_service_factory"]
    sync_report_blocking_async_refresh_calls = (
        "return asyncio.run(self.ingestion_pipeline_cls().pre_report_refresh(request))"
        in report_generation_api_source
        or "market_summary = asyncio.run(" in report_generation_api_source
        or "run_async_from_sync(" in report_generation_api_source
    )
    sync_report_async_bridge_guard_present = (
        "from app.core.async_bridge import run_async_from_sync" in report_generation_api_source
        and 'operation="sync_report.pre_report_refresh"' in report_generation_api_source
        and 'operation="sync_report.refresh_market_quality_recovery"'
        in report_generation_api_source
    )
    sync_report_async_refresh_gates_present = (
        "sync_pre_refresh_requested=sync_pre_refresh_enabled"
        in report_service_factory_source
        and "sync_quality_recovery_requested=sync_quality_recovery_enabled"
        in report_service_factory_source
    )
    sync_report_background_hint_present = (
        '"background_task_endpoint": "POST /reports/generate_async"'
        in report_generation_api_source
        and '"data_operation_endpoint": "POST /tasks/data-operation"'
        in report_generation_api_source
    )
    sync_report_refresh_defaults_disabled = (
        "sync_report_pre_refresh_enabled: bool = False" in sources["config"]
        and "sync_report_quality_recovery_enabled: bool = False" in sources["config"]
    )
    return {
        "api_tasking_architecture_status_extracted": True,
        "api_tasking_architecture_status_path": (
            "app/services/status_api_architecture_tasking.py"
        ),
        "task_uses_api_runtime": "get_task_api_services" in sources["tasks"],
        "task_imports_api_main": "app.api.main" in sources["tasks"],
        "task_exports_present": source_context.paths["task_exports"].exists(),
        "api_runtime_uses_task_exports": "task_export_namespace" in sources["runtime"],
        "compatibility_exports_imports_tasks": "from app.tasks." in (
            sources["compatibility_exports"]
        ),
        **_task_submission_error_status(source_context),
        **_sync_report_refresh_status(
            source_context,
            sync_report_blocking_async_refresh_calls,
            sync_report_async_bridge_guard_present,
            sync_report_async_refresh_gates_present,
            sync_report_refresh_defaults_disabled,
            sync_report_background_hint_present,
        ),
    }


def _task_submission_error_status(source_context: ApiArchitectureSourceContext) -> dict:
    paths = source_context.paths
    sources = source_context.sources
    operations_routes_source = sources["operations_routes"]
    background_task_submission_source = sources["background_task_submission"]
    report_routes_source = sources["report_routes"]
    error_details_source = sources["error_details"]
    task_submission_errors_source = sources["task_submission_errors"]
    run_task_api_source = sources["run_task_api"]
    persistence_source = sources["persistence"]
    task_failure_diagnostics_source = sources["task_failure_diagnostics"]
    background_task_submission_handlers_extracted = (
        paths["background_task_submission"].exists()
        and "def submit_generate_report_task(" in background_task_submission_source
        and "def submit_discovered_report_task(" in background_task_submission_source
        and "def submit_data_operation_task(" in background_task_submission_source
        and "def submit_report_follow_up_task(" in background_task_submission_source
        and "data_operation_error_context(" in background_task_submission_source
        and "submit_generate_report_task(" in operations_routes_source
        and "submit_discovered_report_task(" in operations_routes_source
        and "submit_data_operation_task(" in operations_routes_source
        and "submit_report_follow_up_task(" in report_routes_source
        and "raise_task_submission_failed(" not in operations_routes_source
        and "raise_task_submission_failed(" not in report_routes_source
    )
    background_task_control_handlers_extracted = (
        "def get_background_task_status(" in background_task_submission_source
        and "def cancel_background_task(" in background_task_submission_source
        and "def retry_background_task(" in background_task_submission_source
        and "get_background_task_status(" in operations_routes_source
        and "cancel_background_task(" in operations_routes_source
        and "retry_background_task(" in operations_routes_source
        and "raise_task_queue_unavailable(" not in operations_routes_source
    )
    return {
        "structured_task_submission_errors": (
            "def task_submission_failed_detail(" in error_details_source
            and "def raise_task_submission_failed(" in task_submission_errors_source
            and "def raise_task_queue_unavailable(" in task_submission_errors_source
            and task_submission_errors_source.count("task_submission_failed_detail(") >= 1
            and task_submission_errors_source.count("task_queue_unavailable_detail(") >= 1
            and background_task_submission_source.count("raise_task_submission_failed(") >= 4
            and "background_task_submission_failed" in error_details_source
        ),
        "background_task_submission_handlers_extracted": (
            background_task_submission_handlers_extracted
        ),
        "background_task_control_handlers_extracted": (
            background_task_control_handlers_extracted
        ),
        "background_task_submission_helper_path": "app/api/background_task_submission.py",
        "operation_task_submission_handlers_extracted": (
            background_task_submission_handlers_extracted
        ),
        "operation_task_submission_helper_path": "app/api/background_task_submission.py",
        "task_submission_error_detail_path": "app/api/error_details.py",
        "task_submission_error_helper_path": "app/api/task_submission_errors.py",
        "task_failure_diagnostics_shared_service": paths[
            "task_failure_diagnostics"
        ].exists()
        and "def task_failure_diagnostic_payload(" in task_failure_diagnostics_source
        and "def task_failure_diagnostic(" in task_failure_diagnostics_source
        and "from app.services.task_failure_diagnostics import (" in run_task_api_source,
        "task_failure_diagnostics_persisted_to_run_payload": (
            "task_failure_diagnostic_payload" in persistence_source
            and '"task_failure_diagnostic"' in persistence_source
            and "def _clear_task_failure_diagnostic(" in persistence_source
        ),
        "task_submission_error_endpoint_coverage": {
            "generate_report_async": 'operation="generate_report"'
            in background_task_submission_source
            and "submit_generate_report_task(" in operations_routes_source,
            "run_discovered_async": 'operation="run_discovered"'
            in background_task_submission_source
            and "submit_discovered_report_task(" in operations_routes_source,
            "data_operation": "payload.operation" in operations_routes_source
            and "submit_data_operation_task(" in operations_routes_source,
            "report_follow_up": 'operation="report_follow_up"'
            in background_task_submission_source
            and "submit_report_follow_up_task(" in report_routes_source,
        },
        "background_task_control_endpoint_coverage": {
            "task_status": 'operation="task_status"' in background_task_submission_source
            and "get_background_task_status(" in operations_routes_source,
            "task_cancel": 'operation="task_cancel"' in background_task_submission_source
            and "cancel_background_task(" in operations_routes_source,
            "task_retry": 'operation="task_retry"' in background_task_submission_source
            and "retry_background_task(" in operations_routes_source,
        },
    }


def _sync_report_refresh_status(
    source_context: ApiArchitectureSourceContext,
    sync_report_blocking_async_refresh_calls: bool,
    sync_report_async_bridge_guard_present: bool,
    sync_report_async_refresh_gates_present: bool,
    sync_report_refresh_defaults_disabled: bool,
    sync_report_background_hint_present: bool,
) -> dict:
    config_source = source_context.sources["config"]
    return {
        "sync_report_network_refresh_opt_in": sync_report_refresh_defaults_disabled
        and (
            not sync_report_blocking_async_refresh_calls
            or (sync_report_async_refresh_gates_present and sync_report_async_bridge_guard_present)
        ),
        "sync_report_pre_refresh_default_enabled": (
            "sync_report_pre_refresh_enabled: bool = True" in config_source
        ),
        "sync_report_quality_recovery_default_enabled": (
            "sync_report_quality_recovery_enabled: bool = True" in config_source
        ),
        "sync_report_blocking_async_refresh_calls_present": (
            sync_report_blocking_async_refresh_calls
        ),
        "sync_report_async_bridge_guard_present": sync_report_async_bridge_guard_present,
        "sync_report_background_task_hint_present": sync_report_background_hint_present,
        "sync_report_blocking_async_calls_gated": (
            not sync_report_blocking_async_refresh_calls or sync_report_async_refresh_gates_present
        ),
    }
