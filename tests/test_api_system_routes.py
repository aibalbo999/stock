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
) -> TestClient:
    router = create_system_router(
        db_status_func=lambda: db_status or {},
        service_status_func=lambda: service_status or {},
        upgrade_audit_func=upgrade_audit_func or (lambda **kwargs: upgrade_audit or {}),
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
