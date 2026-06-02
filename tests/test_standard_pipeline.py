import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.models.schemas import ReportRequest, ReportResponse
from app.services.persistence import AnalysisRunRepository
from app.services.report_generator import ReportExecutionError
from app.services.standard_pipeline import StandardReportPipelineService
from app.services.workflow_checkpoint import WorkflowCheckpointRecorder


@contextmanager
def fake_session_scope():
    yield object()


class FakeRun:
    id = 77


class FakeAnalysisRunRepository:
    started = {}

    def __init__(self, session):
        pass

    def start(self, source, payload):
        FakeAnalysisRunRepository.started = {"source": source, "payload": payload}
        return FakeRun()


class FakeReport:
    id = 88


class FakeReportRepository:
    stored = {}

    def __init__(self, session):
        pass

    def create(self, request, response):
        FakeReportRepository.stored = {
            "request": request.model_dump(mode="json"),
            "title": response.title,
        }
        return FakeReport()


class FakeIngestionPipeline:
    async def pre_report_refresh(self, request):
        return {
            "news": {"count": 3},
            "company_filings": {"stored_count": 2},
        }


class FakeReportBuildService:
    def build(self, request, *, source_count=None):
        return {
            "response": ReportResponse(title="AI 產業鏈 自動分析報告", markdown="# report"),
            "quality_gate": {"status": "ready"},
            "report_execution": {"evidence_count": 3},
            "evidence_count": 3,
        }


class FakeWorkflowRecorder:
    def __init__(self):
        self.events = []

    def initialize(self, run_id, name, steps):
        self.events.append(("initialize", run_id, name, list(steps)))

    def start_step(self, run_id, step, summary=None):
        self.events.append(("start", step, summary or {}))

    def complete_step(self, run_id, step, summary=None):
        self.events.append(("complete", step, summary or {}))

    def fail_step(self, run_id, step, error, summary=None):
        self.events.append(("fail", step, error))

    def complete_workflow_payload(self, run_id, payload):
        return {**payload, "workflow": {"name": "standard_report_pipeline", "status": "success"}}


def test_standard_pipeline_service_runs_report_and_auto_follow_up() -> None:
    workflow = FakeWorkflowRecorder()
    captured = {}

    async def auto_follow_up(report_id):
        return {
            "status": "started",
            "source_report_id": report_id,
            "source_report_topic": "AI 產業鏈",
            "source_report_tickers": ["2330"],
            "rerun_report": {"report_id": 99, "request": {"topic": "AI 產業鏈", "tickers": ["2330"]}},
        }

    def safe_update(run_id, payload, report_id):
        captured["safe_update"] = {"run_id": run_id, "payload": payload, "report_id": report_id}
        return True

    service = _service(
        workflow_recorder_factory=lambda: workflow,
        auto_follow_up_func=auto_follow_up,
        safe_update_run_success_func=safe_update,
    )

    result = run_async(service.run(ReportRequest(topic="AI 產業鏈", tickers=["2330"])))

    assert result["run_id"] == 77
    assert result["report_id"] == 88
    assert result["active_report_id"] == 99
    assert result["run_record_updated"] is True
    assert FakeAnalysisRunRepository.started["source"] == "pipeline_api"
    assert captured["safe_update"]["payload"]["workflow"]["status"] == "success"
    assert ("complete", "auto_follow_up", {"status": "started", "rerun_report_id": 99}) in workflow.events


def test_standard_pipeline_service_marks_run_failed_on_report_error() -> None:
    workflow = FakeWorkflowRecorder()
    captured = {}

    class FailingReportBuildService:
        def build(self, request, *, source_count=None):
            raise ReportExecutionError("bad report")

    def safe_failed(run_id, error):
        captured["failed"] = {"run_id": run_id, "error": error}

    service = _service(
        workflow_recorder_factory=lambda: workflow,
        report_build_service_factory=lambda: FailingReportBuildService(),
        safe_mark_run_failed_func=safe_failed,
    )

    with pytest.raises(ReportExecutionError):
        run_async(service.run(ReportRequest(topic="AI 產業鏈", tickers=["2330"])))

    assert captured["failed"] == {"run_id": 77, "error": "bad report"}
    assert ("fail", "report_build", "bad report") in workflow.events


def test_standard_pipeline_service_resumes_failed_report_build_from_checkpoint() -> None:
    workflow = FakeWorkflowRecorder()
    captured = {}
    payload = WorkflowCheckpointRecorder.initialize_payload(
        ReportRequest(topic="AI 產業鏈", tickers=["2330"]).model_dump(mode="json"),
        "standard_report_pipeline",
        ["pre_report_refresh", "report_build", "auto_follow_up"],
        "2026-05-31T09:00:00",
    )
    payload = WorkflowCheckpointRecorder.complete_step_payload(
        payload,
        "pre_report_refresh",
        "2026-05-31T09:01:00",
        {"news_count": 5, "company_filing_count": 2},
    )
    payload = WorkflowCheckpointRecorder.fail_step_payload(
        payload,
        "report_build",
        "bad report",
        "2026-05-31T09:02:00",
    )

    class ExistingRunRepository(FakeAnalysisRunRepository):
        def get(self, run_id):
            assert run_id == 77
            return SimpleNamespace(id=77, payload_json=json.dumps(payload), report_id=None)

        def mark_running(self, run_id):
            captured["mark_running"] = run_id

    class NoRefreshIngestionPipeline:
        async def pre_report_refresh(self, request):
            raise AssertionError("completed pre_report_refresh should be reused from checkpoint")

    class CapturingReportBuildService:
        def build(self, request, *, source_count=None):
            captured["build"] = {
                "request": request.model_dump(mode="json"),
                "source_count": source_count,
            }
            return {
                "response": ReportResponse(title="AI 產業鏈 自動分析報告", markdown="# resumed"),
                "quality_gate": {"status": "ready"},
                "report_execution": {"evidence_count": 5},
                "evidence_count": 5,
            }

    async def auto_follow_up(report_id):
        return {"status": "not_needed", "source_report_id": report_id}

    def safe_update(run_id, payload, report_id):
        captured["safe_update"] = {"run_id": run_id, "payload": payload, "report_id": report_id}
        return True

    service = _service(
        analysis_run_repository_cls=ExistingRunRepository,
        ingestion_pipeline_cls=NoRefreshIngestionPipeline,
        report_build_service_factory=lambda: CapturingReportBuildService(),
        workflow_recorder_factory=lambda: workflow,
        auto_follow_up_func=auto_follow_up,
        safe_update_run_success_func=safe_update,
    )

    result = run_async(service.resume(77))

    assert captured["mark_running"] == 77
    assert captured["build"]["source_count"] == 5
    assert result["run_id"] == 77
    assert result["report_id"] == 88
    assert result["resumed_from_step"] == "report_build"
    assert result["ingestion"]["resumed_from_checkpoint"] is True
    assert captured["safe_update"]["payload"]["resumed_from_step"] == "report_build"
    assert ("start", "report_build", {}) in workflow.events
    assert ("complete", "report_build", {"report_id": 88, "quality_gate_status": "ready", "evidence_count": 5}) in workflow.events


def test_standard_pipeline_service_rejects_non_resumable_workflow() -> None:
    payload = WorkflowCheckpointRecorder.initialize_payload(
        ReportRequest(topic="AI 產業鏈", tickers=["2330"]).model_dump(mode="json"),
        "standard_report_pipeline",
        ["pre_report_refresh"],
        "2026-05-31T09:00:00",
    )
    payload["workflow"]["status"] = "success"
    payload["workflow"]["resume"] = WorkflowCheckpointRecorder.resume_state(payload["workflow"])

    class ExistingRunRepository(FakeAnalysisRunRepository):
        def get(self, run_id):
            return SimpleNamespace(id=run_id, payload_json=json.dumps(payload), report_id=None)

    service = _service(analysis_run_repository_cls=ExistingRunRepository)

    with pytest.raises(ReportExecutionError, match="not resumable"):
        run_async(service.resume(77))


def test_standard_pipeline_resume_updates_existing_run_state_with_real_checkpoint() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    captured = {}

    @contextmanager
    def session_scope():
        session = session_factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"])
    with session_scope() as session:
        repository = AnalysisRunRepository(session)
        run = repository.start("pipeline_api", request.model_dump(mode="json"))
        run_id = run.id

    recorder = WorkflowCheckpointRecorder(session_scope_factory=session_scope)
    recorder.initialize(run_id, "standard_report_pipeline", ["pre_report_refresh", "report_build", "auto_follow_up"])
    recorder.complete_step(run_id, "pre_report_refresh", {"news_count": 4, "company_filing_count": 1})
    recorder.fail_step(run_id, "report_build", "bad report")
    with session_scope() as session:
        AnalysisRunRepository(session).mark_failed(run_id, "bad report")

    class CapturingReportBuildService:
        def build(self, request, *, source_count=None):
            captured["source_count"] = source_count
            return {
                "response": ReportResponse(title="AI 產業鏈 自動分析報告", markdown="# resumed"),
                "quality_gate": {"status": "ready"},
                "report_execution": {"evidence_count": 4},
                "evidence_count": 4,
            }

    class FakeReportRepository:
        def __init__(self, session):
            pass

        def create(self, request, response):
            return SimpleNamespace(id=123)

    def safe_update(run_id, payload, report_id):
        with session_scope() as session:
            repository = AnalysisRunRepository(session)
            repository.update_payload(run_id, payload)
            repository.mark_success(run_id, report_id)
        return True

    async def auto_follow_up(report_id):
        return {"status": "not_needed", "source_report_id": report_id}

    service = _service(
        session_scope_factory=session_scope,
        analysis_run_repository_cls=AnalysisRunRepository,
        report_repository_cls=FakeReportRepository,
        report_build_service_factory=lambda: CapturingReportBuildService(),
        workflow_recorder_factory=lambda: WorkflowCheckpointRecorder(session_scope_factory=session_scope),
        safe_update_run_success_func=safe_update,
        auto_follow_up_func=auto_follow_up,
    )

    result = run_async(service.resume(run_id))

    with session_scope() as session:
        resumed = AnalysisRunRepository(session).get(run_id)
        payload = json.loads(resumed.payload_json)

    assert captured["source_count"] == 4
    assert result["run_id"] == run_id
    assert result["report_id"] == 123
    assert resumed.status == "success"
    assert resumed.error is None
    assert payload["workflow"]["status"] == "success"
    assert payload["workflow"]["resume"]["resumable"] is False
    assert payload["workflow"]["steps"][2]["summary"]["status"] == "not_needed"
    assert payload["resumed_from_step"] == "report_build"


def _service(**overrides) -> StandardReportPipelineService:
    async def noop_auto_follow_up(report_id):
        return {"status": "not_needed"}

    defaults = {
        "session_scope_factory": fake_session_scope,
        "analysis_run_repository_cls": FakeAnalysisRunRepository,
        "report_repository_cls": FakeReportRepository,
        "ingestion_pipeline_cls": FakeIngestionPipeline,
        "report_build_service_factory": lambda: FakeReportBuildService(),
        "workflow_recorder_factory": FakeWorkflowRecorder,
        "auto_follow_up_func": noop_auto_follow_up,
        "safe_update_run_success_func": lambda run_id, payload, report_id: True,
        "safe_mark_run_failed_func": lambda run_id, error: None,
        "workflow_steps": ["pre_report_refresh", "report_build", "auto_follow_up"],
    }
    defaults.update(overrides)
    return StandardReportPipelineService(**defaults)


def run_async(coro):
    import asyncio

    return asyncio.run(coro)
