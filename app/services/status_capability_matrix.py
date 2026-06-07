from __future__ import annotations

from app.services.status_api_architecture import api_controller_status
from app.services.status_capability_ai_rag import ai_rag_capabilities
from app.services.status_capability_architecture import architecture_capabilities
from app.services.status_capability_data_business import data_business_capabilities


def upgrade_capability_matrix(status: dict) -> dict:
    vector_store = status.get("vector_store") or {}
    llm_status = status.get("gemini") or {}
    llm_quota_routing = status.get("llm_quota_routing") or {}
    llm_observability = status.get("llm_observability") or {}
    graph_status = status.get("supply_chain_graph") or {}
    workflow_status = status.get("workflow_orchestration") or {}
    database_status = status.get("database") or {}
    migration_status = database_status.get("migration") or {}
    market_cache_status = status.get("market_data_cache") or {}
    company_filing_status = status.get("company_filings") or {}
    api_status = api_controller_status()
    frontend_status = status.get("frontend") or {}
    task_queue_status = status.get("task_queue") or {}
    python_runtime_status = status.get("python_runtime") or {}
    report_retention_status = status.get("report_retention") or {}
    security_scan_status = status.get("security_scanning") or {}

    return {
        "ai_rag": ai_rag_capabilities(
            vector_store=vector_store,
            llm_status=llm_status,
            llm_quota_routing=llm_quota_routing,
            llm_observability=llm_observability,
            graph_status=graph_status,
            company_filing_status=company_filing_status,
        ),
        "architecture": architecture_capabilities(
            api_status=api_status,
            workflow_status=workflow_status,
            task_queue_status=task_queue_status,
            frontend_status=frontend_status,
            python_runtime_status=python_runtime_status,
            database_status=database_status,
            migration_status=migration_status,
            security_scan_status=security_scan_status,
        ),
        "data_business_logic": data_business_capabilities(
            market_cache_status=market_cache_status,
            finmind_status=status.get("finmind") or {},
            fugle_status=status.get("fugle") or {},
            company_filing_status=company_filing_status,
            report_retention_status=report_retention_status,
            candidate_confidence_status=status.get("candidate_confidence") or {},
        ),
    }
