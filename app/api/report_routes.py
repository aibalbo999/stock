from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import api_services_provider
from app.api.schemas import FollowUpRunRequest, ReportFollowUpTaskRequest
from app.models.schemas import ReportRequest, ReportResponse


def create_report_router(
    api_services: Any | None = None,
    *,
    report_execution_error_cls: type[Exception],
    workflow_orchestration_error_cls: type[Exception],
    report_query_not_found_cls: type[Exception],
    company_data_audit_not_found_cls: type[Exception],
    task_queue_unavailable_error_cls: type[Exception],
    get_follow_up_plan_func: Callable[[int], dict],
    auto_start_follow_up_func: Callable[[int], Awaitable[dict]],
    run_follow_up_func: Callable[[int, Optional[FollowUpRunRequest]], Awaitable[dict]],
) -> APIRouter:
    router = APIRouter()
    services_dependency = api_services_provider(api_services)

    @router.post("/reports/generate", response_model=ReportResponse)
    def generate_report(
        request: ReportRequest,
        services: Any = Depends(services_dependency),
    ) -> ReportResponse:
        try:
            return services.sync_report_generation_api().generate(request)
        except report_execution_error_cls as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except workflow_orchestration_error_cls as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/reports")
    def list_reports(limit: int = 20, services: Any = Depends(services_dependency)) -> list[dict]:
        return services.report_query().list_reports(limit)

    @router.get("/reports/{report_id}")
    def get_report(report_id: int, services: Any = Depends(services_dependency)) -> dict:
        try:
            return services.report_query().get_report(report_id)
        except report_query_not_found_cls as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/reports/{report_id}/candidate-audit")
    def get_report_candidate_audit(
        report_id: int,
        services: Any = Depends(services_dependency),
    ) -> dict:
        try:
            return services.report_query().candidate_audit(report_id)
        except report_query_not_found_cls as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/reports/{report_id}/company-data-audit")
    def get_report_company_data_audit(
        report_id: int,
        services: Any = Depends(services_dependency),
    ) -> dict:
        try:
            return services.company_data_audit_api().report_company_data_audit(report_id)
        except company_data_audit_not_found_cls as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/reports/{report_id}/follow-up/plan")
    def get_report_follow_up_plan(report_id: int) -> dict:
        return get_follow_up_plan_func(report_id)

    @router.post("/reports/{report_id}/follow-up/auto-start")
    async def auto_start_report_follow_up(report_id: int) -> dict:
        return await auto_start_follow_up_func(report_id)

    @router.post("/reports/{report_id}/follow-up/run")
    async def run_report_follow_up(report_id: int, payload: Optional[FollowUpRunRequest] = None) -> dict:
        return await run_follow_up_func(report_id, payload)

    @router.post("/reports/{report_id}/follow-up/run_async")
    def run_report_follow_up_async(
        report_id: int,
        payload: Optional[ReportFollowUpTaskRequest] = None,
        services: Any = Depends(services_dependency),
    ) -> dict:
        try:
            return services.run_task_api().queue_report_follow_up(
                report_id,
                (payload or ReportFollowUpTaskRequest()).model_dump(mode="json"),
            )
        except task_queue_unavailable_error_cls as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.delete("/reports/{report_id}")
    def delete_report(report_id: int, services: Any = Depends(services_dependency)) -> dict:
        try:
            return services.report_query().delete_report(report_id)
        except report_query_not_found_cls as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
