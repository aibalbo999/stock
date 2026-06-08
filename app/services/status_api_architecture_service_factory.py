from __future__ import annotations

from app.services.status_api_architecture_sources import ApiArchitectureSourceContext


def api_service_factory_architecture_status(
    source_context: ApiArchitectureSourceContext,
) -> dict:
    paths = source_context.paths
    sources = source_context.sources
    service_factory_source = sources["service_factory"]
    report_service_factory_source = sources["report_service_factory"]
    data_service_factory_source = sources["data_service_factory"]
    workflow_service_factory_source = sources["workflow_service_factory"]
    ai_graph_service_factory_source = sources["ai_graph_service_factory"]
    return {
        "api_service_factory_architecture_status_extracted": True,
        "api_service_factory_architecture_status_path": (
            "app/services/status_api_architecture_service_factory.py"
        ),
        "service_factory_present": paths["service_factory"].exists(),
        "service_factory_lines": len(service_factory_source.splitlines())
        if service_factory_source
        else None,
        "report_service_factory_path": "app/api/service_factory_report.py",
        "report_service_factory_extracted": paths["report_service_factory"].exists()
        and "class ReportServiceFactoryMixin" in report_service_factory_source
        and "def report_query(" in report_service_factory_source
        and "def sync_report_generation_api(" in report_service_factory_source
        and "def report_follow_up_run(" in report_service_factory_source
        and "ReportServiceFactoryMixin" in service_factory_source
        and "def report_query(" not in service_factory_source
        and "def sync_report_generation_api(" not in service_factory_source,
        "data_service_factory_path": "app/api/service_factory_data.py",
        "data_service_factory_extracted": paths["data_service_factory"].exists()
        and "class DataServiceFactoryMixin" in data_service_factory_source
        and "def data_operations_api(" in data_service_factory_source
        and "def discovery_api(" in data_service_factory_source
        and "def company_filing_api(" in data_service_factory_source
        and "DataServiceFactoryMixin" in service_factory_source
        and "def data_operations_api(" not in service_factory_source
        and "def discovery_api(" not in service_factory_source
        and "def company_filing_api(" not in service_factory_source,
        "workflow_service_factory_path": "app/api/service_factory_workflow.py",
        "workflow_service_factory_extracted": paths["workflow_service_factory"].exists()
        and "class WorkflowServiceFactoryMixin" in workflow_service_factory_source
        and "def run_task_api(" in workflow_service_factory_source
        and "def pipeline_api(" in workflow_service_factory_source
        and "def standard_report_pipeline(" in workflow_service_factory_source
        and "WorkflowServiceFactoryMixin" in service_factory_source
        and "def run_task_api(" not in service_factory_source
        and "def pipeline_api(" not in service_factory_source
        and "def standard_report_pipeline(" not in service_factory_source,
        "ai_graph_service_factory_path": "app/api/service_factory_ai.py",
        "ai_graph_service_factory_extracted": paths["ai_graph_service_factory"].exists()
        and "class AiGraphServiceFactoryMixin" in ai_graph_service_factory_source
        and "def supply_chain_graph_api(" in ai_graph_service_factory_source
        and "def llm_api(" in ai_graph_service_factory_source
        and "AiGraphServiceFactoryMixin" in service_factory_source
        and "def supply_chain_graph_api(" not in service_factory_source
        and "def llm_api(" not in service_factory_source,
    }
