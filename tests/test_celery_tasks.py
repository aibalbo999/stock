import json
from contextlib import contextmanager
from types import SimpleNamespace

from app.models.schemas import ReportResponse
from app.tasks import tasks
from app.tasks.tasks import build_run_payload


def test_build_run_payload_includes_task_id_and_ingestion() -> None:
    payload = {"topic": "AI 產業鏈", "tickers": ["2330"], "lookback_days": 7}
    ingestion = {"news": {"count": 0}, "market": {"requested_tickers": ["2330"]}}

    assert build_run_payload(payload, "task-123", ingestion) == {
        "request": payload,
        "celery_task_id": "task-123",
        "ingestion": ingestion,
    }


def test_build_run_payload_omits_empty_optional_fields() -> None:
    payload = {"topic": "AI 產業鏈"}

    assert build_run_payload(payload) == {"request": payload}


def test_generate_report_task_records_workflow_checkpoints(monkeypatch, tmp_path) -> None:
    class FakeRun:
        id = 101
        payload_json = "{}"
        status = "running"
        report_id = None
        output_path = None
        error = None

    class FakeAnalysisRunRepository:
        run = FakeRun()

        def __init__(self, session):
            self.session = session

        def start(self, source, payload):
            assert source == "celery"
            self.run.payload_json = json.dumps(payload, ensure_ascii=False)
            return self.run

        def get(self, run_id):
            assert run_id == self.run.id
            return self.run

        def update_payload(self, run_id, payload):
            assert run_id == self.run.id
            self.run.payload_json = json.dumps(payload, ensure_ascii=False)
            return self.run

        def mark_success(self, run_id, report_id, output_path=None):
            assert run_id == self.run.id
            self.run.status = "success"
            self.run.report_id = report_id
            self.run.output_path = output_path
            return self.run

        def mark_failed(self, run_id, error):
            self.run.status = "failed"
            self.run.error = error
            return self.run

    class FakeIngestionPipeline:
        async def pre_report_refresh(self, request):
            assert request.topic == "AI 產業鏈"
            return {"news": {"count": 5}, "company_filings": {"stored_count": 2}}

    class FakeReportBuildService:
        def build(self, request, source_count=None):
            assert source_count == 5
            return {
                "response": ReportResponse(title="AI report", markdown="# AI report"),
                "quality_gate": {"status": "ready"},
                "report_execution": {"evidence_count": 3},
                "evidence_count": 3,
            }

    class FakeReport:
        id = 202

    class FakeReportRepository:
        def __init__(self, session):
            self.session = session

        def create(self, request, response):
            return FakeReport()

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(tasks, "init_db", lambda: None)
    monkeypatch.setattr(tasks, "session_scope", fake_session_scope)
    monkeypatch.setattr(tasks, "AnalysisRunRepository", FakeAnalysisRunRepository)
    monkeypatch.setattr(tasks, "IngestionPipeline", FakeIngestionPipeline)
    monkeypatch.setattr(tasks, "ReportBuildService", FakeReportBuildService)
    monkeypatch.setattr(tasks, "ReportRepository", FakeReportRepository)
    monkeypatch.setattr(tasks, "get_settings", lambda: SimpleNamespace(report_dir=tmp_path))

    result = tasks.generate_report_task.run({"topic": "AI 產業鏈", "tickers": ["2330"]})
    payload = json.loads(FakeAnalysisRunRepository.run.payload_json)
    workflow = payload["workflow"]
    statuses = {step["name"]: step["status"] for step in workflow["steps"]}

    assert result["run_id"] == 101
    assert result["id"] == 202
    assert workflow["name"] == "celery_report_task"
    assert workflow["status"] == "success"
    assert statuses["pre_report_refresh"] == "success"
    assert statuses["report_build"] == "success"
    assert statuses["report_persist"] == "success"
    assert payload["quality_gate"] == {"status": "ready"}
