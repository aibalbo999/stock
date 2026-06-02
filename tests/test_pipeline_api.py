from types import SimpleNamespace

import pytest

from app.models.schemas import ReportRequest
from app.services.report_generator import ReportExecutionError
from app.services.pipeline_api import PipelineApiService


def test_pipeline_api_runs_standard_pipeline_through_workflow_runner() -> None:
    captured = {}

    class FakeWorkflowRunner:
        async def run(self, workflow_name, local_runner, **kwargs):
            captured["workflow_name"] = workflow_name
            captured["dispatch_payload"] = kwargs["dispatch_payload"]
            result = await local_runner()
            return {**result, "workflow_orchestration": {"mode": "local_checkpoint"}}

    class FakeStandardPipeline:
        async def run(self, request):
            captured["request"] = request.model_dump(mode="json")
            return {"report_id": 7}

    service = PipelineApiService(
        workflow_runner_factory=FakeWorkflowRunner,
        standard_pipeline_factory=FakeStandardPipeline,
        discovered_pipeline_factory=lambda: None,
    )

    result = run_async(service.run_standard(ReportRequest(topic="AI 產業鏈", tickers=["2330"])))

    assert result == {"report_id": 7, "workflow_orchestration": {"mode": "local_checkpoint"}}
    assert captured == {
        "workflow_name": "standard_report_pipeline",
        "dispatch_payload": {
            "operation": "run_standard",
            "request": ReportRequest(topic="AI 產業鏈", tickers=["2330"]).model_dump(mode="json"),
        },
        "request": ReportRequest(topic="AI 產業鏈", tickers=["2330"]).model_dump(mode="json"),
    }


def test_pipeline_api_runs_discovered_pipeline_through_workflow_runner() -> None:
    captured = {}
    payload = SimpleNamespace(topic="機器人產業鏈")

    class FakeWorkflowRunner:
        async def run(self, workflow_name, local_runner, **kwargs):
            captured["workflow_name"] = workflow_name
            captured["dispatch_payload"] = kwargs["dispatch_payload"]
            result = await local_runner()
            return {**result, "workflow_orchestration": {"mode": "prefect_flow"}}

    class FakeDiscoveredPipeline:
        async def run(self, received_payload):
            captured["payload"] = received_payload
            return {"report_id": 8}

    service = PipelineApiService(
        workflow_runner_factory=FakeWorkflowRunner,
        standard_pipeline_factory=lambda: None,
        discovered_pipeline_factory=FakeDiscoveredPipeline,
    )

    result = run_async(service.run_discovered(payload))

    assert result == {"report_id": 8, "workflow_orchestration": {"mode": "prefect_flow"}}
    assert captured == {
        "workflow_name": "ai_discovered_topic_pipeline",
        "dispatch_payload": {
            "operation": "run_discovered",
            "request": {"topic": "機器人產業鏈"},
        },
        "payload": payload,
    }


def test_pipeline_api_resumes_standard_pipeline_through_workflow_runner() -> None:
    captured = {}

    class FakeWorkflowRunner:
        async def run(self, workflow_name, local_runner, **kwargs):
            captured["workflow_name"] = workflow_name
            captured["dispatch_payload"] = kwargs["dispatch_payload"]
            result = await local_runner()
            return {**result, "workflow_orchestration": {"mode": "local_checkpoint"}}

    class FakeStandardPipeline:
        async def resume(self, run_id):
            captured["run_id"] = run_id
            return {"report_id": 11, "resumed_from_step": "report_build"}

    service = PipelineApiService(
        workflow_runner_factory=FakeWorkflowRunner,
        standard_pipeline_factory=FakeStandardPipeline,
        discovered_pipeline_factory=lambda: None,
    )

    result = run_async(service.resume_standard_run(77))

    assert result == {
        "report_id": 11,
        "resumed_from_step": "report_build",
        "workflow_orchestration": {"mode": "local_checkpoint"},
    }
    assert captured == {
        "workflow_name": "standard_report_pipeline",
        "dispatch_payload": {"operation": "resume_standard", "run_id": 77},
        "run_id": 77,
    }


def test_pipeline_api_resumes_discovered_pipeline_through_workflow_runner() -> None:
    captured = {}

    class FakeWorkflowRunner:
        async def run(self, workflow_name, local_runner, **kwargs):
            captured["workflow_name"] = workflow_name
            captured["dispatch_payload"] = kwargs["dispatch_payload"]
            result = await local_runner()
            return {**result, "workflow_orchestration": {"mode": "local_checkpoint"}}

    class FakeDiscoveredPipeline:
        async def resume(self, run_id):
            captured["run_id"] = run_id
            return {"report_id": 12, "resumed_from_step": "auto_follow_up"}

    service = PipelineApiService(
        workflow_runner_factory=FakeWorkflowRunner,
        standard_pipeline_factory=lambda: None,
        discovered_pipeline_factory=FakeDiscoveredPipeline,
    )

    result = run_async(service.resume_discovered_run(77))

    assert result == {
        "report_id": 12,
        "resumed_from_step": "auto_follow_up",
        "workflow_orchestration": {"mode": "local_checkpoint"},
    }
    assert captured == {
        "workflow_name": "ai_discovered_topic_pipeline",
        "dispatch_payload": {"operation": "resume_discovered", "run_id": 77},
        "run_id": 77,
    }


def test_pipeline_api_persists_workflow_orchestration_metadata_when_run_id_is_available() -> None:
    captured = {}

    class FakeWorkflowRunner:
        async def run(self, workflow_name, local_runner, **kwargs):
            result = await local_runner()
            return {
                **result,
                "workflow_orchestration": {
                    "requested_engine": "prefect",
                    "executed_engine": "prefect",
                    "mode": "prefect_flow",
                },
            }

    class FakeStandardPipeline:
        async def run(self, request):
            return {"run_id": 77, "report_id": 7}

    class FakeRunState:
        def safe_merge_payload(self, run_id, updates):
            captured["persisted"] = {"run_id": run_id, "updates": updates}
            return True

    service = PipelineApiService(
        workflow_runner_factory=FakeWorkflowRunner,
        standard_pipeline_factory=FakeStandardPipeline,
        discovered_pipeline_factory=lambda: None,
        run_state_factory=lambda: FakeRunState(),
    )

    result = run_async(service.run_standard(ReportRequest(topic="AI 產業鏈", tickers=["2330"])))

    assert result["workflow_orchestration"]["mode"] == "prefect_flow"
    assert captured["persisted"] == {
        "run_id": 77,
        "updates": {
            "workflow_orchestration": {
                "requested_engine": "prefect",
                "executed_engine": "prefect",
                "mode": "prefect_flow",
            },
        },
    }


def test_pipeline_api_executes_standard_dispatch_payload_locally_without_workflow_runner() -> None:
    captured = {}

    class FailingWorkflowRunner:
        async def run(self, workflow_name, local_runner, **kwargs):
            raise AssertionError("worker local execution must bypass workflow runner")

    class FakeStandardPipeline:
        async def run(self, request):
            captured["request"] = request.model_dump(mode="json")
            return {"run_id": 77, "report_id": 7}

    class FakeRunState:
        def safe_merge_payload(self, run_id, updates):
            captured["persisted"] = {"run_id": run_id, "updates": updates}
            return True

    service = PipelineApiService(
        workflow_runner_factory=FailingWorkflowRunner,
        standard_pipeline_factory=FakeStandardPipeline,
        discovered_pipeline_factory=lambda: None,
        run_state_factory=lambda: FakeRunState(),
    )

    result = run_async(
        service.run_dispatch_payload_locally(
            {
                "operation": "run_standard",
                "request": {"topic": "AI 產業鏈", "tickers": ["2330"]},
            }
        )
    )

    assert captured["request"] == ReportRequest(topic="AI 產業鏈", tickers=["2330"]).model_dump(mode="json")
    assert result["workflow_orchestration"]["mode"] == "external_worker_local_execution"
    assert result["workflow_orchestration"]["requested_engine"] == "external_worker"
    assert captured["persisted"]["run_id"] == 77


def test_pipeline_api_executes_discovered_dispatch_payload_with_configured_schema() -> None:
    captured = {}

    class FakeTopicDiscoveryRequest:
        @classmethod
        def model_validate(cls, payload):
            return SimpleNamespace(**payload)

    class FakeDiscoveredPipeline:
        async def run(self, payload):
            captured["topic"] = payload.topic
            return {"run_id": 88, "report_id": 8}

    service = PipelineApiService(
        workflow_runner_factory=lambda: None,
        standard_pipeline_factory=lambda: None,
        discovered_pipeline_factory=FakeDiscoveredPipeline,
        topic_discovery_request_cls=FakeTopicDiscoveryRequest,
    )

    result = run_async(
        service.run_dispatch_payload_locally(
            {"operation": "run_discovered", "request": {"topic": "機器人產業鏈"}}
        )
    )

    assert captured["topic"] == "機器人產業鏈"
    assert result["workflow_orchestration"]["mode"] == "external_worker_local_execution"


def test_pipeline_api_executes_resume_dispatch_payload_locally() -> None:
    captured = {}

    class FakeStandardPipeline:
        async def resume(self, run_id):
            captured["run_id"] = run_id
            return {"run_id": run_id, "report_id": 11}

    service = PipelineApiService(
        workflow_runner_factory=lambda: None,
        standard_pipeline_factory=FakeStandardPipeline,
        discovered_pipeline_factory=lambda: None,
    )

    result = run_async(service.run_dispatch_payload_locally({"operation": "resume_standard", "run_id": 77}))

    assert captured["run_id"] == 77
    assert result["workflow_orchestration"]["mode"] == "external_worker_local_execution"


def test_pipeline_api_rejects_unknown_worker_dispatch_operation() -> None:
    service = PipelineApiService(
        workflow_runner_factory=lambda: None,
        standard_pipeline_factory=lambda: None,
        discovered_pipeline_factory=lambda: None,
    )

    with pytest.raises(ReportExecutionError, match="unsupported workflow dispatch operation"):
        run_async(service.run_dispatch_payload_locally({"operation": "run_sideways"}))


def run_async(coro):
    import asyncio

    return asyncio.run(coro)
