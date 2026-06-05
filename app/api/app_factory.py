from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Optional

from fastapi import FastAPI

from app.api.ai_routes import create_ai_router
from app.api.company_filing_routes import create_company_filing_router
from app.api.operations_routes import create_operations_router
from app.api.pipeline_routes import create_pipeline_router
from app.api.report_routes import create_report_router
from app.api.supply_chain_routes import create_supply_chain_router
from app.api.system_routes import create_system_router
from app.db.status import db_status
from app.services.company_data_audit_api import CompanyDataAuditApiNotFound
from app.services.report_generator import ReportExecutionError
from app.services.report_query import ReportQueryNotFound
from app.services.run_task_api import AsyncReportValidationError, RunTaskNotFound, TaskQueueUnavailableError
from app.services.service_status import service_status
from app.services.upgrade_audit import audit_upgrade_capabilities
from app.services.workflow_orchestration import WorkflowOrchestrationError


def create_app(
    *,
    api_services,
    lifespan,
    get_follow_up_plan_func: Callable[[int], dict],
    auto_start_follow_up_func: Callable[[int], Awaitable[dict]],
    run_follow_up_func: Callable[[int, Optional[object]], Awaitable[dict]],
) -> FastAPI:
    app = FastAPI(
        title="台股 AI 產業鏈 RAG 分析系統",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.api_services = api_services
    app.include_router(
        create_system_router(
            db_status_func=db_status,
            service_status_func=service_status,
            upgrade_audit_func=audit_upgrade_capabilities,
        )
    )
    app.include_router(create_supply_chain_router())
    app.include_router(create_company_filing_router())
    app.include_router(
        create_pipeline_router(
            report_execution_error_cls=ReportExecutionError,
            workflow_orchestration_error_cls=WorkflowOrchestrationError,
        )
    )
    app.include_router(
        create_operations_router(
            async_report_validation_error_cls=AsyncReportValidationError,
            run_task_not_found_cls=RunTaskNotFound,
            task_queue_unavailable_error_cls=TaskQueueUnavailableError,
        )
    )
    app.include_router(create_ai_router())
    app.include_router(
        create_report_router(
            report_execution_error_cls=ReportExecutionError,
            workflow_orchestration_error_cls=WorkflowOrchestrationError,
            report_query_not_found_cls=ReportQueryNotFound,
            company_data_audit_not_found_cls=CompanyDataAuditApiNotFound,
            task_queue_unavailable_error_cls=TaskQueueUnavailableError,
            get_follow_up_plan_func=get_follow_up_plan_func,
            auto_start_follow_up_func=auto_start_follow_up_func,
            run_follow_up_func=run_follow_up_func,
        )
    )
    return app
