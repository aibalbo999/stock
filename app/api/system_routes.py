from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from app.services.maintenance_diagnostics import (
    maintenance_diagnostic_action_catalog,
    run_maintenance_diagnostic_action,
)


def create_system_router(
    *,
    db_status_func: Callable[[], dict],
    service_status_func: Callable[[], dict],
    upgrade_audit_func: Callable[..., dict],
    maintenance_diagnostic_catalog_func: Callable[[], dict] = maintenance_diagnostic_action_catalog,
    maintenance_diagnostic_run_func: Callable[[str], dict] = run_maintenance_diagnostic_action,
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

    @router.get("/maintenance/diagnostics")
    def maintenance_diagnostics() -> dict:
        return maintenance_diagnostic_catalog_func()

    @router.post("/maintenance/diagnostics/{action_id}/run")
    def run_maintenance_diagnostic(action_id: str) -> dict:
        try:
            return maintenance_diagnostic_run_func(action_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
