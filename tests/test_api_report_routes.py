from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.report_routes import create_report_router
from app.models.schemas import ReportResponse


class FakeReportExecutionError(Exception):
    pass


class FakeWorkflowOrchestrationError(Exception):
    pass


class FakeReportQueryNotFound(Exception):
    pass


class FakeCompanyDataAuditNotFound(Exception):
    pass


class FakeTaskQueueUnavailableError(Exception):
    pass


def test_report_router_delegates_report_generation_and_queries() -> None:
    captured = {}

    class FakeGenerationApi:
        def generate(self, request) -> ReportResponse:
            captured["request"] = request.model_dump(mode="json")
            return ReportResponse(title="AI 產業鏈報告", markdown="# report")

    class FakeReportQuery:
        def list_reports(self, limit: int) -> list[dict]:
            captured["limit"] = limit
            return [{"report_id": 7}]

        def get_report(self, report_id: int) -> dict:
            captured["report_id"] = report_id
            return {"report_id": report_id}

    client = _client(generation_api=FakeGenerationApi(), report_query=FakeReportQuery())

    generated = client.post("/reports/generate", json={"topic": "AI 產業鏈", "tickers": ["2330"]})
    listed = client.get("/reports?limit=3")
    fetched = client.get("/reports/7")

    assert generated.status_code == 200
    assert generated.json()["title"] == "AI 產業鏈報告"
    assert captured["request"]["topic"] == "AI 產業鏈"
    assert listed.json() == [{"report_id": 7}]
    assert captured["limit"] == 3
    assert fetched.json() == {"report_id": 7}


def test_report_router_maps_generation_and_lookup_errors() -> None:
    class FakeGenerationApi:
        def generate(self, request) -> ReportResponse:
            raise FakeWorkflowOrchestrationError("workflow unavailable")

    class FakeReportQuery:
        def get_report(self, report_id: int) -> dict:
            raise FakeReportQueryNotFound("report not found")

        def candidate_audit(self, report_id: int) -> dict:
            raise FakeReportQueryNotFound("audit not found")

        def delete_report(self, report_id: int) -> dict:
            raise FakeReportQueryNotFound("delete target not found")

    class FakeCompanyDataAuditApi:
        def report_company_data_audit(self, report_id: int) -> dict:
            raise FakeCompanyDataAuditNotFound("company audit not found")

    client = _client(
        generation_api=FakeGenerationApi(),
        report_query=FakeReportQuery(),
        company_data_audit_api=FakeCompanyDataAuditApi(),
    )

    assert client.post("/reports/generate", json={"topic": "AI 產業鏈", "tickers": ["2330"]}).status_code == 503
    assert client.get("/reports/7").status_code == 404
    assert client.get("/reports/7/candidate-audit").status_code == 404
    assert client.get("/reports/7/company-data-audit").status_code == 404
    assert client.delete("/reports/7").status_code == 404


def test_report_router_delegates_follow_up_callbacks() -> None:
    captured = {}

    def plan(report_id: int) -> dict:
        captured["plan_report_id"] = report_id
        return {"summary": {"required_count": 1}}

    async def auto_start(report_id: int) -> dict:
        captured["auto_start_report_id"] = report_id
        return {"status": "queued", "source_report_id": report_id}

    async def run_follow_up(report_id: int, payload) -> dict:
        captured["run_report_id"] = report_id
        captured["payload"] = payload.model_dump(mode="json") if payload else None
        return {"status": "executed", "source_report_id": report_id}

    client = _client(
        get_follow_up_plan_func=plan,
        auto_start_follow_up_func=auto_start,
        run_follow_up_func=run_follow_up,
    )

    plan_response = client.get("/reports/7/follow-up/plan")
    auto_start_response = client.post("/reports/7/follow-up/auto-start")
    run_response = client.post("/reports/7/follow-up/run", json={"rerun_report": True, "purpose": "required"})

    assert plan_response.json() == {"summary": {"required_count": 1}}
    assert auto_start_response.json() == {"status": "queued", "source_report_id": 7}
    assert run_response.json() == {"status": "executed", "source_report_id": 7}
    assert captured["plan_report_id"] == 7
    assert captured["auto_start_report_id"] == 7
    assert captured["run_report_id"] == 7
    assert captured["payload"]["rerun_report"] is True
    assert captured["payload"]["purpose"] == "required"


def test_report_router_queues_follow_up_task() -> None:
    captured = {}

    class FakeRunTaskApi:
        def queue_report_follow_up(self, report_id: int, payload: dict) -> dict:
            captured["report_id"] = report_id
            captured["payload"] = payload
            return {"task_id": "follow-task", "status": "queued"}

    client = _client(run_task_api=FakeRunTaskApi())

    response = client.post(
        "/reports/7/follow-up/run_async",
        json={"rerun_report": True, "purpose": "required", "news_limit": 20},
    )

    assert response.status_code == 200
    assert response.json() == {"task_id": "follow-task", "status": "queued"}
    assert captured["report_id"] == 7
    assert captured["payload"]["rerun_report"] is True
    assert captured["payload"]["purpose"] == "required"
    assert captured["payload"]["news_limit"] == 20


def test_report_router_maps_follow_up_queue_errors_to_503() -> None:
    class FakeRunTaskApi:
        def queue_report_follow_up(self, report_id: int, payload: dict) -> dict:
            raise FakeTaskQueueUnavailableError("task queue unavailable")

    client = _client(run_task_api=FakeRunTaskApi())

    response = client.post("/reports/7/follow-up/run_async")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "task_queue_unavailable"
    assert detail["message"] == "task queue unavailable"
    assert detail["operation"] == "report_follow_up"
    assert detail["retryable"] is True
    assert detail["next_steps"]


def _client(
    generation_api=None,
    report_query=None,
    company_data_audit_api=None,
    run_task_api=None,
    get_follow_up_plan_func=None,
    auto_start_follow_up_func=None,
    run_follow_up_func=None,
) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_report_router(
            _services(
                generation_api=generation_api,
                report_query=report_query,
                company_data_audit_api=company_data_audit_api,
                run_task_api=run_task_api,
            ),
            report_execution_error_cls=FakeReportExecutionError,
            workflow_orchestration_error_cls=FakeWorkflowOrchestrationError,
            report_query_not_found_cls=FakeReportQueryNotFound,
            company_data_audit_not_found_cls=FakeCompanyDataAuditNotFound,
            task_queue_unavailable_error_cls=FakeTaskQueueUnavailableError,
            get_follow_up_plan_func=get_follow_up_plan_func or (lambda report_id: {}),
            auto_start_follow_up_func=auto_start_follow_up_func or _noop_auto_start,
            run_follow_up_func=run_follow_up_func or _noop_run,
        )
    )
    return TestClient(app)


async def _noop_auto_start(report_id: int) -> dict:
    return {"status": "skipped", "source_report_id": report_id}


async def _noop_run(report_id: int, payload) -> dict:
    return {"status": "skipped", "source_report_id": report_id}


def _services(generation_api=None, report_query=None, company_data_audit_api=None, run_task_api=None):
    class FakeServices:
        def sync_report_generation_api(self):
            return generation_api

        def report_query(self):
            return report_query

        def company_data_audit_api(self):
            return company_data_audit_api

        def run_task_api(self):
            return run_task_api

    return FakeServices()
