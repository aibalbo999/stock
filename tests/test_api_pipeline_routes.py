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


def _services(pipeline_api):
    class FakeServices:
        def pipeline_api(self):
            return pipeline_api

    return FakeServices()
