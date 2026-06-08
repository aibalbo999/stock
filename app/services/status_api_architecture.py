from __future__ import annotations

from app.services.status_api_architecture_compatibility import (
    api_compatibility_architecture_status,
)
from app.services.status_api_architecture_sources import api_architecture_source_context


def api_controller_status() -> dict:
    source_context = api_architecture_source_context()
    api_dir = source_context.api_dir
    paths = source_context.paths
    sources = source_context.sources
    service_factory_path = paths["service_factory"]
    runtime_path = paths["runtime"]
    task_failure_diagnostics_path = paths["task_failure_diagnostics"]
    main_source = sources["main"]
    main_py_lines = len(main_source.splitlines()) if main_source else None
    runtime_source = sources["runtime"]
    service_factory_source = sources["service_factory"]
    tasks_source = sources["tasks"]
    operations_routes_source = sources["operations_routes"]
    report_routes_source = sources["report_routes"]
    error_details_source = sources["error_details"]
    task_submission_errors_source = sources["task_submission_errors"]
    run_task_api_source = sources["run_task_api"]
    persistence_source = sources["persistence"]
    task_failure_diagnostics_source = sources["task_failure_diagnostics"]
    config_source = sources["config"]
    report_generation_api_source = sources["report_generation_api"]
    legacy_facade_reference_scan_paths = source_context.legacy_facade_reference_scan_paths
    route_modules = source_context.route_modules
    task_exports_path = paths["task_exports"]
    report_service_factory_path = paths["report_service_factory"]
    data_service_factory_path = paths["data_service_factory"]
    workflow_service_factory_path = paths["workflow_service_factory"]
    ai_graph_service_factory_path = paths["ai_graph_service_factory"]
    compatibility_exports_source = sources["compatibility_exports"]
    report_service_factory_source = sources["report_service_factory"]
    data_service_factory_source = sources["data_service_factory"]
    workflow_service_factory_source = sources["workflow_service_factory"]
    ai_graph_service_factory_source = sources["ai_graph_service_factory"]
    direct_domain_imports = [
        line.strip()
        for line in main_source.splitlines()
        if (
            line.startswith("from app.data_sources.")
            or line.startswith("from app.db.")
            or line.startswith("from app.models.")
            or line.startswith("from app.rag.")
            or line.startswith("from app.tasks.")
            or (
                line.startswith("from app.services.")
                and "app.services.api_compatibility" not in line
            )
        )
    ]
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
        '"IngestionPipeline"] if sync_pre_refresh_enabled else None'
        in report_service_factory_source
        and '"IngestionPipeline"] if sync_quality_recovery_enabled else None'
        in report_service_factory_source
    )
    sync_report_refresh_defaults_disabled = (
        "sync_report_pre_refresh_enabled: bool = False" in config_source
        and "sync_report_quality_recovery_enabled: bool = False" in config_source
    )
    return {
        "collector_path": "app/services/status_api_architecture.py",
        "api_source_context_extracted": source_context.__class__.__name__
        == "ApiArchitectureSourceContext"
        and "main" in sources
        and "legacy_facade" in sources
        and bool(legacy_facade_reference_scan_paths),
        "api_source_context_path": "app/services/status_api_architecture_sources.py",
        "main_py_lines": main_py_lines,
        "route_module_count": len(route_modules),
        "route_modules": route_modules,
        "app_factory_present": (api_dir / "app_factory.py").exists(),
        "main_uses_app_factory": "from app.api.app_factory import create_app" in main_source,
        "service_factory_present": service_factory_path.exists(),
        "service_factory_lines": len(service_factory_source.splitlines())
        if service_factory_source
        else None,
        "report_service_factory_path": "app/api/service_factory_report.py",
        "report_service_factory_extracted": report_service_factory_path.exists()
        and "class ReportServiceFactoryMixin" in report_service_factory_source
        and "def report_query(" in report_service_factory_source
        and "def sync_report_generation_api(" in report_service_factory_source
        and "def report_follow_up_run(" in report_service_factory_source
        and "ReportServiceFactoryMixin" in service_factory_source
        and "def report_query(" not in service_factory_source
        and "def sync_report_generation_api(" not in service_factory_source,
        "data_service_factory_path": "app/api/service_factory_data.py",
        "data_service_factory_extracted": data_service_factory_path.exists()
        and "class DataServiceFactoryMixin" in data_service_factory_source
        and "def data_operations_api(" in data_service_factory_source
        and "def discovery_api(" in data_service_factory_source
        and "def company_filing_api(" in data_service_factory_source
        and "DataServiceFactoryMixin" in service_factory_source
        and "def data_operations_api(" not in service_factory_source
        and "def discovery_api(" not in service_factory_source
        and "def company_filing_api(" not in service_factory_source,
        "workflow_service_factory_path": "app/api/service_factory_workflow.py",
        "workflow_service_factory_extracted": workflow_service_factory_path.exists()
        and "class WorkflowServiceFactoryMixin" in workflow_service_factory_source
        and "def run_task_api(" in workflow_service_factory_source
        and "def pipeline_api(" in workflow_service_factory_source
        and "def standard_report_pipeline(" in workflow_service_factory_source
        and "WorkflowServiceFactoryMixin" in service_factory_source
        and "def run_task_api(" not in service_factory_source
        and "def pipeline_api(" not in service_factory_source
        and "def standard_report_pipeline(" not in service_factory_source,
        "ai_graph_service_factory_path": "app/api/service_factory_ai.py",
        "ai_graph_service_factory_extracted": ai_graph_service_factory_path.exists()
        and "class AiGraphServiceFactoryMixin" in ai_graph_service_factory_source
        and "def supply_chain_graph_api(" in ai_graph_service_factory_source
        and "def llm_api(" in ai_graph_service_factory_source
        and "AiGraphServiceFactoryMixin" in service_factory_source
        and "def supply_chain_graph_api(" not in service_factory_source
        and "def llm_api(" not in service_factory_source,
        "api_runtime_present": runtime_path.exists(),
        "main_uses_api_runtime": "build_api_runtime" in main_source,
        "task_uses_api_runtime": "get_task_api_services" in tasks_source,
        "task_imports_api_main": "app.api.main" in tasks_source,
        **api_compatibility_architecture_status(source_context),
        "task_exports_present": task_exports_path.exists(),
        "api_runtime_uses_task_exports": "task_export_namespace" in runtime_source,
        "compatibility_exports_imports_tasks": "from app.tasks." in compatibility_exports_source,
        "main_direct_domain_import_count": len(direct_domain_imports),
        "main_direct_domain_imports": direct_domain_imports,
        "structured_task_submission_errors": (
            "def task_submission_failed_detail(" in error_details_source
            and "def raise_task_submission_failed(" in task_submission_errors_source
            and "def raise_task_queue_unavailable(" in task_submission_errors_source
            and task_submission_errors_source.count("task_submission_failed_detail(") >= 1
            and task_submission_errors_source.count("task_queue_unavailable_detail(") >= 1
            and operations_routes_source.count("raise_task_submission_failed(") >= 3
            and report_routes_source.count("raise_task_submission_failed(") >= 1
            and "background_task_submission_failed" in error_details_source
        ),
        "task_submission_error_detail_path": "app/api/error_details.py",
        "task_submission_error_helper_path": "app/api/task_submission_errors.py",
        "task_failure_diagnostics_shared_service": task_failure_diagnostics_path.exists()
        and "def task_failure_diagnostic_payload(" in task_failure_diagnostics_source
        and "def task_failure_diagnostic(" in task_failure_diagnostics_source
        and "from app.services.task_failure_diagnostics import (" in run_task_api_source,
        "task_failure_diagnostics_persisted_to_run_payload": (
            "task_failure_diagnostic_payload" in persistence_source
            and '"task_failure_diagnostic"' in persistence_source
            and "def _clear_task_failure_diagnostic(" in persistence_source
        ),
        "task_submission_error_endpoint_coverage": {
            "generate_report_async": 'operation="generate_report"' in operations_routes_source
            and "raise_task_submission_failed" in operations_routes_source,
            "run_discovered_async": 'operation="run_discovered"' in operations_routes_source
            and "raise_task_submission_failed" in operations_routes_source,
            "data_operation": "operation=payload.operation" in operations_routes_source
            and "raise_task_submission_failed" in operations_routes_source,
            "report_follow_up": 'operation="report_follow_up"' in report_routes_source
            and "raise_task_submission_failed" in report_routes_source,
        },
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
        "sync_report_blocking_async_calls_gated": (
            not sync_report_blocking_async_refresh_calls or sync_report_async_refresh_gates_present
        ),
    }
