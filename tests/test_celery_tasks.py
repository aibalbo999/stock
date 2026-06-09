import json
import asyncio
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

from app.models.schemas import ReportRequest, ReportResponse
from app.tasks import after_close_report_update, data_operations, report_generation, tasks
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


def test_data_operation_market_refresh_smoke_skips_market_provider(monkeypatch) -> None:
    class FakePipeline:
        async def refresh_market(self, *_args, **_kwargs):
            raise AssertionError("smoke payload must not call market data providers")

    monkeypatch.setattr(tasks, "_api_services_for_tasks", lambda: object())
    monkeypatch.setattr(
        tasks, "_cancellable_ingestion_pipeline", lambda run_id=None: FakePipeline()
    )
    monkeypatch.setattr(tasks, "today_taipei", lambda: date(2026, 6, 9))

    result = asyncio.run(
        tasks._run_data_operation_payload(
            "market_refresh",
            {
                "tickers": ["2330"],
                "start_date": "2026-06-09",
                "end_date": "2026-06-09",
                "smoke": True,
            },
        )
    )

    assert result == {
        "smoke": True,
        "operation": "market_refresh",
        "mode": "task_submission_contract",
        "requested_tickers": ["2330"],
        "start_date": "2026-06-09",
        "end_date": "2026-06-09",
        "stored": [],
        "stored_history_count": 0,
        "stale_source_count": 0,
        "errors": [],
        "sources": [],
        "source": "task submission smoke no-op",
        "note": "No external market data providers are called when payload.smoke is true.",
    }


def test_data_operation_dispatch_logic_lives_outside_celery_tasks() -> None:
    tasks_source = Path("app/tasks/tasks.py").read_text()
    helper_source = Path("app/tasks/data_operations.py").read_text()

    assert "from app.tasks.data_operations import" in tasks_source
    assert "async def run_data_operation_payload(" in helper_source
    assert "unsupported data operation task" not in tasks_source
    assert "No external market data providers are called" not in tasks_source
    assert 'if operation == "market_refresh":' not in tasks_source
    assert 'if operation == "market_refresh":' in helper_source
    assert tasks._normalize_tickers(["2330", "2330", ""]) == data_operations.normalize_tickers(
        ["2330", "2330", ""]
    )


def test_after_close_report_update_logic_lives_outside_celery_tasks() -> None:
    tasks_source = Path("app/tasks/tasks.py").read_text()
    helper_source = Path("app/tasks/after_close_report_update.py").read_text()
    file_retention = {"path": Path("reports/new.md"), "old_report_files_deleted": 2}
    db_retention = {"old_report_versions_deleted": 1, "old_report_ids": [27]}

    assert "from app.tasks import after_close_report_update" in tasks_source
    assert "def latest_report_update_target(" in helper_source
    assert "def refresh_after_close_data(" in helper_source
    assert "def rerun_after_close_report(" in helper_source
    assert "def coverage_after_close_update(" in helper_source
    assert "def _latest_report_update_target(" in tasks_source
    assert "ReportFollowUpContextService().load" not in tasks_source
    assert "report_build_service_factory().build" in helper_source
    assert tasks._combined_report_retention(
        db_retention, file_retention
    ) == after_close_report_update.combined_report_retention(db_retention, file_retention)


def test_generate_report_workflow_lives_outside_celery_tasks() -> None:
    tasks_source = Path("app/tasks/tasks.py").read_text()
    helper_source = Path("app/tasks/report_generation.py").read_text()

    assert "from app.tasks import after_close_report_update, report_generation" in tasks_source
    assert "def run_generate_report_payload(" in helper_source
    assert "def _run_generate_report_payload(" in tasks_source
    assert "workflow.start_step(" not in tasks_source
    assert "workflow.complete_step(" not in tasks_source
    assert "FollowUpActionPlanner().plan" not in tasks_source
    assert "combined_report_retention_func(db_retention, file_retention)" in helper_source
    assert (
        tasks.GENERATE_REPORT_PRE_REFRESH_OPERATION == "celery.generate_report.pre_report_refresh"
    )
    assert callable(report_generation.run_generate_report_payload)


def test_after_close_report_update_task_refreshes_latest_report_and_reruns(
    monkeypatch, tmp_path
) -> None:
    calls = []

    class FakeRun:
        id = 303
        payload_json = json.dumps(
            {
                "request": {"topic": "機器人 產業鏈", "tickers": ["2308"], "lookback_days": 60},
                "candidate_whitelist": [{"ticker": "2359", "status": "evidence_supported"}],
            },
            ensure_ascii=False,
        )
        status = "running"
        report_id = None
        output_path = None
        error = None

    class FakeSourceRun:
        payload_json = FakeRun.payload_json

    class FakeReportRecord:
        id = 27
        topic = "機器人 產業鏈"
        tickers_json = json.dumps(["2308"], ensure_ascii=False)
        markdown = "# report"
        generated_at = datetime(2026, 6, 2, 15, 30)
        created_at = datetime(2026, 6, 2, 15, 30)

    class FakeAnalysisRunRepository:
        run = FakeRun()

        def __init__(self, session):
            self.session = session

        def start(self, source, payload):
            assert source == "celery_after_close"
            self.run.payload_json = json.dumps(payload, ensure_ascii=False)
            return self.run

        def get_by_report_id(self, report_id):
            assert report_id == 27
            return FakeSourceRun()

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

    class FakeReportRepository:
        created_id = 404

        def __init__(self, session):
            self.session = session

        def latest(self, limit=20):
            return [FakeReportRecord()]

        def get(self, report_id):
            assert report_id == 27
            return FakeReportRecord()

        def create(self, request, response):
            calls.append(("create_report", request.tickers, response.title))
            self.last_retention_result = {
                "policy": "latest_per_topic",
                "topic": request.topic,
                "report_id": self.created_id,
                "old_report_versions_deleted": 1,
                "old_report_ids": [27],
                "run_links_cleared": True,
                "run_output_paths_cleared": True,
            }
            return SimpleNamespace(id=self.created_id)

    class FakeContextService:
        def load(self, report_id):
            assert report_id == 27
            return {
                "request": tasks.ReportRequest(
                    topic="機器人 產業鏈", tickers=["2308"], lookback_days=60
                ),
                "candidate_whitelist": [{"ticker": "2359", "status": "evidence_supported"}],
                "markdown": "# report",
                "quality_gate": {"status": "ready"},
                "run_payload": json.loads(FakeRun.payload_json),
            }

    class FakeIngestionPipeline:
        async def refresh_market(self, tickers, start_date, end_date, filter_allowed=True):
            calls.append(("market", tickers, filter_allowed, (end_date - start_date).days))
            return {"stored_history_count": 120, "errors": []}

        async def refresh_monthly_revenue(self, tickers, start_date, end_date, filter_allowed=True):
            calls.append(("monthly", tickers, filter_allowed))
            return {"stored_count": 12, "errors": []}

        async def refresh_financial_metrics(
            self, tickers, start_date, end_date, filter_allowed=True
        ):
            calls.append(("financial", tickers, filter_allowed))
            return {"stored_count": 20, "errors": []}

        async def refresh_valuations(self, tickers, start_date, end_date, filter_allowed=True):
            calls.append(("valuation", tickers, filter_allowed))
            return {"stored": [{"ticker": tickers[0]}], "errors": []}

        async def ingest_company_filings(self, tickers, limit_per_query=3, filter_allowed=True):
            calls.append(("filings", tickers, filter_allowed))
            return {"stored_count": 2, "errors": []}

    class FakeReportBuildService:
        def build(self, request, **kwargs):
            calls.append(("build", request.tickers, bool(kwargs.get("whitelist"))))
            return {
                "response": ReportResponse(title="updated", markdown="# updated"),
                "quality_gate": {"status": "ready"},
                "report_execution": {"filtered_tickers": request.tickers},
                "evidence_count": 3,
            }

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(tasks, "init_db", lambda: None)
    monkeypatch.setattr(tasks, "session_scope", fake_session_scope)
    monkeypatch.setattr(tasks, "AnalysisRunRepository", FakeAnalysisRunRepository)
    monkeypatch.setattr(tasks, "ReportRepository", FakeReportRepository)
    monkeypatch.setattr(tasks, "ReportFollowUpContextService", FakeContextService)
    monkeypatch.setattr(tasks, "IngestionPipeline", FakeIngestionPipeline)
    monkeypatch.setattr(tasks, "ReportBuildService", FakeReportBuildService)
    monkeypatch.setattr(
        tasks,
        "CandidateRevalidationService",
        lambda: SimpleNamespace(sufficient_company_filing_tickers=lambda tickers: set(tickers)),
    )
    monkeypatch.setattr(
        tasks,
        "SupplyChainWhitelist",
        SimpleNamespace(from_candidate_whitelist=lambda candidates: object()),
    )
    monkeypatch.setattr(
        tasks, "audit_company_data", lambda *args, **kwargs: {"status": "sufficient"}
    )
    monkeypatch.setattr(
        tasks,
        "MarketRepository",
        lambda session: SimpleNamespace(latest_by_tickers=lambda tickers: []),
    )
    monkeypatch.setattr(
        tasks,
        "MonthlyRevenueRepository",
        lambda session: SimpleNamespace(latest_by_tickers=lambda tickers: []),
    )
    monkeypatch.setattr(
        tasks,
        "ValuationMetricRepository",
        lambda session: SimpleNamespace(latest_by_tickers=lambda tickers: []),
    )
    monkeypatch.setattr(
        tasks,
        "FinancialMetricRepository",
        lambda session: SimpleNamespace(by_tickers=lambda tickers: []),
    )
    monkeypatch.setattr(tasks, "today_taipei", lambda: date(2026, 6, 3))
    monkeypatch.setattr(tasks, "get_settings", lambda: SimpleNamespace(report_dir=tmp_path))
    old_report_file = tmp_path / "20260602_153000_機器人 產業鏈.md"
    old_report_file.write_text("# old", encoding="utf-8")

    result = tasks.after_close_report_update_task.run(
        {"task": "latest_report_update", "lookback_days": 120, "rerun_report": True}
    )

    assert result["source_report_id"] == 27
    assert result["report_id"] == 404
    assert result["tickers"] == ["2308", "2359"]
    assert ("market", ["2308", "2359"], False, 120) in calls
    assert ("monthly", ["2308", "2359"], False) in calls
    assert ("financial", ["2308", "2359"], False) in calls
    assert ("valuation", ["2308", "2359"], False) in calls
    assert ("filings", ["2308", "2359"], False) in calls
    assert ("build", ["2308", "2359"], True) in calls
    assert FakeAnalysisRunRepository.run.status == "success"
    assert not old_report_file.exists()
    assert result["rerun_report"]["retention"]["old_report_versions_deleted"] == 1
    assert result["rerun_report"]["retention"]["old_report_files_deleted"] == 1
    assert result["rerun_report"]["retention"]["db"]["old_report_ids"] == [27]


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
            self.last_retention_result = {
                "policy": "latest_per_topic",
                "topic": request.topic,
                "report_id": FakeReport.id,
                "old_report_versions_deleted": 1,
                "old_report_ids": [201],
                "run_links_cleared": True,
                "run_output_paths_cleared": True,
            }
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
    old_report_file = tmp_path / "20260606_080000_AI 產業鏈.md"
    old_report_file.write_text("# old", encoding="utf-8")

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
    assert payload["retention"]["old_report_versions_deleted"] == 1
    assert payload["retention"]["old_report_files_deleted"] == 1
    assert result["retention"]["db"]["old_report_ids"] == [201]
    assert not old_report_file.exists()


def test_maintenance_cleanup_task_records_result(monkeypatch) -> None:
    captured = {}

    class FakeRun:
        id = 909
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
            assert source == "celery_maintenance_cleanup"
            captured["start_payload"] = payload
            return self.run

        def update_payload(self, run_id, payload):
            assert run_id == self.run.id
            self.run.payload_json = json.dumps(payload, ensure_ascii=False)
            return self.run

        def mark_success(self, run_id, report_id, output_path=None):
            assert run_id == self.run.id
            assert report_id is None
            self.run.status = "success"
            return self.run

        def mark_failed(self, run_id, error):
            self.run.status = "failed"
            self.run.error = error
            return self.run

    class FakeDataOperations:
        def maintenance_cleanup(self, **kwargs):
            captured["cleanup_kwargs"] = kwargs
            return {"old_report_files_deleted": 2, "old_report_versions_deleted": 1}

    class FakeServices:
        def data_operations_api(self):
            return FakeDataOperations()

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(tasks, "init_db", lambda: None)
    monkeypatch.setattr(tasks, "session_scope", fake_session_scope)
    monkeypatch.setattr(tasks, "AnalysisRunRepository", FakeAnalysisRunRepository)
    monkeypatch.setattr(tasks, "_api_services_for_tasks", lambda: FakeServices())
    monkeypatch.setattr(tasks, "utc_now_naive", lambda: datetime(2026, 6, 9, 4, 0, 0))

    result = tasks.maintenance_cleanup_task.run(
        {
            "failed_runs": False,
            "orphan_report_refs": True,
            "latest_reports_only": True,
            "stale_running_minutes": 240,
        }
    )

    assert result["run_id"] == 909
    assert result["result"] == {"old_report_files_deleted": 2, "old_report_versions_deleted": 1}
    assert captured["cleanup_kwargs"] == {
        "failed_runs": False,
        "orphan_report_refs": True,
        "latest_reports_only": True,
        "stale_running_before": datetime(2026, 6, 9, 0, 0, 0),
        "runs_before": None,
        "reports_before": None,
    }
    assert FakeAnalysisRunRepository.run.status == "success"


def test_write_report_file_prunes_older_files_for_same_topic(monkeypatch, tmp_path) -> None:
    old_same_topic = tmp_path / "20260606_120000_記憶體產業鏈.md"
    old_numeric_same_topic = tmp_path / "010_記憶體產業鏈.md"
    other_topic = tmp_path / "009_機器人_產業鏈.md"
    old_same_topic.write_text("old", encoding="utf-8")
    old_numeric_same_topic.write_text("old numeric", encoding="utf-8")
    other_topic.write_text("robot", encoding="utf-8")
    monkeypatch.setattr(tasks, "get_settings", lambda: SimpleNamespace(report_dir=tmp_path))

    path = tasks._write_report_file(
        ReportRequest(topic="記憶體產業鏈"),
        SimpleNamespace(
            generated_at=datetime(2026, 6, 7, 8, 0, 0),
            markdown="# latest",
        ),
    )

    assert path.name == "20260607_080000_記憶體產業鏈.md"
    assert path.read_text(encoding="utf-8") == "# latest"
    assert not old_same_topic.exists()
    assert not old_numeric_same_topic.exists()
    assert other_topic.exists()
