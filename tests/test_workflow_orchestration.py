import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.services.workflow_orchestration import (
    WorkflowOrchestrationError,
    WorkflowOrchestrationRunner,
    dispatch_airflow_dag,
    dispatch_temporal_workflow,
    workflow_orchestration_status,
)


def run_async(coro):
    import asyncio

    return asyncio.run(coro)


def test_workflow_orchestration_status_defaults_to_local_checkpoint() -> None:
    status = workflow_orchestration_status(SimpleNamespace(workflow_engine="local"))

    assert status["ready"] is True
    assert status["engine"] == "local"
    assert status["mode"] == "local_checkpoint"
    assert status["external_engine"] is False
    assert status["checkpoint_store"] == "analysis_run.payload_json"
    assert status["workflow_payload_version"] == 2
    assert status["configuration"]["recoverable_from_analysis_run"] is True
    assert status["configuration"]["run_api_resume_summary_enabled"] is True
    assert status["local_fallback_enabled"] is True


def test_workflow_orchestration_status_reports_prefect_dependency() -> None:
    settings = SimpleNamespace(workflow_engine="prefect", prefect_api_url="http://prefect.local/api")

    status = workflow_orchestration_status(
        settings,
        dependency_checker=lambda dependency: dependency == "prefect",
    )

    assert status["ready"] is True
    assert status["engine"] == "prefect"
    assert status["dependency"] == "prefect"
    assert status["dependency_available"] is True
    assert status["configuration"]["api_url_configured"] is True
    assert status["fallback_reason"] is None


def test_workflow_orchestration_status_reports_temporal_missing_settings() -> None:
    settings = SimpleNamespace(
        workflow_engine="temporal",
        temporal_address="",
        temporal_namespace="default",
        temporal_task_queue="",
        temporal_workflow_name="StockAnalysisPipeline",
    )

    status = workflow_orchestration_status(
        settings,
        dependency_checker=lambda dependency: dependency == "temporalio",
    )

    assert status["ready"] is False
    assert status["dependency_available"] is True
    assert status["fallback_reason"] == "missing_settings:temporal_address,temporal_task_queue"


def test_workflow_orchestration_status_reports_temporal_dispatch_ready() -> None:
    settings = SimpleNamespace(
        workflow_engine="temporal",
        temporal_address="localhost:7233",
        temporal_namespace="default",
        temporal_task_queue="stock-analysis",
        temporal_workflow_name="StockAnalysisPipeline",
        temporal_ui_url="http://temporal.local",
        temporal_timeout_seconds=12,
    )

    status = workflow_orchestration_status(
        settings,
        dependency_checker=lambda dependency: dependency == "temporalio",
    )

    assert status["ready"] is True
    assert status["engine"] == "temporal"
    assert status["configuration"]["workflow_name"] == "StockAnalysisPipeline"
    assert status["configuration"]["ui_url"] == "http://temporal.local"
    assert status["configuration"]["timeout_seconds"] == 12
    assert status["fallback_reason"] is None


def test_workflow_orchestration_status_reports_unsupported_engine() -> None:
    status = workflow_orchestration_status(SimpleNamespace(workflow_engine="unknown"))

    assert status["ready"] is False
    assert status["mode"] == "unsupported"
    assert status["fallback_reason"] == "unsupported_engine:unknown"


def test_workflow_orchestration_runner_uses_local_checkpoint_by_default() -> None:
    async def local_runner():
        return {"report_id": 7}

    runner = WorkflowOrchestrationRunner(
        settings_provider=lambda: SimpleNamespace(workflow_engine="local"),
    )

    result = run_async(runner.run("standard_report_pipeline", local_runner))

    assert result["report_id"] == 7
    assert result["workflow_orchestration"] == {
        "requested_engine": "local",
        "executed_engine": "local",
        "mode": "local_checkpoint",
        "external_engine": False,
        "fallback_reason": None,
        "local_fallback_enabled": True,
        "external_run_id": None,
        "external_url": None,
    }


def test_workflow_orchestration_runner_wraps_ready_prefect_flow() -> None:
    captured = {}

    async def local_runner():
        captured["local_called"] = True
        return {"report_id": 8}

    async def fake_prefect_runner(workflow_name, runner):
        captured["workflow_name"] = workflow_name
        payload = await runner()
        return {**payload, "prefect_flow_id": "flow-1"}

    runner = WorkflowOrchestrationRunner(
        settings_provider=lambda: SimpleNamespace(workflow_engine="prefect"),
        status_provider=lambda settings: {"engine": "prefect", "ready": True},
        prefect_flow_runner=fake_prefect_runner,
    )

    result = run_async(runner.run("standard_report_pipeline", local_runner))

    assert captured == {"workflow_name": "standard_report_pipeline", "local_called": True}
    assert result["prefect_flow_id"] == "flow-1"
    assert result["workflow_orchestration"]["requested_engine"] == "prefect"
    assert result["workflow_orchestration"]["executed_engine"] == "prefect"
    assert result["workflow_orchestration"]["external_engine"] is True
    assert result["workflow_orchestration"]["local_fallback_enabled"] is True


def test_workflow_orchestration_runner_falls_back_when_external_engine_not_ready() -> None:
    async def local_runner():
        return {"report_id": 9}

    runner = WorkflowOrchestrationRunner(
        settings_provider=lambda: SimpleNamespace(workflow_engine="temporal"),
        status_provider=lambda settings: {
            "engine": "temporal",
            "ready": False,
            "fallback_reason": "missing_dependency:temporalio",
        },
    )

    result = run_async(runner.run("ai_discovered_topic_pipeline", local_runner))

    assert result["report_id"] == 9
    assert result["workflow_orchestration"]["requested_engine"] == "temporal"
    assert result["workflow_orchestration"]["executed_engine"] == "local"
    assert result["workflow_orchestration"]["mode"] == "local_checkpoint_fallback"
    assert result["workflow_orchestration"]["fallback_reason"] == "missing_dependency:temporalio"
    assert result["workflow_orchestration"]["local_fallback_enabled"] is True


def test_workflow_orchestration_status_reports_airflow_rest_dispatch_ready() -> None:
    settings = SimpleNamespace(
        workflow_engine="airflow",
        airflow_api_url="https://airflow.example/api/v1",
        airflow_dag_id="stock_pipeline",
        airflow_api_token="token",
        airflow_username="",
        airflow_password=None,
        airflow_timeout_seconds=12,
    )

    status = workflow_orchestration_status(
        settings,
        dependency_checker=lambda dependency: False,
    )

    assert status["ready"] is True
    assert status["engine"] == "airflow"
    assert status["dependency"] == "airflow_rest_api"
    assert status["dependency_available"] is True
    assert status["configuration"]["dag_id"] == "stock_pipeline"
    assert status["configuration"]["api_token_configured"] is True
    assert status["configuration"]["timeout_seconds"] == 12
    assert status["fallback_reason"] is None


def test_workflow_orchestration_status_reports_airflow_missing_dag_id() -> None:
    settings = SimpleNamespace(
        workflow_engine="airflow",
        airflow_api_url="https://airflow.example",
        airflow_dag_id="",
    )

    status = workflow_orchestration_status(settings)

    assert status["ready"] is False
    assert status["fallback_reason"] == "missing_settings:airflow_dag_id"


def test_workflow_orchestration_runner_dispatches_ready_airflow_without_local_execution() -> None:
    captured = {}

    async def local_runner():
        raise AssertionError("Airflow dispatch should not execute the local runner")

    async def fake_airflow_dispatcher(workflow_name, dispatch_payload, settings):
        captured["workflow_name"] = workflow_name
        captured["dispatch_payload"] = dispatch_payload
        captured["settings"] = settings
        return {
            "status": "dispatched",
            "run_id": 77,
            "external_run_id": "dag-run-1",
            "external_url": "https://airflow.example/dags/stock/grid?dag_run_id=dag-run-1",
        }

    settings = SimpleNamespace(workflow_engine="airflow", workflow_local_fallback_enabled=False)
    runner = WorkflowOrchestrationRunner(
        settings_provider=lambda: settings,
        status_provider=lambda received: {"engine": "airflow", "ready": True},
        airflow_dispatcher=fake_airflow_dispatcher,
    )

    result = run_async(
        runner.run(
            "standard_report_pipeline",
            local_runner,
            dispatch_payload={"operation": "resume_standard", "run_id": 77},
        )
    )

    assert captured["workflow_name"] == "standard_report_pipeline"
    assert captured["dispatch_payload"] == {"operation": "resume_standard", "run_id": 77}
    assert captured["settings"] is settings
    assert result["status"] == "dispatched"
    assert result["workflow_orchestration"]["requested_engine"] == "airflow"
    assert result["workflow_orchestration"]["executed_engine"] == "airflow"
    assert result["workflow_orchestration"]["mode"] == "airflow_dag_dispatch"
    assert result["workflow_orchestration"]["external_run_id"] == "dag-run-1"
    assert result["workflow_orchestration"]["external_url"].startswith("https://airflow.example")


def test_workflow_orchestration_runner_dispatches_ready_temporal_without_local_execution() -> None:
    captured = {}

    async def local_runner():
        raise AssertionError("Temporal dispatch should not execute the local runner")

    async def fake_temporal_dispatcher(workflow_name, dispatch_payload, settings):
        captured["workflow_name"] = workflow_name
        captured["dispatch_payload"] = dispatch_payload
        captured["settings"] = settings
        return {
            "status": "dispatched",
            "run_id": 77,
            "external_run_id": "temporal-run-1",
            "external_url": "http://temporal.local/namespaces/default/workflows/stock-run",
        }

    settings = SimpleNamespace(workflow_engine="temporal", workflow_local_fallback_enabled=False)
    runner = WorkflowOrchestrationRunner(
        settings_provider=lambda: settings,
        status_provider=lambda received: {"engine": "temporal", "ready": True},
        temporal_dispatcher=fake_temporal_dispatcher,
    )

    result = run_async(
        runner.run(
            "standard_report_pipeline",
            local_runner,
            dispatch_payload={"operation": "resume_standard", "run_id": 77},
        )
    )

    assert captured["workflow_name"] == "standard_report_pipeline"
    assert captured["dispatch_payload"] == {"operation": "resume_standard", "run_id": 77}
    assert captured["settings"] is settings
    assert result["status"] == "dispatched"
    assert result["workflow_orchestration"]["requested_engine"] == "temporal"
    assert result["workflow_orchestration"]["executed_engine"] == "temporal"
    assert result["workflow_orchestration"]["mode"] == "temporal_workflow_dispatch"
    assert result["workflow_orchestration"]["external_run_id"] == "temporal-run-1"
    assert result["workflow_orchestration"]["external_url"].startswith("http://temporal.local")


def test_workflow_orchestration_runner_raises_when_external_engine_not_ready_and_fallback_disabled() -> None:
    async def local_runner():
        raise AssertionError("local fallback must not execute")

    runner = WorkflowOrchestrationRunner(
        settings_provider=lambda: SimpleNamespace(
            workflow_engine="airflow",
            workflow_local_fallback_enabled=False,
        ),
        status_provider=lambda settings: {
            "engine": "airflow",
            "ready": False,
            "fallback_reason": "missing_settings:airflow_api_url",
        },
    )

    with pytest.raises(WorkflowOrchestrationError) as exc:
        run_async(runner.run("standard_report_pipeline", local_runner))

    assert exc.value.engine == "airflow"
    assert exc.value.reason == "missing_settings:airflow_api_url"


def test_workflow_orchestration_runner_propagates_temporal_dispatch_errors() -> None:
    async def local_runner():
        raise AssertionError("local fallback must not execute")

    async def fake_temporal_dispatcher(workflow_name, dispatch_payload, settings):
        raise WorkflowOrchestrationError(
            engine="temporal",
            reason="temporal_dispatch_failed:worker unavailable",
        )

    runner = WorkflowOrchestrationRunner(
        settings_provider=lambda: SimpleNamespace(
            workflow_engine="temporal",
            workflow_local_fallback_enabled=False,
        ),
        status_provider=lambda settings: {
            "engine": "temporal",
            "ready": True,
            "fallback_reason": None,
        },
        temporal_dispatcher=fake_temporal_dispatcher,
    )

    with pytest.raises(WorkflowOrchestrationError) as exc:
        run_async(runner.run("standard_report_pipeline", local_runner))

    assert exc.value.reason == "temporal_dispatch_failed:worker unavailable"


def test_dispatch_temporal_workflow_starts_configured_workflow(monkeypatch) -> None:
    captured = {}

    class FakeHandle:
        id = "temporal-workflow-id"
        result_run_id = "temporal-run-id"

    class FakeClient:
        @classmethod
        async def connect(cls, address, namespace):
            captured["connect"] = {"address": address, "namespace": namespace}
            return cls()

        async def start_workflow(self, workflow, payload, id, task_queue):
            captured["start"] = {
                "workflow": workflow,
                "payload": payload,
                "id": id,
                "task_queue": task_queue,
            }
            return FakeHandle()

    temporalio_module = ModuleType("temporalio")
    temporalio_module.__path__ = []
    client_module = ModuleType("temporalio.client")
    client_module.Client = FakeClient
    monkeypatch.setitem(sys.modules, "temporalio", temporalio_module)
    monkeypatch.setitem(sys.modules, "temporalio.client", client_module)
    settings = SimpleNamespace(
        temporal_address="localhost:7233",
        temporal_namespace="default",
        temporal_task_queue="stock-analysis",
        temporal_workflow_name="StockAnalysisPipeline",
        temporal_ui_url="http://temporal.local",
        temporal_timeout_seconds=5,
    )

    result = run_async(
        dispatch_temporal_workflow(
            "standard_report_pipeline",
            {"operation": "resume_standard", "run_id": 77},
            settings,
        )
    )

    assert captured["connect"] == {"address": "localhost:7233", "namespace": "default"}
    assert captured["start"]["workflow"] == "StockAnalysisPipeline"
    assert captured["start"]["payload"] == {
        "workflow_name": "standard_report_pipeline",
        "payload": {"operation": "resume_standard", "run_id": 77},
    }
    assert captured["start"]["id"].startswith("stock-standard_report_pipeline-run-77-")
    assert captured["start"]["task_queue"] == "stock-analysis"
    assert result["status"] == "dispatched"
    assert result["run_id"] == 77
    assert result["external_workflow_id"] == "temporal-workflow-id"
    assert result["external_run_id"] == "temporal-run-id"
    assert result["external_url"] == (
        "http://temporal.local/namespaces/default/workflows/temporal-workflow-id"
    )


def test_dispatch_airflow_dag_posts_to_airflow_rest_api(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"dag_run_id": "airflow-run-1", "state": "queued"}

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, endpoint, json, headers, auth):
            captured["endpoint"] = endpoint
            captured["json"] = json
            captured["headers"] = headers
            captured["auth"] = auth
            return FakeResponse()

    monkeypatch.setattr("app.services.workflow_orchestration.httpx.AsyncClient", FakeAsyncClient)
    settings = SimpleNamespace(
        airflow_api_url="https://airflow.example/api/v1",
        airflow_dag_id="stock_pipeline",
        airflow_api_token="token",
        airflow_username="",
        airflow_password=None,
        airflow_timeout_seconds=5,
    )

    result = run_async(
        dispatch_airflow_dag(
            "standard_report_pipeline",
            {"operation": "resume_standard", "run_id": 77},
            settings,
        )
    )

    assert captured["endpoint"] == "https://airflow.example/api/v1/dags/stock_pipeline/dagRuns"
    assert captured["headers"] == {"Authorization": "Bearer token"}
    assert captured["auth"] is None
    assert captured["json"]["conf"]["workflow_name"] == "standard_report_pipeline"
    assert captured["json"]["conf"]["payload"] == {"operation": "resume_standard", "run_id": 77}
    assert captured["json"]["dag_run_id"].startswith("stock__standard_report_pipeline__run_77__")
    assert result["status"] == "dispatched"
    assert result["run_id"] == 77
    assert result["external_run_id"] == "airflow-run-1"
