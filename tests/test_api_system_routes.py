from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.system_routes import create_system_router


def system_router_client(
    *,
    db_status: dict | None = None,
    service_status: dict | None = None,
    upgrade_audit: dict | None = None,
    upgrade_audit_func=None,
    maintenance_diagnostic_catalog: dict | None = None,
    maintenance_diagnostic_run_func=None,
    maintenance_operation_catalog: dict | None = None,
    maintenance_operation_run_func=None,
) -> TestClient:
    router = create_system_router(
        db_status_func=lambda: db_status or {},
        service_status_func=lambda: service_status or {},
        upgrade_audit_func=upgrade_audit_func or (lambda **kwargs: upgrade_audit or {}),
        maintenance_diagnostic_catalog_func=lambda: maintenance_diagnostic_catalog or {},
        maintenance_diagnostic_run_func=maintenance_diagnostic_run_func
        or (lambda action_id: {"action_id": action_id}),
        maintenance_operation_catalog_func=lambda: maintenance_operation_catalog or {},
        maintenance_operation_run_func=maintenance_operation_run_func
        or (lambda action_id, **kwargs: {"action_id": action_id, **kwargs}),
    )

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_system_router_health_endpoint() -> None:
    response = system_router_client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_system_router_services_status_endpoint() -> None:
    response = system_router_client(
        service_status={
            "database": {"ready": True},
            "market_data_cache": {"enabled": True},
            "vector_store": {"enabled": True},
        }
    ).get("/services/status")

    assert response.status_code == 200
    body = response.json()
    assert "database" in body
    assert "market_data_cache" in body
    assert "vector_store" in body


def test_system_router_upgrade_audit_endpoint() -> None:
    response = system_router_client(
        upgrade_audit={
            "strict_external": False,
            "summary": {"status": "ready"},
            "checks": [{"capability": "multilingual_embedding"}],
        }
    ).get("/services/upgrade-audit")

    assert response.status_code == 200
    body = response.json()
    assert body["strict_external"] is False
    assert "summary" in body
    assert "checks" in body
    assert any(check["capability"] == "multilingual_embedding" for check in body["checks"])


def test_system_router_upgrade_audit_endpoint_passes_strict_external_flag() -> None:
    captured = {}

    def fake_upgrade_audit(**kwargs):
        captured["kwargs"] = kwargs
        return {"ok": True}

    router = create_system_router(
        db_status_func=lambda: {},
        service_status_func=lambda: {},
        upgrade_audit_func=fake_upgrade_audit,
    )

    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get("/services/upgrade-audit?strict_external=true")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert captured["kwargs"] == {"strict_external": True}


def test_system_router_maintenance_diagnostics_catalog_endpoint() -> None:
    response = system_router_client(
        maintenance_diagnostic_catalog={
            "execution_policy": "allowlisted_read_only_subprocess",
            "actions": [{"id": "upgrade_audit", "read_only": True}],
        }
    ).get("/maintenance/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["execution_policy"] == "allowlisted_read_only_subprocess"
    assert body["actions"] == [{"id": "upgrade_audit", "read_only": True}]


def test_system_router_maintenance_diagnostic_run_endpoint_delegates_action_id() -> None:
    captured = {}

    def fake_run(action_id: str) -> dict:
        captured["action_id"] = action_id
        return {"id": action_id, "status": "success", "stdout_tail": "ok"}

    response = system_router_client(maintenance_diagnostic_run_func=fake_run).post(
        "/maintenance/diagnostics/upgrade_audit/run"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert captured["action_id"] == "upgrade_audit"


def test_system_router_maintenance_diagnostic_run_endpoint_rejects_unknown_action() -> None:
    def fake_run(action_id: str) -> dict:
        raise ValueError(f"Unknown maintenance diagnostic action: {action_id}")

    response = system_router_client(maintenance_diagnostic_run_func=fake_run).post(
        "/maintenance/diagnostics/rm-rf/run"
    )

    assert response.status_code == 404
    assert "Unknown maintenance diagnostic action" in response.json()["detail"]


def test_system_router_maintenance_operations_catalog_endpoint() -> None:
    response = system_router_client(
        maintenance_operation_catalog={
            "execution_policy": "allowlisted_local_dependency_operations",
            "operations": [{"id": "start_local_dependencies", "requires_confirmation": True}],
        }
    ).get("/maintenance/operations")

    assert response.status_code == 200
    body = response.json()
    assert body["execution_policy"] == "allowlisted_local_dependency_operations"
    assert body["operations"] == [{"id": "start_local_dependencies", "requires_confirmation": True}]


def test_system_router_maintenance_operation_run_endpoint_delegates_confirmation() -> None:
    captured = {}

    def fake_run(action_id: str, **kwargs) -> dict:
        captured["action_id"] = action_id
        captured["kwargs"] = kwargs
        return {"id": action_id, "status": "success"}

    response = system_router_client(maintenance_operation_run_func=fake_run).post(
        "/maintenance/operations/start_local_dependencies/run",
        json={"confirmed": True},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert captured == {
        "action_id": "start_local_dependencies",
        "kwargs": {"confirmed": True},
    }


def test_system_router_maintenance_operation_run_endpoint_requires_confirmation() -> None:
    def fake_run(action_id: str, **kwargs) -> dict:
        raise PermissionError(f"Maintenance operation requires confirmation: {action_id}")

    response = system_router_client(maintenance_operation_run_func=fake_run).post(
        "/maintenance/operations/start_local_dependencies/run",
        json={"confirmed": False},
    )

    assert response.status_code == 400
    assert "requires confirmation" in response.json()["detail"]


def test_system_router_maintenance_operation_run_endpoint_rejects_unknown_action() -> None:
    def fake_run(action_id: str, **kwargs) -> dict:
        raise ValueError(f"Unknown maintenance operation: {action_id}")

    response = system_router_client(maintenance_operation_run_func=fake_run).post(
        "/maintenance/operations/rm-rf/run",
        json={"confirmed": True},
    )

    assert response.status_code == 404
    assert "Unknown maintenance operation" in response.json()["detail"]
