from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter


def create_system_router(
    *,
    db_status_func: Callable[[], dict],
    service_status_func: Callable[[], dict],
    upgrade_audit_func: Callable[..., dict],
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

    return router
