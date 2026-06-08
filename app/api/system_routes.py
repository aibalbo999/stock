from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from app.api.schemas import MaintenanceOperationRunRequest
from app.services.external_deployment_env_gaps import (
    external_deployment_env_check_status_report,
)
from app.services.maintenance_diagnostics import (
    maintenance_diagnostic_action_catalog,
    run_maintenance_diagnostic_action,
)
from app.services.maintenance_operations import (
    maintenance_operation_catalog,
    run_maintenance_operation,
)


def create_system_router(
    *,
    db_status_func: Callable[[], dict],
    service_status_func: Callable[[], dict],
    upgrade_audit_func: Callable[..., dict],
    maintenance_diagnostic_catalog_func: Callable[[], dict] = maintenance_diagnostic_action_catalog,
    maintenance_diagnostic_run_func: Callable[[str], dict] = run_maintenance_diagnostic_action,
    maintenance_operation_catalog_func: Callable[[], dict] = maintenance_operation_catalog,
    maintenance_operation_run_func: Callable[..., dict] = run_maintenance_operation,
    external_env_check_func: Callable[..., dict] = external_deployment_env_check_status_report,
) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @router.get("/db/status")
    def database_status() -> dict:
        return db_status_func()

    @router.get("/services/status")
    def services_status() -> dict:
        return service_status_func()

    @router.get("/services/upgrade-audit")
    def services_upgrade_audit(strict_external: bool = False) -> dict:
        return upgrade_audit_func(strict_external=strict_external)

    @router.get("/services/external-deployment/env-check")
    def services_external_deployment_env_check(
        target: str = "all",
        strict_external: bool = False,
        include_process_env: bool = False,
    ) -> dict:
        try:
            return external_env_check_func(
                target=target,
                strict_external=strict_external,
                include_process_env=include_process_env,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/maintenance/diagnostics")
    def maintenance_diagnostics() -> dict:
        return maintenance_diagnostic_catalog_func()

    @router.post("/maintenance/diagnostics/{action_id}/run")
    def run_maintenance_diagnostic(action_id: str) -> dict:
        try:
            return maintenance_diagnostic_run_func(action_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/maintenance/operations")
    def maintenance_operations() -> dict:
        return maintenance_operation_catalog_func()

    @router.post("/maintenance/operations/{action_id}/run")
    def run_maintenance_operation_route(
        action_id: str,
        payload: MaintenanceOperationRunRequest,
    ) -> dict:
        try:
            return maintenance_operation_run_func(action_id, confirmed=payload.confirmed)
        except PermissionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
