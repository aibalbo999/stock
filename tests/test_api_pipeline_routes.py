from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.pipeline_routes import create_pipeline_router


class FakeReportExecutionError(Exception):
    pass


class FakeWorkflowOrchestrationError(Exception):
    pass


def test_pipeline_router_delegates_standard_pipeline_run() -> None:
    captured = {}

    class FakePipelineApi:
        async def run_standard(self, request) -> dict:
            captured["topic"] = request.topic
            return {"run_id": 7, "workflow_name": "standard_report_pipeline"}

    app = FastAPI()
    app.include_router(
        create_pipeline_router(
            _services(FakePipelineApi()),
            report_execution_error_cls=FakeReportExecutionError,
            workflow_orchestration_error_cls=FakeWorkflowOrchestrationError,
        )
    )

    response = TestClient(app).post("/pipeline/run", json={"topic": "AI 產業鏈", "tickers": ["2330"]})

    assert response.status_code == 200
    assert response.json() == {"run_id": 7, "workflow_name": "standard_report_pipeline"}
    assert captured == {"topic": "AI 產業鏈"}


def test_pipeline_router_maps_workflow_unavailable_to_503() -> None:
    class FakePipelineApi:
        async def run_standard(self, request) -> dict:
            raise FakeWorkflowOrchestrationError("workflow engine unavailable")

    app = FastAPI()
    app.include_router(
        create_pipeline_router(
            _services(FakePipelineApi()),
            report_execution_error_cls=FakeReportExecutionError,
            workflow_orchestration_error_cls=FakeWorkflowOrchestrationError,
        )
    )

    response = TestClient(app).post("/pipeline/run", json={"topic": "AI 產業鏈", "tickers": ["2330"]})

    assert response.status_code == 503
    assert response.json()["detail"] == "workflow engine unavailable"


def test_pipeline_router_maps_invalid_worker_dispatch_to_400() -> None:
    class FakePipelineApi:
        async def run_dispatch_payload_locally(self, payload: dict) -> dict:
            raise FakeReportExecutionError("unsupported workflow dispatch operation")

    app = FastAPI()
    app.include_router(
        create_pipeline_router(
            _services(FakePipelineApi()),
            report_execution_error_cls=FakeReportExecutionError,
            workflow_orchestration_error_cls=FakeWorkflowOrchestrationError,
        )
    )

    response = TestClient(app).post("/pipeline/worker/execute", json={"operation": "run_sideways"})

    assert response.status_code == 400
    assert response.json()["detail"] == "unsupported workflow dispatch operation"


def test_pipeline_router_delegates_worker_dispatch_and_resume_endpoints() -> None:
    captured = {}

    class FakePipelineApi:
        async def run_dispatch_payload_locally(self, payload: dict) -> dict:
            captured["dispatch"] = payload
            return {
                "run_id": 77,
                "report_id": 88,
                "workflow_orchestration": {"mode": "external_worker_local_execution"},
            }

        async def resume_standard_run(self, run_id: int) -> dict:
            captured["standard_resume"] = run_id
            return {"run_id": run_id, "report_id": 88, "resumed_from_step": "report_build"}

        async def resume_discovered_run(self, run_id: int) -> dict:
            captured["discovered_resume"] = run_id
            return {"run_id": run_id, "report_id": 89, "resumed_from_step": "auto_follow_up"}

    app = FastAPI()
    app.include_router(
        create_pipeline_router(
            _services(FakePipelineApi()),
            report_execution_error_cls=FakeReportExecutionError,
            workflow_orchestration_error_cls=FakeWorkflowOrchestrationError,
        )
    )
    client = TestClient(app)

    dispatch_response = client.post(
        "/pipeline/worker/execute",
        json={"operation": "resume_standard", "run_id": 77},
    )
    standard_response = client.post("/pipeline/runs/77/resume")
    discovered_response = client.post("/pipeline/discovered-runs/77/resume")

    assert dispatch_response.status_code == 200
    assert dispatch_response.json() == {
        "run_id": 77,
        "report_id": 88,
        "workflow_orchestration": {"mode": "external_worker_local_execution"},
    }
    assert standard_response.status_code == 200
    assert standard_response.json() == {
        "run_id": 77,
        "report_id": 88,
        "resumed_from_step": "report_build",
    }
    assert discovered_response.status_code == 200
    assert discovered_response.json() == {
        "run_id": 77,
        "report_id": 89,
        "resumed_from_step": "auto_follow_up",
    }
    assert captured == {
        "dispatch": {"operation": "resume_standard", "run_id": 77},
        "standard_resume": 77,
        "discovered_resume": 77,
    }


def _services(pipeline_api):
    class FakeServices:
        def pipeline_api(self):
            return pipeline_api

    return FakeServices()
