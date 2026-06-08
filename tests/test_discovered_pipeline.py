import json
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.data_sources.market import MarketFetchError
from app.db.models import Base
from app.models.schemas import MarketSnapshot, NewsDocument, ReportResponse, Source
from app.services.topic_discovery import TopicDiscoveryService
from app.services import (
    discovered_candidate_filings,
    discovered_market_payload,
    discovered_pipeline_checkpoints,
    discovered_pipeline_results,
)
from app.services.discovered_pipeline import (
    DiscoveredTopicPipelineService,
    candidate_filing_revalidation_tickers,
    company_filing_timeout_result,
    should_revalidate_candidate_filings,
)
from app.services.persistence import AnalysisRunRepository
from app.services.report_generator import ReportExecutionError
from app.services.workflow_checkpoint import WorkflowCheckpointRecorder


@contextmanager
def fake_session_scope():
    yield object()


class FakePayload:
    topic = "AI 產業鏈"
    analysis_mode = "standard"
    deep_analysis = False

    def model_dump(self, mode=None):
        return {"topic": self.topic}


class GenericTopicPayload(FakePayload):
    topic = "量子運算"


def test_candidate_filing_revalidation_helpers_live_outside_pipeline_orchestrator() -> None:
    candidates = [
        {"ticker": "2330", "status": "evidence_supported"},
        {"ticker": "1504", "status": "weak_evidence"},
        {"ticker": "2308", "status": "needs_evidence"},
    ]
    payload = SimpleNamespace(analysis_mode="standard", deep_analysis=False)

    assert (
        should_revalidate_candidate_filings
        is discovered_candidate_filings.should_revalidate_candidate_filings
    )
    assert (
        candidate_filing_revalidation_tickers
        is discovered_candidate_filings.candidate_filing_revalidation_tickers
    )
    assert (
        company_filing_timeout_result is discovered_candidate_filings.company_filing_timeout_result
    )
    assert should_revalidate_candidate_filings(candidates, min_supported_ratio=0.6) is True
    assert candidate_filing_revalidation_tickers(candidates, payload) == ["1504", "2308", "2330"]


def test_company_filing_timeout_result_has_gap_summary_and_next_actions() -> None:
    result = company_filing_timeout_result(
        ["1504"],
        TimeoutError("timeout"),
        "candidate MOPS annual report discovery",
    )

    assert result["requested_tickers"] == ["1504"]
    assert result["stored_count"] == 0
    assert result["gap_summary"]["retryable_tickers"] == ["1504"]
    assert result["next_actions"][0]["ticker"] == "1504"
    assert result["errors"][0]["category"] == "timeout"
    assert result["errors"][0]["retryable"] is True


def test_discovered_market_payload_logic_lives_outside_pipeline_orchestrator() -> None:
    pipeline_source = Path("app/services/discovered_pipeline.py").read_text()
    payload_source = Path("app/services/discovered_market_payload.py").read_text()
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 29), close=1200)
    error = MarketFetchError(ticker="2330", dataset="price", error="timeout")

    payload = discovered_market_payload.market_data_payload(
        {
            "snapshots": [snapshot],
            "price_history_snapshots": [snapshot],
            "market_errors": [error],
        }
    )
    restored = discovered_market_payload.market_data_from_payload(payload)

    assert (
        DiscoveredTopicPipelineService._market_data_payload({"snapshots": [snapshot]})["snapshots"][
            0
        ]
        == (payload["snapshots"][0])
    )
    assert isinstance(restored["snapshots"][0], MarketSnapshot)
    assert restored["snapshots"][0].trade_date == date(2026, 5, 29)
    assert restored["market_errors"][0] == error
    assert "MarketSnapshot.model_validate(" not in pipeline_source
    assert "MarketSnapshot.model_validate(" in payload_source


def test_discovered_checkpoint_payload_logic_lives_outside_pipeline_orchestrator() -> None:
    pipeline_source = Path("app/services/discovered_pipeline.py").read_text()
    checkpoint_source = Path("app/services/discovered_pipeline_checkpoints.py").read_text()
    document = NewsDocument(
        id="doc-1",
        title="台積電 AI 供應鏈",
        text="台積電 CoWoS 產能。",
        source=Source(title="台積電 AI 供應鏈", published_at=date(2026, 5, 31)),
    )

    assert (
        DiscoveredTopicPipelineService._payload_model_dump(FakePayload())
        == discovered_pipeline_checkpoints.payload_model_dump(FakePayload())
        == {"topic": "AI 產業鏈"}
    )
    restored = discovered_pipeline_checkpoints.documents_from_payload(
        [document.model_dump(mode="json")]
    )

    assert DiscoveredTopicPipelineService._parse_payload('{"topic":"AI"}') == {"topic": "AI"}
    assert DiscoveredTopicPipelineService._json_safe({"date": date(2026, 5, 31)}) == {
        "date": "2026-05-31"
    }
    assert isinstance(restored[0], NewsDocument)
    assert restored[0].source.published_at == date(2026, 5, 31)
    assert "json.loads(" not in pipeline_source
    assert "NewsDocument.model_validate(" not in pipeline_source
    assert "json.loads(" in checkpoint_source
    assert "NewsDocument.model_validate(" in checkpoint_source


def test_discovered_pipeline_result_payload_lives_outside_pipeline_orchestrator() -> None:
    pipeline_source = Path("app/services/discovered_pipeline.py").read_text()
    results_source = Path("app/services/discovered_pipeline_results.py").read_text()

    result = discovered_pipeline_results.discovered_pipeline_result_payload(
        run_id=77,
        run_record_updated=True,
        report_id=88,
        active_report_id=99,
        auto_follow_up={"status": "completed"},
        discovery={"plan": {}},
        queries=["AI 伺服器"],
        fixed_source_ingestion={"count": 1},
        dynamic_query_ingestion=[],
        candidate_filing_ingestion=None,
        company_filing_ingestion={"stored_count": 0},
        source_audit={"coverage": "ok"},
        candidate_whitelist=[{"ticker": "2330", "status": "evidence_supported"}],
        promoted_tickers=["2330"],
        run_payload={"market": [{"ticker": "2330"}], "market_history_count": 3},
        quality_gate={"status": "pass"},
        report_execution={"evidence_count": 5},
        request={"topic": "AI 產業鏈"},
        topic="AI 產業鏈",
        report={"title": "AI report"},
        resumed_from_step="report_build",
    )

    assert result["active_report_id"] == 99
    assert result["market"] == [{"ticker": "2330"}]
    assert result["market_history_count"] == 3
    assert result["monthly_revenue"] == []
    assert result["resumed_from_step"] == "report_build"
    assert '"market_history_count": run_payload' not in pipeline_source
    assert '"market_history_count": run_payload' in results_source


class FakeRun:
    id = 77


class FakeRunRepository:
    def __init__(self, session):
        pass

    def start(self, source, payload):
        assert source == "pipeline_ai_discovery"
        return FakeRun()

    def get(self, run_id):
        return FakeRun() if run_id == FakeRun.id else None

    def update_payload(self, run_id, payload):
        pass


class FakeReportRepository:
    def __init__(self, session):
        pass

    def get(self, report_id):
        return SimpleNamespace(title="AI report", markdown="# report") if report_id == 88 else None


class FakePlan:
    subtopics = [SimpleNamespace(name="AI")]
    candidate_companies = [SimpleNamespace(ticker="2330")]


class FakePlanClass:
    @staticmethod
    def model_validate(payload):
        return FakePlan()


class FakeCandidate:
    def __init__(self, ticker="2330", status="evidence_supported"):
        self.ticker = ticker
        self.status = status

    def model_dump(self):
        return {"ticker": self.ticker, "status": self.status}


class FakeTopicDiscoveryService:
    def evaluate_plan_quality(self, plan):
        return TopicDiscoveryService.evaluate_plan_quality(plan)

    def validate_candidates(self, plan, documents):
        return [FakeCandidate("2330", "evidence_supported")]


class FakeWhitelist:
    @staticmethod
    def from_candidate_whitelist(candidates):
        return SimpleNamespace(candidates=candidates)


class FakeCompanyFilingRepository:
    def __init__(self, session):
        pass

    def latest_by_tickers(self, tickers, limit_per_ticker=4):
        return []

    @staticmethod
    def to_news_document(document):
        return document


class FakeWorkflowRecorder:
    def __init__(self):
        self.events = []

    def initialize(self, run_id, name, steps):
        self.events.append(("initialize", name, list(steps)))

    def start_step(self, run_id, step, summary=None):
        self.events.append(("start", step, summary or {}))

    def complete_step(self, run_id, step, summary=None):
        self.events.append(("complete", step, summary or {}))

    def fail_step(self, run_id, step, error, summary=None):
        self.events.append(("fail", step, error))

    def complete_workflow_payload(self, run_id, payload):
        return {
            **payload,
            "workflow": {"name": "ai_discovered_topic_pipeline", "status": "success"},
        }

    def payload_with_current_workflow(self, run_id, payload):
        return {
            **payload,
            "workflow": {"name": "ai_discovered_topic_pipeline", "status": "running"},
        }


class FakeMarketDataService:
    async def fetch_and_persist_for_discovery(self, payload, promoted_tickers, end_date):
        return {
            "snapshots": [],
            "price_history_snapshots": [],
            "market_errors": [],
            "monthly_revenues": [],
            "monthly_revenue_errors": [],
            "latest_monthly_revenues": [],
            "financial_metrics": [],
            "financial_metric_errors": [],
            "valuations": [],
            "valuation_errors": [],
        }


class FakeReportBuilderService:
    def build_and_store_report(self, **kwargs):
        return {
            "response": ReportResponse(title="AI report", markdown="# report"),
            "report_id": 88,
            "quality_gate": {"status": "ready"},
            "report_execution": {"evidence_count": 1},
            "run_payload": {
                "market": [],
                "market_history_count": 0,
                "market_errors": [],
                "monthly_revenue": [],
                "monthly_revenue_errors": [],
                "latest_monthly_revenue": [],
                "financial_metrics_count": 0,
                "financial_metric_errors": [],
                "valuations": [],
                "valuation_errors": [],
            },
        }


def test_discovered_pipeline_service_runs_full_flow() -> None:
    workflow = FakeWorkflowRecorder()
    captured = {}

    async def discover_topic(service, topic):
        return {"plan": {"candidate_companies": []}, "plan_quality": {"status": "ready"}}

    async def run_ingestion(
        payload, service, plan, limit_per_query, evidence_limit, max_queries, document_limit
    ):
        return {
            "urls": ["https://example.com/rss"],
            "end_date": date(2026, 5, 31),
            "documents": ["doc-1"],
            "fixed_source_ingestion": {"count": 1},
            "dynamic_query_ingestion": [{"count": 1}],
            "ingestion_results": [{"count": 2}],
            "source_audit": {"total_stored_count": 2},
            "candidates": [FakeCandidate()],
        }

    def safe_update(run_id, payload, report_id):
        captured["safe_update"] = {"run_id": run_id, "payload": payload, "report_id": report_id}
        return True

    async def auto_follow_up(report_id):
        return {
            "status": "started",
            "source_report_id": report_id,
            "source_report_topic": "AI 產業鏈",
            "source_report_tickers": ["2330"],
            "rerun_report": {
                "report_id": 99,
                "request": {"topic": "AI 產業鏈", "tickers": ["2330"]},
            },
        }

    result = run_async(
        _service(
            workflow_recorder_factory=lambda: workflow,
            discover_topic_with_timeout_func=discover_topic,
            run_topic_discovery_ingestion_func=run_ingestion,
            safe_update_run_success_func=safe_update,
            auto_follow_up_func=auto_follow_up,
        ).run(FakePayload())
    )

    assert result["run_id"] == 77
    assert result["report_id"] == 88
    assert result["active_report_id"] == 99
    assert result["promoted_tickers"] == ["2330"]
    assert result["run_record_updated"] is True
    assert captured["safe_update"]["payload"]["workflow"]["status"] == "success"
    assert captured["safe_update"]["payload"]["report_id"] == 88
    assert (
        "complete",
        "auto_follow_up",
        {"status": "started", "rerun_report_id": 99},
    ) in workflow.events


def test_discovered_pipeline_service_runs_unknown_topic_to_report() -> None:
    workflow = FakeWorkflowRecorder()

    async def discover_topic(service, topic):
        plan = TopicDiscoveryService._fallback_plan(topic)
        quality = service.evaluate_plan_quality(plan)
        assert quality.status == "ready"
        return {"plan": plan.model_dump(), "plan_quality": quality.model_dump()}

    async def run_ingestion(
        payload, service, plan, limit_per_query, evidence_limit, max_queries, document_limit
    ):
        return {
            "urls": ["https://example.com/rss"],
            "end_date": date(2026, 5, 31),
            "documents": ["doc-1"],
            "fixed_source_ingestion": {"count": 1},
            "dynamic_query_ingestion": [{"count": 1}],
            "ingestion_results": [{"count": 2}],
            "source_audit": {"total_stored_count": 2, "plan_quality": {"status": "ready"}},
            "candidates": [FakeCandidate()],
        }

    result = run_async(
        _service(
            workflow_recorder_factory=lambda: workflow,
            discover_topic_with_timeout_func=discover_topic,
            run_topic_discovery_ingestion_func=run_ingestion,
        ).run(GenericTopicPayload())
    )

    assert result["report_id"] == 88
    assert result["discovery"]["plan_quality"]["status"] == "ready"
    assert result["request"]["topic"] == "量子運算"
    assert result["quality_gate"]["status"] == "ready"


def test_discovered_pipeline_service_marks_failed_step() -> None:
    workflow = FakeWorkflowRecorder()
    captured = {}

    class FailingReportBuilderService:
        def build_and_store_report(self, **kwargs):
            raise ReportExecutionError("bad discovered report")

    async def discover_topic(service, topic):
        return {"plan": {"candidate_companies": []}, "plan_quality": {"status": "ready"}}

    async def run_ingestion(
        payload, service, plan, limit_per_query, evidence_limit, max_queries, document_limit
    ):
        return {
            "urls": [],
            "end_date": date(2026, 5, 31),
            "documents": [],
            "fixed_source_ingestion": {},
            "dynamic_query_ingestion": [],
            "ingestion_results": [],
            "source_audit": {"total_stored_count": 0},
            "candidates": [FakeCandidate()],
        }

    def safe_failed(run_id, error):
        captured["failed"] = {"run_id": run_id, "error": error}

    service = _service(
        workflow_recorder_factory=lambda: workflow,
        discovered_report_builder_service_factory=lambda: FailingReportBuilderService(),
        discover_topic_with_timeout_func=discover_topic,
        run_topic_discovery_ingestion_func=run_ingestion,
        safe_mark_run_failed_func=safe_failed,
    )

    with pytest.raises(ReportExecutionError):
        run_async(service.run(FakePayload()))

    assert captured["failed"] == {"run_id": 77, "error": "bad discovered report"}
    assert ("fail", "report_build", "bad discovered report") in workflow.events


def test_discovered_pipeline_checkpoints_report_payload_before_auto_follow_up() -> None:
    captured = {}

    class CapturingRunRepository(FakeRunRepository):
        def update_payload(self, run_id, payload):
            captured["checkpoint"] = {"run_id": run_id, "payload": payload}

    service = _service(analysis_run_repository_cls=CapturingRunRepository)

    result = run_async(service.run(FakePayload()))

    assert result["report_id"] == 88
    assert captured["checkpoint"]["run_id"] == 77
    assert captured["checkpoint"]["payload"]["report_id"] == 88
    assert captured["checkpoint"]["payload"]["workflow"]["status"] == "running"


def test_discovered_pipeline_checkpoints_serializable_stage_artifacts() -> None:
    captured = {"updates": []}
    document = NewsDocument(
        id="doc-1",
        title="台積電 AI 供應鏈",
        text="台積電 CoWoS 產能。",
        source=Source(title="台積電 AI 供應鏈", published_at=date(2026, 5, 31)),
    )
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 29), close=1200)

    class CapturingRunRepository(FakeRunRepository):
        def update_payload(self, run_id, payload):
            captured["updates"].append(payload)

    async def run_ingestion(
        payload, service, plan, limit_per_query, evidence_limit, max_queries, document_limit
    ):
        return {
            "urls": ["https://example.com/rss"],
            "end_date": date(2026, 5, 31),
            "documents": [document],
            "fixed_source_ingestion": {"count": 1},
            "dynamic_query_ingestion": [],
            "ingestion_results": [{"count": 1}],
            "source_audit": {"total_stored_count": 1},
            "candidates": [FakeCandidate()],
        }

    class SnapshotMarketDataService(FakeMarketDataService):
        async def fetch_and_persist_for_discovery(self, payload, promoted_tickers, end_date):
            data = await super().fetch_and_persist_for_discovery(
                payload, promoted_tickers, end_date
            )
            data["snapshots"] = [snapshot]
            data["price_history_snapshots"] = [snapshot]
            return data

    result = run_async(
        _service(
            analysis_run_repository_cls=CapturingRunRepository,
            run_topic_discovery_ingestion_func=run_ingestion,
            discovered_market_data_service_factory=lambda: SnapshotMarketDataService(),
            dedupe_documents_func=lambda documents: documents,
        ).run(FakePayload())
    )

    assert result["report_id"] == 88
    assert any(
        update.get("pipeline_request", {}).get("topic") == "AI 產業鏈"
        for update in captured["updates"]
    )
    assert any(
        update.get("source_documents", [{}])[0].get("id") == "doc-1"
        for update in captured["updates"]
        if update.get("source_documents")
    )
    market_updates = [update for update in captured["updates"] if update.get("market_data")]
    assert market_updates[-1]["market_data"]["snapshots"][0]["ticker"] == "2330"
    assert market_updates[-1]["market_data"]["snapshots"][0]["trade_date"] == "2026-05-29"


def test_discovered_pipeline_service_resumes_auto_follow_up_from_checkpoint() -> None:
    workflow = FakeWorkflowRecorder()
    captured = {}
    run_payload = {
        "request": {"topic": "AI 產業鏈", "tickers": ["2330"]},
        "report_id": 88,
        "discovery": {"plan_quality": {"status": "ready"}},
        "queries": ["https://example.com/rss"],
        "fixed_source_ingestion": {"count": 1},
        "dynamic_query_ingestion": [],
        "candidate_filing_ingestion": None,
        "company_filing_ingestion": {"stored_count": 0},
        "source_audit": {"total_stored_count": 1},
        "candidate_whitelist": [{"ticker": "2330", "status": "evidence_supported"}],
        "market": [],
        "market_history_count": 0,
        "market_errors": [],
        "monthly_revenue": [],
        "monthly_revenue_errors": [],
        "latest_monthly_revenue": [],
        "financial_metrics_count": 0,
        "financial_metric_errors": [],
        "valuations": [],
        "valuation_errors": [],
        "quality_gate": {"status": "ready"},
        "report_execution": {"evidence_count": 1},
    }
    workflow_payload = WorkflowCheckpointRecorder.initialize_payload(
        run_payload,
        "ai_discovered_topic_pipeline",
        [
            "topic_discovery",
            "source_ingestion",
            "candidate_revalidation",
            "market_data_refresh",
            "report_build",
            "auto_follow_up",
        ],
        "2026-05-31T09:00:00",
    )
    for step in [
        "topic_discovery",
        "source_ingestion",
        "candidate_revalidation",
        "market_data_refresh",
        "report_build",
    ]:
        workflow_payload = WorkflowCheckpointRecorder.complete_step_payload(
            workflow_payload,
            step,
            "2026-05-31T09:01:00",
        )
    workflow_payload = WorkflowCheckpointRecorder.fail_step_payload(
        workflow_payload,
        "auto_follow_up",
        "follow-up failed",
        "2026-05-31T09:02:00",
    )

    class ExistingRunRepository(FakeRunRepository):
        def get(self, run_id):
            return SimpleNamespace(
                id=run_id,
                payload_json=json.dumps(workflow_payload),
                report_id=88,
            )

        def mark_running(self, run_id):
            captured["mark_running"] = run_id

    async def auto_follow_up(report_id):
        captured["auto_follow_up_report_id"] = report_id
        return {
            "status": "started",
            "source_report_id": report_id,
            "source_report_topic": "AI 產業鏈",
            "source_report_tickers": ["2330"],
            "rerun_report": {
                "report_id": 99,
                "request": {"topic": "AI 產業鏈", "tickers": ["2330"]},
            },
        }

    def safe_update(run_id, payload, report_id):
        captured["safe_update"] = {"run_id": run_id, "payload": payload, "report_id": report_id}
        return True

    service = _service(
        analysis_run_repository_cls=ExistingRunRepository,
        workflow_recorder_factory=lambda: workflow,
        auto_follow_up_func=auto_follow_up,
        safe_update_run_success_func=safe_update,
    )

    result = run_async(service.resume(77))

    assert captured["mark_running"] == 77
    assert captured["auto_follow_up_report_id"] == 88
    assert captured["safe_update"]["payload"]["workflow"]["status"] == "success"
    assert result["run_id"] == 77
    assert result["active_report_id"] == 99
    assert result["resumed_from_step"] == "auto_follow_up"
    assert result["promoted_tickers"] == ["2330"]
    assert result["report"]["markdown"] == "# report"
    assert ("start", "auto_follow_up", {"report_id": 88, "resumed": True}) in workflow.events
    assert (
        "complete",
        "auto_follow_up",
        {"status": "started", "rerun_report_id": 99, "resumed": True},
    ) in workflow.events


def test_discovered_pipeline_service_resumes_report_build_from_checkpoint() -> None:
    workflow = FakeWorkflowRecorder()
    captured = {}
    document = NewsDocument(
        id="doc-1",
        title="台積電 AI 供應鏈",
        text="台積電 CoWoS 產能。",
        source=Source(title="台積電 AI 供應鏈", published_at=date(2026, 5, 31)),
    )
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 29), close=1200)
    checkpoint = {
        "pipeline_request": FakePayload().model_dump(mode="json"),
        "discovery": {"plan": {"candidate_companies": []}, "plan_quality": {"status": "ready"}},
        "discovery_fetch_settings": {
            "limit_per_query": 5,
            "evidence_limit": 40,
            "max_queries": 12,
            "document_limit": 100,
        },
        "queries": ["https://example.com/rss"],
        "source_documents": [document.model_dump(mode="json")],
        "fixed_source_ingestion": {"count": 1},
        "dynamic_query_ingestion": [],
        "ingestion": [{"count": 1}],
        "source_audit": {"total_stored_count": 1},
        "candidate_whitelist": [{"ticker": "2330", "status": "evidence_supported"}],
        "promoted_tickers": ["2330"],
        "candidate_filing_ingestion": None,
        "company_filing_ingestion": {"stored_count": 0},
        "market_data": {
            "snapshots": [snapshot.model_dump(mode="json")],
            "price_history_snapshots": [snapshot.model_dump(mode="json")],
            "market_errors": [],
            "monthly_revenues": [],
            "monthly_revenue_errors": [],
            "latest_monthly_revenues": [],
            "financial_metrics": [],
            "financial_metric_errors": [],
            "valuations": [],
            "valuation_errors": [],
        },
    }
    workflow_payload = WorkflowCheckpointRecorder.initialize_payload(
        checkpoint,
        "ai_discovered_topic_pipeline",
        [
            "topic_discovery",
            "source_ingestion",
            "candidate_revalidation",
            "market_data_refresh",
            "report_build",
            "auto_follow_up",
        ],
        "2026-05-31T09:00:00",
    )
    for step in [
        "topic_discovery",
        "source_ingestion",
        "candidate_revalidation",
        "market_data_refresh",
    ]:
        workflow_payload = WorkflowCheckpointRecorder.complete_step_payload(
            workflow_payload,
            step,
            "2026-05-31T09:01:00",
        )
    workflow_payload = WorkflowCheckpointRecorder.fail_step_payload(
        workflow_payload,
        "report_build",
        "builder failed",
        "2026-05-31T09:02:00",
    )

    class ExistingRunRepository(FakeRunRepository):
        def get(self, run_id):
            return SimpleNamespace(
                id=run_id, payload_json=json.dumps(workflow_payload), report_id=None
            )

        def mark_running(self, run_id):
            captured["mark_running"] = run_id

        def update_payload(self, run_id, payload):
            captured["checkpoint"] = payload

    class CapturingReportBuilderService:
        def build_and_store_report(self, **kwargs):
            captured["builder"] = kwargs
            return FakeReportBuilderService().build_and_store_report(**kwargs)

    async def auto_follow_up(report_id):
        captured["auto_follow_up_report_id"] = report_id
        return {"status": "not_needed", "source_report_id": report_id}

    result = run_async(
        _service(
            analysis_run_repository_cls=ExistingRunRepository,
            workflow_recorder_factory=lambda: workflow,
            discovered_report_builder_service_factory=lambda: CapturingReportBuilderService(),
            auto_follow_up_func=auto_follow_up,
        ).resume(77)
    )

    assert captured["mark_running"] == 77
    assert captured["builder"]["promoted_tickers"] == ["2330"]
    assert isinstance(captured["builder"]["documents"][0], NewsDocument)
    assert isinstance(captured["builder"]["market_data"]["snapshots"][0], MarketSnapshot)
    assert result["report_id"] == 88
    assert result["resumed_from_step"] == "report_build"
    assert captured["auto_follow_up_report_id"] == 88
    assert ("start", "report_build", {"promoted_count": 1, "resumed": True}) in workflow.events


def test_discovered_pipeline_service_resumes_source_ingestion_from_checkpoint() -> None:
    workflow = FakeWorkflowRecorder()
    captured = {}
    document = NewsDocument(
        id="doc-1",
        title="台積電 AI 供應鏈",
        text="台積電 CoWoS 產能。",
        source=Source(title="台積電 AI 供應鏈", published_at=date(2026, 5, 31)),
    )
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 29), close=1200)
    checkpoint = {
        "pipeline_request": {
            "topic": "AI 產業鏈",
            "limit_per_query": 3,
            "lookback_days": 14,
            "evidence_limit": 12,
            "analysis_mode": "fast",
            "deep_analysis": False,
            "include_international": True,
        },
        "discovery": {"plan": {"candidate_companies": []}, "plan_quality": {"status": "ready"}},
        "discovery_fetch_settings": {
            "limit_per_query": 7,
            "evidence_limit": 33,
            "max_queries": 11,
            "document_limit": 99,
        },
    }
    workflow_payload = WorkflowCheckpointRecorder.initialize_payload(
        checkpoint,
        "ai_discovered_topic_pipeline",
        [
            "topic_discovery",
            "source_ingestion",
            "candidate_revalidation",
            "market_data_refresh",
            "report_build",
            "auto_follow_up",
        ],
        "2026-05-31T09:00:00",
    )
    workflow_payload = WorkflowCheckpointRecorder.complete_step_payload(
        workflow_payload,
        "topic_discovery",
        "2026-05-31T09:01:00",
    )
    workflow_payload = WorkflowCheckpointRecorder.fail_step_payload(
        workflow_payload,
        "source_ingestion",
        "news fetch failed",
        "2026-05-31T09:02:00",
    )

    class ExistingRunRepository(FakeRunRepository):
        def get(self, run_id):
            return SimpleNamespace(
                id=run_id, payload_json=json.dumps(workflow_payload), report_id=None
            )

        def mark_running(self, run_id):
            captured["mark_running"] = run_id

        def update_payload(self, run_id, payload):
            captured.setdefault("checkpoints", []).append(payload)

    async def run_ingestion(
        payload, service, plan, limit_per_query, evidence_limit, max_queries, document_limit
    ):
        captured["ingestion_args"] = {
            "topic": payload.topic,
            "limit_per_query": limit_per_query,
            "evidence_limit": evidence_limit,
            "max_queries": max_queries,
            "document_limit": document_limit,
        }
        return {
            "urls": ["https://example.com/rss"],
            "end_date": date(2026, 5, 31),
            "documents": [document],
            "fixed_source_ingestion": {"count": 1},
            "dynamic_query_ingestion": [],
            "ingestion_results": [{"count": 1}],
            "source_audit": {"total_stored_count": 1},
            "candidates": [FakeCandidate()],
        }

    class SnapshotMarketDataService(FakeMarketDataService):
        async def fetch_and_persist_for_discovery(self, payload, promoted_tickers, end_date):
            captured["market"] = {
                "promoted_tickers": promoted_tickers,
                "end_date": end_date,
            }
            data = await super().fetch_and_persist_for_discovery(
                payload, promoted_tickers, end_date
            )
            data["snapshots"] = [snapshot]
            data["price_history_snapshots"] = [snapshot]
            return data

    result = run_async(
        _service(
            analysis_run_repository_cls=ExistingRunRepository,
            workflow_recorder_factory=lambda: workflow,
            run_topic_discovery_ingestion_func=run_ingestion,
            discovered_market_data_service_factory=lambda: SnapshotMarketDataService(),
            dedupe_documents_func=lambda documents: documents,
        ).resume(77)
    )

    assert captured["mark_running"] == 77
    assert captured["ingestion_args"] == {
        "topic": "AI 產業鏈",
        "limit_per_query": 7,
        "evidence_limit": 33,
        "max_queries": 11,
        "document_limit": 99,
    }
    assert captured["market"] == {"promoted_tickers": ["2330"], "end_date": date(2026, 5, 31)}
    assert result["report_id"] == 88
    assert result["resumed_from_step"] == "source_ingestion"
    assert (
        "start",
        "source_ingestion",
        {
            "limit_per_query": 7,
            "evidence_limit": 33,
            "max_queries": 11,
            "resumed": True,
        },
    ) in workflow.events
    assert ("start", "report_build", {"promoted_count": 1, "resumed": True}) in workflow.events


def test_discovered_pipeline_service_resumes_topic_discovery_from_original_payload() -> None:
    workflow = FakeWorkflowRecorder()
    captured = {}
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 29), close=1200)
    workflow_payload = WorkflowCheckpointRecorder.initialize_payload(
        {"topic": "機器人產業鏈"},
        "ai_discovered_topic_pipeline",
        [
            "topic_discovery",
            "source_ingestion",
            "candidate_revalidation",
            "market_data_refresh",
            "report_build",
            "auto_follow_up",
        ],
        "2026-05-31T09:00:00",
    )
    workflow_payload = WorkflowCheckpointRecorder.fail_step_payload(
        workflow_payload,
        "topic_discovery",
        "llm timeout",
        "2026-05-31T09:01:00",
    )

    class ExistingRunRepository(FakeRunRepository):
        def get(self, run_id):
            return SimpleNamespace(
                id=run_id, payload_json=json.dumps(workflow_payload), report_id=None
            )

        def mark_running(self, run_id):
            captured["mark_running"] = run_id

        def update_payload(self, run_id, payload):
            captured.setdefault("checkpoints", []).append(payload)

    async def discover_topic(service, topic):
        captured["discover_topic"] = topic
        return {"plan": {"candidate_companies": []}, "plan_quality": {"status": "ready"}}

    async def run_ingestion(
        payload, service, plan, limit_per_query, evidence_limit, max_queries, document_limit
    ):
        captured["ingestion_topic"] = payload.topic
        return {
            "urls": ["https://example.com/robot"],
            "end_date": date(2026, 5, 31),
            "documents": [],
            "fixed_source_ingestion": {"count": 1},
            "dynamic_query_ingestion": [],
            "ingestion_results": [{"count": 1}],
            "source_audit": {"total_stored_count": 1},
            "candidates": [FakeCandidate()],
        }

    class SnapshotMarketDataService(FakeMarketDataService):
        async def fetch_and_persist_for_discovery(self, payload, promoted_tickers, end_date):
            data = await super().fetch_and_persist_for_discovery(
                payload, promoted_tickers, end_date
            )
            data["snapshots"] = [snapshot]
            data["price_history_snapshots"] = [snapshot]
            return data

    result = run_async(
        _service(
            analysis_run_repository_cls=ExistingRunRepository,
            workflow_recorder_factory=lambda: workflow,
            discover_topic_with_timeout_func=discover_topic,
            run_topic_discovery_ingestion_func=run_ingestion,
            discovered_market_data_service_factory=lambda: SnapshotMarketDataService(),
        ).resume(77)
    )

    assert captured["mark_running"] == 77
    assert captured["discover_topic"] == "機器人產業鏈"
    assert captured["ingestion_topic"] == "機器人產業鏈"
    assert result["report_id"] == 88
    assert result["resumed_from_step"] == "topic_discovery"
    assert any(
        checkpoint.get("pipeline_request", {}).get("topic") == "機器人產業鏈"
        for checkpoint in captured["checkpoints"]
    )
    assert (
        "start",
        "topic_discovery",
        {"topic": "機器人產業鏈", "resumed": True},
    ) in workflow.events
    assert (
        "start",
        "source_ingestion",
        {
            "limit_per_query": 5,
            "evidence_limit": 40,
            "max_queries": 12,
            "resumed": True,
        },
    ) in workflow.events


def test_discovered_pipeline_service_resumes_candidate_revalidation_from_checkpoint() -> None:
    workflow = FakeWorkflowRecorder()
    captured = {}
    document = NewsDocument(
        id="doc-1",
        title="台積電 AI 供應鏈",
        text="台積電 CoWoS 產能。",
        source=Source(title="台積電 AI 供應鏈", published_at=date(2026, 5, 31)),
    )
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 29), close=1200)
    checkpoint = {
        "pipeline_request": FakePayload().model_dump(mode="json"),
        "discovery": {"plan": {"candidate_companies": []}, "plan_quality": {"status": "ready"}},
        "discovery_fetch_settings": {"evidence_limit": 40},
        "queries": ["https://example.com/rss"],
        "discovery_end_date": "2026-05-31",
        "source_documents": [document.model_dump(mode="json")],
        "fixed_source_ingestion": {"count": 1},
        "dynamic_query_ingestion": [],
        "ingestion": [{"count": 1}],
        "source_audit": {"total_stored_count": 1},
        "candidate_whitelist": [{"ticker": "2330", "status": "needs_evidence"}],
    }
    workflow_payload = WorkflowCheckpointRecorder.initialize_payload(
        checkpoint,
        "ai_discovered_topic_pipeline",
        [
            "topic_discovery",
            "source_ingestion",
            "candidate_revalidation",
            "market_data_refresh",
            "report_build",
            "auto_follow_up",
        ],
        "2026-05-31T09:00:00",
    )
    for step in ["topic_discovery", "source_ingestion"]:
        workflow_payload = WorkflowCheckpointRecorder.complete_step_payload(
            workflow_payload,
            step,
            "2026-05-31T09:01:00",
        )
    workflow_payload = WorkflowCheckpointRecorder.fail_step_payload(
        workflow_payload,
        "candidate_revalidation",
        "candidate validation failed",
        "2026-05-31T09:02:00",
    )

    class ExistingRunRepository(FakeRunRepository):
        def get(self, run_id):
            return SimpleNamespace(
                id=run_id, payload_json=json.dumps(workflow_payload), report_id=None
            )

        def mark_running(self, run_id):
            captured["mark_running"] = run_id

        def update_payload(self, run_id, payload):
            captured.setdefault("checkpoints", []).append(payload)

    class SnapshotMarketDataService(FakeMarketDataService):
        async def fetch_and_persist_for_discovery(self, payload, promoted_tickers, end_date):
            captured["market"] = {
                "promoted_tickers": promoted_tickers,
                "end_date": end_date,
            }
            data = await super().fetch_and_persist_for_discovery(
                payload, promoted_tickers, end_date
            )
            data["snapshots"] = [snapshot]
            data["price_history_snapshots"] = [snapshot]
            return data

    class CapturingReportBuilderService:
        def build_and_store_report(self, **kwargs):
            captured["builder"] = kwargs
            return FakeReportBuilderService().build_and_store_report(**kwargs)

    class LocalCompanyFilingRepository:
        def __init__(self, session):
            pass

        def latest_by_tickers(self, tickers, limit_per_ticker=4):
            return [document]

        @staticmethod
        def to_news_document(document):
            return document

    result = run_async(
        _service(
            analysis_run_repository_cls=ExistingRunRepository,
            company_filing_repository_cls=LocalCompanyFilingRepository,
            workflow_recorder_factory=lambda: workflow,
            discovered_market_data_service_factory=lambda: SnapshotMarketDataService(),
            discovered_report_builder_service_factory=lambda: CapturingReportBuilderService(),
            dedupe_documents_func=lambda documents: documents,
            should_revalidate_candidate_filings_func=lambda candidates: True,
        ).resume(77)
    )

    assert captured["mark_running"] == 77
    assert captured["market"] == {"promoted_tickers": ["2330"], "end_date": date(2026, 5, 31)}
    assert captured["builder"]["promoted_tickers"] == ["2330"]
    assert isinstance(captured["builder"]["documents"][0], NewsDocument)
    assert result["report_id"] == 88
    assert result["resumed_from_step"] == "candidate_revalidation"
    assert (
        "start",
        "candidate_revalidation",
        {"candidate_count": 1, "resumed": True},
    ) in workflow.events
    assert (
        "start",
        "market_data_refresh",
        {"promoted_count": 1, "resumed": True},
    ) in workflow.events
    assert ("start", "report_build", {"promoted_count": 1, "resumed": True}) in workflow.events


def test_discovered_pipeline_service_resumes_market_data_refresh_from_checkpoint() -> None:
    workflow = FakeWorkflowRecorder()
    captured = {}
    document = NewsDocument(
        id="doc-1",
        title="台積電 AI 供應鏈",
        text="台積電 CoWoS 產能。",
        source=Source(title="台積電 AI 供應鏈", published_at=date(2026, 5, 31)),
    )
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 29), close=1200)
    checkpoint = {
        "pipeline_request": FakePayload().model_dump(mode="json"),
        "discovery": {"plan": {"candidate_companies": []}, "plan_quality": {"status": "ready"}},
        "discovery_fetch_settings": {"evidence_limit": 40},
        "queries": ["https://example.com/rss"],
        "discovery_end_date": "2026-05-31",
        "source_documents": [document.model_dump(mode="json")],
        "fixed_source_ingestion": {"count": 1},
        "dynamic_query_ingestion": [],
        "ingestion": [{"count": 1}],
        "source_audit": {"total_stored_count": 1},
        "candidate_whitelist": [{"ticker": "2330", "status": "evidence_supported"}],
        "candidate_filing_ingestion": None,
        "company_filing_ingestion": {"stored_count": 0},
        "promoted_tickers": ["2330"],
    }
    workflow_payload = WorkflowCheckpointRecorder.initialize_payload(
        checkpoint,
        "ai_discovered_topic_pipeline",
        [
            "topic_discovery",
            "source_ingestion",
            "candidate_revalidation",
            "market_data_refresh",
            "report_build",
            "auto_follow_up",
        ],
        "2026-05-31T09:00:00",
    )
    for step in ["topic_discovery", "source_ingestion", "candidate_revalidation"]:
        workflow_payload = WorkflowCheckpointRecorder.complete_step_payload(
            workflow_payload,
            step,
            "2026-05-31T09:01:00",
        )
    workflow_payload = WorkflowCheckpointRecorder.fail_step_payload(
        workflow_payload,
        "market_data_refresh",
        "market failed",
        "2026-05-31T09:02:00",
    )

    class ExistingRunRepository(FakeRunRepository):
        def get(self, run_id):
            return SimpleNamespace(
                id=run_id, payload_json=json.dumps(workflow_payload), report_id=None
            )

        def mark_running(self, run_id):
            captured["mark_running"] = run_id

        def update_payload(self, run_id, payload):
            captured.setdefault("checkpoints", []).append(payload)

    class SnapshotMarketDataService(FakeMarketDataService):
        async def fetch_and_persist_for_discovery(self, payload, promoted_tickers, end_date):
            captured["market"] = {
                "promoted_tickers": promoted_tickers,
                "end_date": end_date,
            }
            data = await super().fetch_and_persist_for_discovery(
                payload, promoted_tickers, end_date
            )
            data["snapshots"] = [snapshot]
            data["price_history_snapshots"] = [snapshot]
            return data

    class CapturingReportBuilderService:
        def build_and_store_report(self, **kwargs):
            captured["builder"] = kwargs
            return FakeReportBuilderService().build_and_store_report(**kwargs)

    result = run_async(
        _service(
            analysis_run_repository_cls=ExistingRunRepository,
            workflow_recorder_factory=lambda: workflow,
            discovered_market_data_service_factory=lambda: SnapshotMarketDataService(),
            discovered_report_builder_service_factory=lambda: CapturingReportBuilderService(),
        ).resume(77)
    )

    assert captured["mark_running"] == 77
    assert captured["market"] == {"promoted_tickers": ["2330"], "end_date": date(2026, 5, 31)}
    market_checkpoints = [
        payload for payload in captured["checkpoints"] if payload.get("market_data")
    ]
    assert market_checkpoints[-1]["market_data"]["snapshots"][0]["ticker"] == "2330"
    assert captured["builder"]["promoted_tickers"] == ["2330"]
    assert result["report_id"] == 88
    assert result["resumed_from_step"] == "market_data_refresh"
    assert (
        "start",
        "market_data_refresh",
        {"promoted_count": 1, "resumed": True},
    ) in workflow.events
    assert ("start", "report_build", {"promoted_count": 1, "resumed": True}) in workflow.events


def test_discovered_pipeline_resume_updates_existing_run_state_with_real_checkpoint() -> None:
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

    run_payload = {
        "request": {"topic": "AI 產業鏈", "tickers": ["2330"]},
        "report_id": 88,
        "quality_gate": {"status": "ready"},
        "report_execution": {"evidence_count": 1},
        "candidate_whitelist": [{"ticker": "2330", "status": "evidence_supported"}],
    }
    with session_scope() as session:
        repository = AnalysisRunRepository(session)
        run = repository.start("pipeline_ai_discovery", {"topic": "AI 產業鏈"})
        run_id = run.id

    recorder = WorkflowCheckpointRecorder(session_scope_factory=session_scope)
    recorder.initialize(
        run_id,
        "ai_discovered_topic_pipeline",
        [
            "topic_discovery",
            "source_ingestion",
            "candidate_revalidation",
            "market_data_refresh",
            "report_build",
            "auto_follow_up",
        ],
    )
    for step in [
        "topic_discovery",
        "source_ingestion",
        "candidate_revalidation",
        "market_data_refresh",
        "report_build",
    ]:
        recorder.complete_step(run_id, step)
    with session_scope() as session:
        repository = AnalysisRunRepository(session)
        payload = json.loads(repository.get(run_id).payload_json)
        repository.update_payload(run_id, {**run_payload, "workflow": payload["workflow"]})
        repository.mark_success(run_id, report_id=88)
        repository.mark_failed(run_id, "follow-up failed")

    class FakeSqlReportRepository:
        def __init__(self, session):
            pass

        def get(self, report_id):
            return SimpleNamespace(title="AI report", markdown="# persisted report")

    def safe_update(run_id, payload, report_id):
        with session_scope() as session:
            repository = AnalysisRunRepository(session)
            repository.update_payload(run_id, payload)
            repository.mark_success(run_id, report_id)
        return True

    async def auto_follow_up(report_id):
        captured["report_id"] = report_id
        return {"status": "not_needed", "source_report_id": report_id}

    service = _service(
        session_scope_factory=session_scope,
        analysis_run_repository_cls=AnalysisRunRepository,
        report_repository_cls=FakeSqlReportRepository,
        workflow_recorder_factory=lambda: WorkflowCheckpointRecorder(
            session_scope_factory=session_scope
        ),
        safe_update_run_success_func=safe_update,
        auto_follow_up_func=auto_follow_up,
    )

    result = run_async(service.resume(run_id))

    with session_scope() as session:
        resumed = AnalysisRunRepository(session).get(run_id)
        payload = json.loads(resumed.payload_json)

    assert captured["report_id"] == 88
    assert result["report"]["markdown"] == "# persisted report"
    assert resumed.status == "success"
    assert resumed.error is None
    assert payload["workflow"]["status"] == "success"
    assert payload["workflow"]["resume"]["resumable"] is False
    assert payload["report_id"] == 88


def test_discovered_pipeline_resume_source_ingestion_requires_discovery_artifact() -> None:
    payload = WorkflowCheckpointRecorder.initialize_payload(
        {"topic": "AI 產業鏈"},
        "ai_discovered_topic_pipeline",
        ["topic_discovery", "source_ingestion", "auto_follow_up"],
        "2026-05-31T09:00:00",
    )
    payload = WorkflowCheckpointRecorder.fail_step_payload(
        payload,
        "source_ingestion",
        "network failed",
        "2026-05-31T09:01:00",
    )

    class ExistingRunRepository(FakeRunRepository):
        def get(self, run_id):
            return SimpleNamespace(id=run_id, payload_json=json.dumps(payload), report_id=None)

    service = _service(analysis_run_repository_cls=ExistingRunRepository)

    with pytest.raises(ReportExecutionError, match="resume requires discovery.plan"):
        run_async(service.resume(77))


def _service(**overrides) -> DiscoveredTopicPipelineService:
    async def default_discover_topic(service, topic):
        return {"plan": {"candidate_companies": []}, "plan_quality": {"status": "ready"}}

    async def default_ingestion(
        payload, service, plan, limit_per_query, evidence_limit, max_queries, document_limit
    ):
        return {
            "urls": [],
            "end_date": date(2026, 5, 31),
            "documents": [],
            "fixed_source_ingestion": {},
            "dynamic_query_ingestion": [],
            "ingestion_results": [],
            "source_audit": {"total_stored_count": 0},
            "candidates": [FakeCandidate()],
        }

    async def noop_auto_follow_up(report_id):
        return {"status": "not_needed"}

    defaults = {
        "session_scope_factory": fake_session_scope,
        "analysis_run_repository_cls": FakeRunRepository,
        "report_repository_cls": FakeReportRepository,
        "company_filing_repository_cls": FakeCompanyFilingRepository,
        "topic_discovery_service_cls": FakeTopicDiscoveryService,
        "topic_discovery_plan_cls": FakePlanClass,
        "supply_chain_whitelist_cls": FakeWhitelist,
        "workflow_recorder_factory": FakeWorkflowRecorder,
        "discovered_market_data_service_factory": lambda: FakeMarketDataService(),
        "discovered_report_builder_service_factory": lambda: FakeReportBuilderService(),
        "discover_topic_with_timeout_func": default_discover_topic,
        "discovery_fetch_settings_func": lambda payload: (5, 40, 12),
        "discovery_document_limit_func": lambda payload, evidence_limit: 100,
        "run_topic_discovery_ingestion_func": default_ingestion,
        "should_revalidate_candidate_filings_func": lambda candidates: False,
        "candidate_filing_revalidation_tickers_func": lambda candidates, payload: [],
        "company_filing_timeout_result_func": lambda tickers, exc, source: {
            "requested_tickers": tickers,
            "source": source,
            "stored_count": 0,
        },
        "dedupe_documents_func": lambda documents: list(dict.fromkeys(documents)),
        "apply_company_filing_gate_func": lambda candidates: candidates,
        "summarize_candidate_support_payload_func": lambda candidates: {"total": len(candidates)},
        "summarize_candidate_support_func": lambda candidates: {"total": len(candidates)},
        "safe_update_run_success_func": lambda run_id, payload, report_id: True,
        "safe_mark_run_failed_func": lambda run_id, error: None,
        "auto_follow_up_func": noop_auto_follow_up,
        "workflow_steps": [
            "topic_discovery",
            "source_ingestion",
            "candidate_revalidation",
            "market_data_refresh",
            "report_build",
            "auto_follow_up",
        ],
    }
    defaults.update(overrides)
    return DiscoveredTopicPipelineService(**defaults)


def run_async(coro):
    import asyncio

    return asyncio.run(coro)
