from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.data_operation_error_context import data_operation_error_context
from app.api.dependencies import api_services_provider
from app.api.schemas import (
    DataOperationTaskRequest,
    FeedFetchRequest,
    MaintenanceCleanupRequest,
    ManualNewsIngest,
    MarketRefreshRequest,
    TopicDiscoveryRequest,
)
from app.api.task_submission_errors import (
    raise_task_queue_unavailable,
    raise_task_submission_failed,
)
from app.models.schemas import ReportRequest
from app.services.schedule_config import ScheduleConfig


def create_operations_router(
    api_services: Any | None = None,
    *,
    async_report_validation_error_cls: type[Exception],
    run_task_not_found_cls: type[Exception],
    task_queue_unavailable_error_cls: type[Exception],
) -> APIRouter:
    router = APIRouter()
    services_dependency = api_services_provider(api_services)

    @router.post("/ingest/manual")
    def ingest_manual(
        payload: ManualNewsIngest,
        services: Any = Depends(services_dependency),
    ) -> dict:
        return services.data_operations_api().ingest_manual_news(
            title=payload.title,
            text=payload.text,
            publisher=payload.publisher,
            published_at=payload.published_at,
            url=payload.url,
        )

    @router.get("/news")
    def list_news(limit: int = 20, services: Any = Depends(services_dependency)) -> list[dict]:
        return services.data_operations_api().list_news(limit)

    @router.get("/news/sources")
    def list_news_sources(services: Any = Depends(services_dependency)) -> list[dict]:
        return services.data_operations_api().list_news_sources()

    @router.post("/news/fetch")
    async def fetch_news(
        payload: FeedFetchRequest,
        services: Any = Depends(services_dependency),
    ) -> dict:
        return await services.data_operations_api().fetch_news(
            url=payload.url,
            publisher=payload.publisher,
            limit=payload.limit,
            enabled_sources_only=payload.enabled_sources_only,
            topic=payload.topic,
        )

    @router.post("/market/refresh")
    async def refresh_market(
        payload: MarketRefreshRequest,
        services: Any = Depends(services_dependency),
    ) -> dict:
        return await services.data_operations_api().refresh_market(
            tickers=payload.tickers,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )

    @router.post("/market/refresh_fundamentals")
    async def refresh_fundamentals(
        payload: MarketRefreshRequest,
        services: Any = Depends(services_dependency),
    ) -> dict:
        return await services.data_operations_api().refresh_fundamentals(
            tickers=payload.tickers,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )

    @router.get("/market/snapshots")
    def market_snapshots(
        tickers: str = "",
        services: Any = Depends(services_dependency),
    ) -> list[dict]:
        return services.data_operations_api().market_snapshots(tickers)

    @router.get("/market/cache-summary")
    def market_cache_summary(
        tickers: str = "",
        limit_per_ticker: int = 2,
        services: Any = Depends(services_dependency),
    ) -> dict:
        return services.data_operations_api().market_cache_summary(tickers, limit_per_ticker)

    @router.get("/schedule")
    def get_schedule(services: Any = Depends(services_dependency)) -> dict:
        return services.data_operations_api().get_schedule()

    @router.put("/schedule")
    def update_schedule(
        config: ScheduleConfig,
        services: Any = Depends(services_dependency),
    ) -> dict:
        return services.data_operations_api().update_schedule(config)

    @router.get("/runs")
    def list_runs(limit: int = 20, services: Any = Depends(services_dependency)) -> list[dict]:
        return services.run_task_api().list_runs(limit)

    @router.get("/runs/{run_id}")
    def get_run(run_id: int, services: Any = Depends(services_dependency)) -> dict:
        try:
            return services.run_task_api().get_run(run_id)
        except run_task_not_found_cls as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.delete("/runs/{run_id}")
    def delete_run(run_id: int, services: Any = Depends(services_dependency)) -> dict:
        try:
            return services.run_task_api().delete_run(run_id)
        except run_task_not_found_cls as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/maintenance/cleanup")
    def maintenance_cleanup(
        payload: MaintenanceCleanupRequest,
        services: Any = Depends(services_dependency),
    ) -> dict:
        return services.data_operations_api().maintenance_cleanup(
            failed_runs=payload.failed_runs,
            orphan_report_refs=payload.orphan_report_refs,
            latest_reports_only=payload.latest_reports_only,
            stale_running_before=payload.stale_running_before,
            runs_before=payload.runs_before,
            reports_before=payload.reports_before,
        )

    @router.post("/reports/generate_async")
    def generate_report_async(
        request: ReportRequest,
        services: Any = Depends(services_dependency),
    ) -> dict:
        try:
            return services.run_task_api().generate_report_async(request)
        except async_report_validation_error_cls as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except task_queue_unavailable_error_cls as exc:
            raise_task_queue_unavailable(exc, operation="generate_report")
        except Exception as exc:
            raise_task_submission_failed(exc, operation="generate_report")

    @router.post("/pipeline/run_discovered_async")
    def generate_discovered_report_async(
        payload: TopicDiscoveryRequest,
        services: Any = Depends(services_dependency),
    ) -> dict:
        try:
            return services.run_task_api().generate_discovered_report_async(payload)
        except async_report_validation_error_cls as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except task_queue_unavailable_error_cls as exc:
            raise_task_queue_unavailable(exc, operation="run_discovered")
        except Exception as exc:
            raise_task_submission_failed(exc, operation="run_discovered")

    @router.post("/tasks/data-operation")
    def queue_data_operation(
        payload: DataOperationTaskRequest,
        services: Any = Depends(services_dependency),
    ) -> dict:
        error_context = data_operation_error_context(payload.operation, payload.payload)
        try:
            return services.run_task_api().queue_data_operation(
                payload.operation,
                payload.payload,
            )
        except async_report_validation_error_cls as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except task_queue_unavailable_error_cls as exc:
            raise_task_queue_unavailable(
                exc,
                operation=payload.operation,
                context=error_context,
            )
        except Exception as exc:
            raise_task_submission_failed(
                exc,
                operation=payload.operation,
                context=error_context,
            )

    @router.get("/tasks/summary")
    def task_summary(
        days: int = 7,
        limit: int = 500,
        services: Any = Depends(services_dependency),
    ) -> dict:
        return services.run_task_api().task_summary(days=days, limit=limit)

    @router.get("/tasks/{task_id}")
    def get_task_status(task_id: str, services: Any = Depends(services_dependency)) -> dict:
        try:
            return services.run_task_api().get_task_status(task_id)
        except task_queue_unavailable_error_cls as exc:
            raise_task_queue_unavailable(exc, operation="task_status")

    @router.post("/tasks/{task_id}/cancel")
    def cancel_task(task_id: str, services: Any = Depends(services_dependency)) -> dict:
        try:
            return services.run_task_api().cancel_task(task_id)
        except task_queue_unavailable_error_cls as exc:
            raise_task_queue_unavailable(exc, operation="task_cancel")

    @router.post("/tasks/{task_id}/retry")
    def retry_task(task_id: str, services: Any = Depends(services_dependency)) -> dict:
        try:
            return services.run_task_api().retry_task(task_id)
        except run_task_not_found_cls as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except async_report_validation_error_cls as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except task_queue_unavailable_error_cls as exc:
            raise_task_queue_unavailable(exc, operation="task_retry")

    @router.get("/tasks/{task_id}/run")
    def get_run_by_task_id(task_id: str, services: Any = Depends(services_dependency)) -> dict:
        try:
            return services.run_task_api().get_run_by_task_id(task_id)
        except run_task_not_found_cls as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
