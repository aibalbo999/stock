from __future__ import annotations

from pathlib import Path


def api_controller_status() -> dict:
    app_dir = Path(__file__).resolve().parents[1]
    api_dir = app_dir / "api"
    main_path = api_dir / "main.py"
    service_factory_path = api_dir / "service_factory.py"
    runtime_path = api_dir / "runtime.py"
    operations_routes_path = api_dir / "operations_routes.py"
    report_routes_path = api_dir / "report_routes.py"
    error_details_path = api_dir / "error_details.py"
    tasks_path = app_dir / "tasks" / "tasks.py"
    run_task_api_path = app_dir / "services" / "run_task_api.py"
    persistence_path = app_dir / "services" / "persistence.py"
    task_failure_diagnostics_path = app_dir / "services" / "task_failure_diagnostics.py"
    config_path = app_dir / "core" / "config.py"
    report_generation_api_path = app_dir / "services" / "report_generation_api.py"
    main_source = _read_source(main_path)
    main_py_lines = len(main_source.splitlines()) if main_source else None
    runtime_source = _read_source(runtime_path)
    service_factory_source = _read_source(service_factory_path)
    tasks_source = _read_source(tasks_path)
    operations_routes_source = _read_source(operations_routes_path)
    report_routes_source = _read_source(report_routes_path)
    error_details_source = _read_source(error_details_path)
    run_task_api_source = _read_source(run_task_api_path)
    persistence_source = _read_source(persistence_path)
    task_failure_diagnostics_source = _read_source(task_failure_diagnostics_path)
    config_source = _read_source(config_path)
    report_generation_api_source = _read_source(report_generation_api_path)
    route_modules = sorted(path.name for path in api_dir.glob("*_routes.py"))
    legacy_facade_path = api_dir / "legacy_facade.py"
    compatibility_exports_path = api_dir / "compatibility_exports.py"
    compatibility_helpers_path = api_dir / "compatibility_helpers.py"
    compatibility_helper_candidate_path = api_dir / "compatibility_helper_candidate.py"
    compatibility_helper_discovery_path = api_dir / "compatibility_helper_discovery.py"
    compatibility_helper_followup_path = api_dir / "compatibility_helper_followup.py"
    compatibility_helper_run_state_path = api_dir / "compatibility_helper_run_state.py"
    task_exports_path = api_dir / "task_exports.py"
    api_compatibility_path = app_dir / "services" / "api_compatibility.py"
    compatibility_candidate_path = app_dir / "services" / "api_compatibility_candidate.py"
    compatibility_discovery_path = app_dir / "services" / "api_compatibility_discovery.py"
    compatibility_followup_path = app_dir / "services" / "api_compatibility_followup.py"
    compatibility_run_state_path = app_dir / "services" / "api_compatibility_run_state.py"
    report_service_factory_path = api_dir / "service_factory_report.py"
    data_service_factory_path = api_dir / "service_factory_data.py"
    workflow_service_factory_path = api_dir / "service_factory_workflow.py"
    ai_graph_service_factory_path = api_dir / "service_factory_ai.py"
    compatibility_exports_source = _read_source(compatibility_exports_path)
    compatibility_helpers_source = _read_source(compatibility_helpers_path)
    compatibility_helper_candidate_source = _read_source(compatibility_helper_candidate_path)
    compatibility_helper_discovery_source = _read_source(compatibility_helper_discovery_path)
    compatibility_helper_followup_source = _read_source(compatibility_helper_followup_path)
    compatibility_helper_run_state_source = _read_source(compatibility_helper_run_state_path)
    legacy_facade_source = _read_source(legacy_facade_path)
    api_compatibility_source = _read_source(api_compatibility_path)
    compatibility_candidate_source = _read_source(compatibility_candidate_path)
    compatibility_discovery_source = _read_source(compatibility_discovery_path)
    compatibility_followup_source = _read_source(compatibility_followup_path)
    compatibility_run_state_source = _read_source(compatibility_run_state_path)
    report_service_factory_source = _read_source(report_service_factory_path)
    data_service_factory_source = _read_source(data_service_factory_path)
    workflow_service_factory_source = _read_source(workflow_service_factory_path)
    ai_graph_service_factory_source = _read_source(ai_graph_service_factory_path)
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
        "main_py_lines": main_py_lines,
        "route_module_count": len(route_modules),
        "route_modules": route_modules,
        "app_factory_present": (api_dir / "app_factory.py").exists(),
        "main_uses_app_factory": "from app.api.app_factory import create_app" in main_source,
        "service_factory_present": service_factory_path.exists(),
        "service_factory_lines": len(service_factory_source.splitlines()) if service_factory_source else None,
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
        "compatibility_exports_present": compatibility_exports_path.exists(),
        "main_uses_compatibility_exports": (
            "compatibility_export_namespace" in main_source
            or (
                "build_api_runtime" in main_source
                and "compatibility_exports" in main_source
                and "compatibility_export_namespace" in runtime_source
            )
        ),
        "compatibility_helpers_present": compatibility_helpers_path.exists(),
        "main_uses_compatibility_helpers": (
            "compatibility_helper_namespace" in main_source
            or (
                "build_api_runtime" in main_source
                and "compatibility_helpers" in main_source
                and "compatibility_helper_namespace" in runtime_source
            )
        ),
        "compatibility_helper_domain_builders_extracted": (
            compatibility_helper_candidate_path.exists()
            and compatibility_helper_discovery_path.exists()
            and compatibility_helper_followup_path.exists()
            and compatibility_helper_run_state_path.exists()
            and "def candidate_compatibility_helper_namespace("
            in compatibility_helper_candidate_source
            and "def discovery_compatibility_helper_namespace("
            in compatibility_helper_discovery_source
            and "def follow_up_compatibility_helper_namespace("
            in compatibility_helper_followup_source
            and "def run_state_compatibility_helper_namespace("
            in compatibility_helper_run_state_source
            and "candidate_compatibility_helper_namespace" in compatibility_helpers_source
            and "discovery_compatibility_helper_namespace" in compatibility_helpers_source
            and "follow_up_compatibility_helper_namespace" in compatibility_helpers_source
            and "run_state_compatibility_helper_namespace" in compatibility_helpers_source
            and "def run_topic_discovery_ingestion(" not in compatibility_helpers_source
            and "def run_report_follow_up(" not in compatibility_helpers_source
            and "def apply_company_filing_gate_to_candidate_payload("
            not in compatibility_helpers_source
            and "def safe_mark_run_failed(" not in compatibility_helpers_source
        ),
        "compatibility_helper_domain_builder_paths": [
            "app/api/compatibility_helper_candidate.py",
            "app/api/compatibility_helper_discovery.py",
            "app/api/compatibility_helper_followup.py",
            "app/api/compatibility_helper_run_state.py",
        ],
        "task_exports_present": task_exports_path.exists(),
        "api_runtime_uses_task_exports": "task_export_namespace" in runtime_source,
        "compatibility_exports_imports_tasks": "from app.tasks." in compatibility_exports_source,
        "main_direct_domain_import_count": len(direct_domain_imports),
        "main_direct_domain_imports": direct_domain_imports,
        "structured_task_submission_errors": (
            "def task_submission_failed_detail(" in error_details_source
            and operations_routes_source.count("task_submission_failed_detail(") >= 3
            and report_routes_source.count("task_submission_failed_detail(") >= 1
            and "background_task_submission_failed" in error_details_source
        ),
        "task_submission_error_detail_path": "app/api/error_details.py",
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
            and "task_submission_failed_detail" in operations_routes_source,
            "run_discovered_async": 'operation="run_discovered"' in operations_routes_source
            and "task_submission_failed_detail" in operations_routes_source,
            "data_operation": "operation=payload.operation" in operations_routes_source
            and "task_submission_failed_detail" in operations_routes_source,
            "report_follow_up": 'operation="report_follow_up"' in report_routes_source
            and "task_submission_failed_detail" in report_routes_source,
        },
        "sync_report_network_refresh_opt_in": sync_report_refresh_defaults_disabled
        and (
            not sync_report_blocking_async_refresh_calls
            or (
                sync_report_async_refresh_gates_present
                and sync_report_async_bridge_guard_present
            )
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
            not sync_report_blocking_async_refresh_calls
            or sync_report_async_refresh_gates_present
        ),
        "compatibility_service_present": (app_dir / "services" / "api_compatibility.py").exists(),
        "compatibility_service_domain_mixins_extracted": (
            compatibility_candidate_path.exists()
            and compatibility_discovery_path.exists()
            and compatibility_followup_path.exists()
            and compatibility_run_state_path.exists()
            and "class CandidateCompatibilityMixin" in compatibility_candidate_source
            and "class DiscoveryCompatibilityMixin" in compatibility_discovery_source
            and "class FollowUpCompatibilityMixin" in compatibility_followup_source
            and "class RunStateCompatibilityMixin" in compatibility_run_state_source
            and "CandidateCompatibilityMixin" in api_compatibility_source
            and "DiscoveryCompatibilityMixin" in api_compatibility_source
            and "FollowUpCompatibilityMixin" in api_compatibility_source
            and "RunStateCompatibilityMixin" in api_compatibility_source
            and "def run_topic_discovery_ingestion(" not in api_compatibility_source
            and "def run_report_follow_up(" not in api_compatibility_source
            and "def apply_company_filing_gate_to_candidate_payload("
            not in api_compatibility_source
            and "def safe_mark_run_failed(" not in api_compatibility_source
        ),
        "compatibility_service_domain_mixin_paths": [
            "app/services/api_compatibility_candidate.py",
            "app/services/api_compatibility_discovery.py",
            "app/services/api_compatibility_followup.py",
            "app/services/api_compatibility_run_state.py",
        ],
        "main_imports_legacy_facade": "app.api.legacy_facade" in main_source
        or "LegacyApiFacade" in main_source,
        "legacy_facade_present": legacy_facade_path.exists(),
        "legacy_facade_alias_only": "ApiCompatibilityService" in legacy_facade_source
        and "class LegacyApiFacade(ApiCompatibilityService)" in legacy_facade_source,
    }


def _read_source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
