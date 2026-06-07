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
    main_source = ""
    runtime_source = ""
    tasks_source = ""
    try:
        main_source = main_path.read_text(encoding="utf-8")
        main_py_lines = len(main_source.splitlines())
    except OSError:
        main_py_lines = None
    try:
        runtime_source = runtime_path.read_text(encoding="utf-8")
    except OSError:
        runtime_source = ""
    try:
        service_factory_source = service_factory_path.read_text(encoding="utf-8")
    except OSError:
        service_factory_source = ""
    try:
        tasks_source = tasks_path.read_text(encoding="utf-8")
    except OSError:
        tasks_source = ""
    try:
        operations_routes_source = operations_routes_path.read_text(encoding="utf-8")
    except OSError:
        operations_routes_source = ""
    try:
        report_routes_source = report_routes_path.read_text(encoding="utf-8")
    except OSError:
        report_routes_source = ""
    try:
        error_details_source = error_details_path.read_text(encoding="utf-8")
    except OSError:
        error_details_source = ""
    try:
        run_task_api_source = run_task_api_path.read_text(encoding="utf-8")
    except OSError:
        run_task_api_source = ""
    try:
        persistence_source = persistence_path.read_text(encoding="utf-8")
    except OSError:
        persistence_source = ""
    try:
        task_failure_diagnostics_source = task_failure_diagnostics_path.read_text(encoding="utf-8")
    except OSError:
        task_failure_diagnostics_source = ""
    route_modules = sorted(path.name for path in api_dir.glob("*_routes.py"))
    legacy_facade_path = api_dir / "legacy_facade.py"
    compatibility_exports_path = api_dir / "compatibility_exports.py"
    compatibility_helpers_path = api_dir / "compatibility_helpers.py"
    task_exports_path = api_dir / "task_exports.py"
    report_service_factory_path = api_dir / "service_factory_report.py"
    data_service_factory_path = api_dir / "service_factory_data.py"
    workflow_service_factory_path = api_dir / "service_factory_workflow.py"
    ai_graph_service_factory_path = api_dir / "service_factory_ai.py"
    try:
        compatibility_exports_source = compatibility_exports_path.read_text(encoding="utf-8")
    except OSError:
        compatibility_exports_source = ""
    try:
        legacy_facade_source = legacy_facade_path.read_text(encoding="utf-8")
    except OSError:
        legacy_facade_source = ""
    try:
        report_service_factory_source = report_service_factory_path.read_text(encoding="utf-8")
    except OSError:
        report_service_factory_source = ""
    try:
        data_service_factory_source = data_service_factory_path.read_text(encoding="utf-8")
    except OSError:
        data_service_factory_source = ""
    try:
        workflow_service_factory_source = workflow_service_factory_path.read_text(encoding="utf-8")
    except OSError:
        workflow_service_factory_source = ""
    try:
        ai_graph_service_factory_source = ai_graph_service_factory_path.read_text(encoding="utf-8")
    except OSError:
        ai_graph_service_factory_source = ""
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
        "compatibility_service_present": (app_dir / "services" / "api_compatibility.py").exists(),
        "main_imports_legacy_facade": "app.api.legacy_facade" in main_source
        or "LegacyApiFacade" in main_source,
        "legacy_facade_present": legacy_facade_path.exists(),
        "legacy_facade_alias_only": "ApiCompatibilityService" in legacy_facade_source
        and "class LegacyApiFacade(ApiCompatibilityService)" in legacy_facade_source,
    }
