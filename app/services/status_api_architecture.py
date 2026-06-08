from __future__ import annotations

from app.services.status_api_architecture_compatibility import (
    api_compatibility_architecture_status,
)
from app.services.status_api_architecture_sources import api_architecture_source_context
from app.services.status_api_architecture_tasking import api_tasking_architecture_status


def api_controller_status() -> dict:
    source_context = api_architecture_source_context()
    api_dir = source_context.api_dir
    paths = source_context.paths
    sources = source_context.sources
    service_factory_path = paths["service_factory"]
    runtime_path = paths["runtime"]
    main_source = sources["main"]
    main_py_lines = len(main_source.splitlines()) if main_source else None
    service_factory_source = sources["service_factory"]
    legacy_facade_reference_scan_paths = source_context.legacy_facade_reference_scan_paths
    route_modules = source_context.route_modules
    report_service_factory_path = paths["report_service_factory"]
    data_service_factory_path = paths["data_service_factory"]
    workflow_service_factory_path = paths["workflow_service_factory"]
    ai_graph_service_factory_path = paths["ai_graph_service_factory"]
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
        **api_compatibility_architecture_status(source_context),
        **api_tasking_architecture_status(source_context),
        "main_direct_domain_import_count": len(direct_domain_imports),
        "main_direct_domain_imports": direct_domain_imports,
    }
