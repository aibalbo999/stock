from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import api_services_provider
from app.api.schemas import TopicDiscoveryRequest
from app.models.schemas import ReportRequest


def create_pipeline_router(
    api_services: Any | None = None,
    *,
    report_execution_error_cls: type[Exception],
    workflow_orchestration_error_cls: type[Exception],
) -> APIRouter:
    router = APIRouter()
    services_dependency = api_services_provider(api_services)

    @router.post("/pipeline/run")
    async def run_pipeline(
        request: ReportRequest,
        services: Any = Depends(services_dependency),
    ) -> dict:
        try:
            return await services.pipeline_api().run_standard(request)
        except report_execution_error_cls as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except workflow_orchestration_error_cls as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post("/pipeline/worker/execute")
    async def execute_pipeline_dispatch_locally(
        payload: dict[str, Any],
        services: Any = Depends(services_dependency),
    ) -> dict:
        try:
            return await services.pipeline_api().run_dispatch_payload_locally(payload)
        except report_execution_error_cls as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post("/pipeline/runs/{run_id}/resume")
    async def resume_standard_pipeline(
        run_id: int,
        services: Any = Depends(services_dependency),
    ) -> dict:
        try:
            return await services.pipeline_api().resume_standard_run(run_id)
        except report_execution_error_cls as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except workflow_orchestration_error_cls as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post("/pipeline/discovered-runs/{run_id}/resume")
    async def resume_discovered_pipeline(
        run_id: int,
        services: Any = Depends(services_dependency),
    ) -> dict:
        try:
            return await services.pipeline_api().resume_discovered_run(run_id)
        except report_execution_error_cls as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except workflow_orchestration_error_cls as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post("/pipeline/run_discovered")
    async def run_discovered_pipeline(
        payload: TopicDiscoveryRequest,
        services: Any = Depends(services_dependency),
    ) -> dict:
        try:
            return await services.pipeline_api().run_discovered(payload)
        except report_execution_error_cls as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except workflow_orchestration_error_cls as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
