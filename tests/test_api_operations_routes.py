from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.operations_routes import create_operations_router


class FakeAsyncReportValidationError(Exception):
    pass


class FakeRunTaskNotFound(Exception):
    pass


class FakeTaskQueueUnavailableError(Exception):
    pass


def test_operations_router_delegates_manual_news_and_market_refresh() -> None:
    captured = {}

    class FakeDataApi:
        def ingest_manual_news(self, **kwargs) -> dict:
            captured["manual"] = kwargs
            return {"document_id": "manual-1"}

        async def refresh_market(self, **kwargs) -> dict:
            captured["market"] = kwargs
            return {"stored_count": 2}

    client = _client(data_api=FakeDataApi())

    manual_response = client.post(
        "/ingest/manual",
        json={"title": "台積電新聞", "text": "台積電 AI 需求成長。", "publisher": "manual"},
    )
    market_response = client.post(
        "/market/refresh",
        json={"tickers": ["2330"], "start_date": "2026-05-01", "end_date": "2026-05-02"},
    )

    assert manual_response.status_code == 200
    assert manual_response.json() == {"document_id": "manual-1"}
    assert captured["manual"]["title"] == "台積電新聞"
    assert captured["manual"]["publisher"] == "manual"
    assert market_response.status_code == 200
    assert market_response.json() == {"stored_count": 2}
    assert captured["market"]["tickers"] == ["2330"]


def test_operations_router_delegates_schedule_sources_and_cleanup() -> None:
    captured = {}

    class FakeDataApi:
        def list_news_sources(self) -> list[dict]:
            return [{"name": "twse"}]

        def get_schedule(self) -> dict:
            return {"enabled": False}

        def update_schedule(self, config) -> dict:
            captured["schedule"] = config.model_dump(mode="json")
            return {"enabled": True}

        def market_cache_summary(self, tickers: str, limit_per_ticker: int) -> dict:
            captured["cache_summary"] = (tickers, limit_per_ticker)
            return {"market_snapshots": [{"ticker": "2330"}]}

        def maintenance_cleanup(self, **kwargs) -> dict:
            captured["cleanup"] = kwargs
            return {"failed_runs_deleted": 1}

    client = _client(data_api=FakeDataApi())

    assert client.get("/news/sources").json() == [{"name": "twse"}]
    assert client.get("/market/cache-summary?tickers=2330&limit_per_ticker=3").json() == {
        "market_snapshots": [{"ticker": "2330"}]
    }
    assert client.get("/schedule").json() == {"enabled": False}
    assert client.put("/schedule", json={"enabled": True, "tickers": ["2330"]}).json() == {"enabled": True}
    cleanup_response = client.post("/maintenance/cleanup", json={"failed_runs": True})

    assert cleanup_response.status_code == 200
    assert cleanup_response.json() == {"failed_runs_deleted": 1}
    assert captured["schedule"]["enabled"] is True
    assert captured["cache_summary"] == ("2330", 3)
    assert captured["cleanup"]["failed_runs"] is True


def test_operations_router_queues_discovered_and_data_tasks() -> None:
    captured = {}

    class FakeRunTaskApi:
        def generate_discovered_report_async(self, payload) -> dict:
            captured["discovered"] = payload.model_dump(mode="json")
            return {"task_id": "discover-task", "status": "queued"}

        def queue_data_operation(self, operation: str, payload: dict) -> dict:
            captured["data"] = {"operation": operation, "payload": payload}
            return {"task_id": "data-task", "status": "queued", "operation": operation}

    client = _client(run_task_api=FakeRunTaskApi())

    discovered_response = client.post(
        "/pipeline/run_discovered_async",
        json={"topic": "AI 產業鏈", "lookback_days": 14},
    )
    data_response = client.post(
        "/tasks/data-operation",
        json={"operation": "market_refresh", "payload": {"tickers": ["2330"]}},
    )

    assert discovered_response.status_code == 200
    assert discovered_response.json() == {"task_id": "discover-task", "status": "queued"}
    assert captured["discovered"]["topic"] == "AI 產業鏈"
    assert data_response.status_code == 200
    assert data_response.json() == {
        "task_id": "data-task",
        "status": "queued",
        "operation": "market_refresh",
    }
    assert captured["data"] == {"operation": "market_refresh", "payload": {"tickers": ["2330"]}}


def test_operations_router_maps_run_and_async_task_errors() -> None:
    class FakeRunTaskApi:
        def get_run(self, run_id: int) -> dict:
            raise FakeRunTaskNotFound("run not found")

        def generate_report_async(self, request) -> dict:
            raise FakeAsyncReportValidationError("async report generation requires at least one whitelisted ticker")

        def get_run_by_task_id(self, task_id: str) -> dict:
            raise FakeRunTaskNotFound("run not found for task")

    client = _client(run_task_api=FakeRunTaskApi())

    run_response = client.get("/runs/404")
    async_response = client.post("/reports/generate_async", json={"topic": "AI 產業鏈", "tickers": []})
    task_run_response = client.get("/tasks/missing/run")

    assert run_response.status_code == 404
    assert run_response.json()["detail"] == "run not found"
    assert async_response.status_code == 400
    assert "requires at least one" in async_response.json()["detail"]
    assert task_run_response.status_code == 404
    assert task_run_response.json()["detail"] == "run not found for task"


def test_operations_router_delegates_task_cancel_and_retry() -> None:
    captured = {}

    class FakeRunTaskApi:
        def cancel_task(self, task_id: str) -> dict:
            captured["cancel"] = task_id
            return {"task_id": task_id, "cancel_requested": True}

        def retry_task(self, task_id: str) -> dict:
            captured["retry"] = task_id
            return {"task_id": "retry-task", "retried_from_task_id": task_id}

    client = _client(run_task_api=FakeRunTaskApi())

    cancel_response = client.post("/tasks/task-123/cancel")
    retry_response = client.post("/tasks/task-123/retry")

    assert cancel_response.status_code == 200
    assert cancel_response.json()["cancel_requested"] is True
    assert retry_response.status_code == 200
    assert retry_response.json()["task_id"] == "retry-task"
    assert captured == {"cancel": "task-123", "retry": "task-123"}


def test_operations_router_maps_task_queue_errors_to_503() -> None:
    class FakeRunTaskApi:
        def queue_data_operation(self, operation: str, payload: dict) -> dict:
            raise FakeTaskQueueUnavailableError("task queue unavailable")

        def get_task_status(self, task_id: str) -> dict:
            raise FakeTaskQueueUnavailableError("task queue unavailable")

    client = _client(run_task_api=FakeRunTaskApi())

    queue_response = client.post(
        "/tasks/data-operation",
        json={"operation": "market_refresh", "payload": {"tickers": ["2330"]}},
    )
    status_response = client.get("/tasks/task-123")

    assert queue_response.status_code == 503
    queue_detail = queue_response.json()["detail"]
    assert queue_detail["code"] == "task_queue_unavailable"
    assert queue_detail["message"] == "task queue unavailable"
    assert queue_detail["operation"] == "market_refresh"
    assert queue_detail["retryable"] is True
    assert queue_detail["next_steps"]
    assert status_response.status_code == 503
    status_detail = status_response.json()["detail"]
    assert status_detail["code"] == "task_queue_unavailable"
    assert status_detail["operation"] == "task_status"


def _client(data_api=None, run_task_api=None) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_operations_router(
            _services(data_api=data_api, run_task_api=run_task_api),
            async_report_validation_error_cls=FakeAsyncReportValidationError,
            run_task_not_found_cls=FakeRunTaskNotFound,
            task_queue_unavailable_error_cls=FakeTaskQueueUnavailableError,
        )
    )
    return TestClient(app)


def _services(data_api=None, run_task_api=None):
    class FakeServices:
        def data_operations_api(self):
            return data_api

        def run_task_api(self):
            return run_task_api

    return FakeServices()
