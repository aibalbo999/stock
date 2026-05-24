from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.core.time import now_taipei
from app.api import main
from app.models.schemas import NewsDocument, ReportResponse, Source
from app.services.report_quality import (
    parse_quality_gate_from_markdown,
    render_quality_action_guard_markdown,
    summarize_document_source_quality,
)


class DummyQueuedTask:
    id = "queued-task-id"


class DummyTaskResult:
    def __init__(self, status: str, ready: bool, successful: bool, result: object) -> None:
        self.status = status
        self._ready = ready
        self._successful = successful
        self.result = result

    def ready(self) -> bool:
        return self._ready

    def successful(self) -> bool:
        return self._successful


class DummyRun:
    id = 19
    source = "celery"
    status = "success"
    payload_json = '{"celery_task_id": "task-linked"}'
    report_id = 11
    output_path = "reports/demo.md"
    error = None
    started_at = datetime(2026, 5, 24, 4, 52, 33)
    finished_at = datetime(2026, 5, 24, 4, 52, 50)


def test_task_status_success(monkeypatch) -> None:
    def fake_async_result(task_id: str) -> DummyTaskResult:
        assert task_id == "task-ok"
        return DummyTaskResult(
            "SUCCESS",
            True,
            True,
            {"run_id": 1, "id": 2, "title": "report"},
        )

    monkeypatch.setattr(main.celery_app, "AsyncResult", fake_async_result)

    response = TestClient(main.app).get("/tasks/task-ok")

    assert response.status_code == 200
    assert response.json() == {
        "task_id": "task-ok",
        "status": "SUCCESS",
        "ready": True,
        "successful": True,
        "result": {"run_id": 1, "id": 2, "title": "report"},
    }


def test_task_status_includes_linked_run(monkeypatch) -> None:
    class FakeRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_celery_task_id(self, task_id: str) -> DummyRun | None:
            assert task_id == "task-linked"
            return DummyRun()

    @contextmanager
    def fake_session_scope():
        yield object()

    def fake_async_result(task_id: str) -> DummyTaskResult:
        assert task_id == "task-linked"
        return DummyTaskResult("SUCCESS", True, True, {"run_id": 19})

    monkeypatch.setattr(main.celery_app, "AsyncResult", fake_async_result)
    monkeypatch.setattr(main, "AnalysisRunRepository", FakeRunRepository)
    monkeypatch.setattr(main, "session_scope", fake_session_scope)

    response = TestClient(main.app).get("/tasks/task-linked")

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == "task-linked"
    assert body["status"] == "SUCCESS"
    assert body["run"]["id"] == 19
    assert body["run"]["report_id"] == 11
    assert body["run"]["payload"] == '{"celery_task_id": "task-linked"}'


def test_generate_report_async_queues_celery_task(monkeypatch) -> None:
    captured_payload = {}

    def fake_delay(payload: dict) -> DummyQueuedTask:
        captured_payload.update(payload)
        return DummyQueuedTask()

    monkeypatch.setattr(main.generate_report_task, "delay", fake_delay)

    response = TestClient(main.app).post(
        "/reports/generate_async",
        json={
            "topic": "AI 產業鏈",
            "tickers": ["2330"],
            "lookback_days": 7,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"task_id": "queued-task-id", "status": "queued"}
    assert captured_payload == {
        "topic": "AI 產業鏈",
        "tickers": ["2330"],
        "lookback_days": 7,
        "evidence_limit": 40,
        "investor_capital": 1000000,
        "beginner_mode": True,
        "investor_profile": "beginner",
        "max_position_pct": 0.1,
        "cash_reserve_pct": 0.3,
    }


def test_generate_report_sync_attaches_quality_gate_from_used_evidence(monkeypatch) -> None:
    captured = {"updated_payloads": []}

    class FakeGenerator:
        def __init__(self) -> None:
            self.last_evidence_documents = ["used-doc"]

        def generate(self, request) -> ReportResponse:
            assert request.topic == "AI 產業鏈"
            return ReportResponse(
                title="AI 產業鏈 自動分析報告",
                markdown="# AI 產業鏈 自動分析報告\n\n## 一頁摘要\n- 測試",
            )

    class FakeReport:
        id = 77

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def create(self, request, response) -> FakeReport:
            captured["stored_quality_gate"] = response.quality_gate
            return FakeReport()

    class FakeAnalysisRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def start(self, source: str, payload: dict) -> DummyRun:
            assert source == "api_sync"
            captured["start_payload"] = payload
            return DummyRun()

        def update_payload(self, run_id: int, payload: dict) -> None:
            assert run_id == DummyRun.id
            captured["updated_payloads"].append(payload)

        def mark_success(self, run_id: int, report_id: int) -> None:
            assert run_id == DummyRun.id
            assert report_id == FakeReport.id
            captured["marked_success"] = True

        def mark_failed(self, run_id: int, error: str) -> None:
            captured["failed"] = error

    @contextmanager
    def fake_session_scope():
        yield object()

    def fake_quality_gate_for_request(request, documents=None, source_count=None) -> dict:
        captured["quality_documents"] = documents
        captured["quality_source_count"] = source_count
        return {
            "status": "ready",
            "blockers": [],
            "warnings": [],
            "action_policy": {"policy": "actionable", "label": "通過品質門檻"},
            "metrics": {
                "promoted_count": 1,
                "candidate_supported_ratio": 1,
                "dynamic_source_count": 1,
                "market_coverage": 1,
                "monthly_revenue_coverage": 1,
                "valuation_coverage": 1,
            },
            "recommendation": "資料品質達到本系統產出投資建議的基本門檻。",
        }

    monkeypatch.setattr(main, "ReportGenerator", FakeGenerator)
    monkeypatch.setattr(main, "ReportRepository", FakeReportRepository)
    monkeypatch.setattr(main, "AnalysisRunRepository", FakeAnalysisRunRepository)
    monkeypatch.setattr(main, "session_scope", fake_session_scope)
    monkeypatch.setattr(main, "build_quality_gate_for_request", fake_quality_gate_for_request)

    response = TestClient(main.app).post(
        "/reports/generate",
        json={
            "topic": "AI 產業鏈",
            "tickers": ["2330"],
            "lookback_days": 7,
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["quality_gate"]["status"] == "ready"
    assert "## 報告品質門檻" in body["markdown"]
    assert captured["quality_documents"] == ["used-doc"]
    assert captured["quality_source_count"] is None
    assert captured["stored_quality_gate"]["status"] == "ready"
    assert captured["updated_payloads"][0]["evidence_count"] == 1
    assert captured["marked_success"] is True


def test_source_audit_summarizes_fixed_and_dynamic_ingestion() -> None:
    payload = main.TopicDiscoveryRequest(
        topic="AI 產業鏈",
        lookback_days=21,
        deep_analysis=True,
        include_international=True,
    )

    audit = main.build_source_audit(
        payload=payload,
        urls=["https://news.google.com/search?q=AI", "https://news.google.com/search?q=HBM"],
        fixed_source_ingestion={
            "count": 2,
            "items": [{"title": "固定來源 A"}, {"title": "固定來源 B"}],
            "errors": [],
        },
        dynamic_query_ingestion=[
            {
                "count": 3,
                "items": [{"title": "動態來源 A"}, {"title": "動態來源 B"}],
                "errors": [{"source": "bad", "error": "timeout"}],
            },
            {
                "count": 1,
                "items": [{"title": "動態來源 C"}],
                "errors": [],
            },
        ],
        limit_per_query=12,
        evidence_limit=120,
        max_queries=80,
    )

    assert audit["topic"] == "AI 產業鏈"
    assert audit["lookback_days"] == 21
    assert audit["deep_analysis"] is True
    assert audit["include_international"] is True
    assert audit["fixed_sources"]["stored_count"] == 2
    assert audit["dynamic_queries"]["stored_count"] == 4
    assert audit["dynamic_query_count"] == 2
    assert audit["total_stored_count"] == 6
    assert audit["total_error_count"] == 1
    assert audit["dynamic_query_sample"] == [
        "https://news.google.com/search?q=AI",
        "https://news.google.com/search?q=HBM",
    ]


def test_deep_discovery_fetch_settings_raise_source_and_evidence_limits() -> None:
    payload = main.TopicDiscoveryRequest(
        topic="AI 產業鏈",
        limit_per_query=5,
        evidence_limit=40,
        deep_analysis=True,
    )

    assert main.discovery_fetch_settings(payload) == (12, 120, 80)


def test_discovery_query_budget_reserves_supplemental_capacity() -> None:
    normal_budget = main.discovery_query_budget(30, deep_analysis=False)
    deep_budget = main.discovery_query_budget(80, deep_analysis=True)

    assert normal_budget["initial_queries"] < 30
    assert normal_budget["supplemental_queries"] > 0
    assert normal_budget["supplemental_rounds"] == 2
    assert deep_budget["initial_queries"] < 80
    assert deep_budget["supplemental_queries"] > normal_budget["supplemental_queries"]
    assert deep_budget["supplemental_rounds"] == 3


def test_source_audit_marks_low_candidate_coverage_for_supplement() -> None:
    audit = {
        "dynamic_queries": {"stored_count": 30},
    }
    candidate_support = {
        "total": 5,
        "supported": 2,
        "unsupported": 3,
        "supported_ratio": 0.4,
    }

    assert main.should_supplement_discovery_sources(audit, candidate_support) is True


def test_source_audit_accepts_sufficient_candidate_and_source_coverage() -> None:
    audit = {
        "dynamic_queries": {"stored_count": 18},
    }
    candidate_support = {
        "total": 5,
        "supported": 4,
        "unsupported": 1,
        "supported_ratio": 0.8,
    }

    assert main.should_supplement_discovery_sources(audit, candidate_support) is False


def test_summarize_document_source_quality_measures_diversity_and_recency() -> None:
    recent = now_taipei().date() - timedelta(days=2)
    old = now_taipei().date() - timedelta(days=45)
    documents = [
        NewsDocument(
            id="doc-1",
            title="近期 A",
            text="測試",
            source=Source(title="近期 A", publisher="Source A", published_at=recent),
        ),
        NewsDocument(
            id="doc-2",
            title="近期 B",
            text="測試",
            source=Source(title="近期 B", publisher="Source B", published_at=recent),
        ),
        NewsDocument(
            id="doc-3",
            title="舊資料",
            text="測試",
            source=Source(title="舊資料", publisher="Source A", published_at=old),
        ),
        NewsDocument(
            id="doc-4",
            title="無日期",
            text="測試",
            source=Source(title="無日期", publisher="Source C"),
        ),
    ]

    quality = summarize_document_source_quality(documents, lookback_days=14)

    assert quality["total_documents"] == 4
    assert quality["unique_publisher_count"] == 3
    assert quality["timestamped_count"] == 3
    assert quality["timestamp_coverage"] == 0.75
    assert quality["recent_count"] == 2
    assert quality["recent_coverage"] == 0.5


def test_report_quality_gate_blocks_undated_sources() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {"supported_ratio": 0.8},
            "dynamic_queries": {"stored_count": 12},
        },
        promoted_tickers=["2330"],
        market_count=1,
        monthly_revenue_count=1,
        financial_metrics_count=12,
        valuation_count=1,
        source_quality={
            "unique_publisher_count": 3,
            "timestamp_coverage": 0.25,
            "recent_coverage": 0.8,
        },
    )

    assert gate["status"] == "insufficient"
    assert "來源時間戳覆蓋率低於 50%" in gate["blockers"]


def test_report_quality_gate_warns_on_low_source_diversity() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {"supported_ratio": 0.8},
            "dynamic_queries": {"stored_count": 12},
        },
        promoted_tickers=["2330"],
        market_count=1,
        monthly_revenue_count=1,
        financial_metrics_count=12,
        valuation_count=1,
        source_quality={
            "unique_publisher_count": 2,
            "timestamp_coverage": 1,
            "recent_coverage": 1,
        },
    )

    assert gate["status"] == "caution"
    assert "資料來源多樣性偏低" in gate["warnings"]


def test_report_quality_gate_blocks_weak_research_inputs() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {"supported_ratio": 0.4},
            "dynamic_queries": {"stored_count": 5},
        },
        promoted_tickers=[],
        market_count=0,
        monthly_revenue_count=0,
        financial_metrics_count=0,
        valuation_count=0,
        investor_capital=1_000_000,
        cash_reserve_pct=0.3,
    )

    assert gate["status"] == "insufficient"
    assert gate["action_policy"]["policy"] == "research_only"
    assert gate["action_policy"]["max_deployable_amount"] == 0
    assert "沒有通過證據驗證的正式分析股票" in gate["blockers"]
    assert "候選公司證據覆蓋率低於 60%" in gate["blockers"]


def test_report_quality_gate_passes_complete_research_inputs() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {"supported_ratio": 0.8},
            "dynamic_queries": {"stored_count": 24},
        },
        promoted_tickers=["2330", "2382"],
        market_count=2,
        monthly_revenue_count=2,
        financial_metrics_count=20,
        valuation_count=2,
        investor_capital=1_000_000,
        cash_reserve_pct=0.3,
    )

    assert gate["status"] == "ready"
    assert gate["action_policy"]["policy"] == "actionable"
    assert gate["action_policy"]["max_deployable_amount"] == 700_000
    assert gate["blockers"] == []
    assert gate["warnings"] == []


def test_report_quality_gate_caps_caution_deployable_amount() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {"supported_ratio": 0.8},
            "dynamic_queries": {"stored_count": 10},
        },
        promoted_tickers=["2330"],
        market_count=1,
        monthly_revenue_count=1,
        financial_metrics_count=6,
        valuation_count=1,
        investor_capital=1_000_000,
        cash_reserve_pct=0.3,
    )

    assert gate["status"] == "caution"
    assert gate["action_policy"]["policy"] == "manual_review_required"
    assert gate["action_policy"]["max_deployable_amount"] == 175_000


def test_attach_quality_gate_to_report_persists_gate_in_markdown_and_payload() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {"supported_ratio": 0.8},
            "dynamic_queries": {"stored_count": 24},
        },
        promoted_tickers=["2330"],
        market_count=1,
        monthly_revenue_count=1,
        financial_metrics_count=12,
        valuation_count=1,
        investor_capital=1_000_000,
        cash_reserve_pct=0.3,
    )
    response = ReportResponse(
        title="AI 產業鏈 自動分析報告",
        markdown="# AI 產業鏈 自動分析報告\n\n## 一頁摘要\n- 測試",
    )

    updated = main.attach_quality_gate_to_report(response, gate)

    assert updated.quality_gate == gate
    assert "## 報告品質門檻" in updated.markdown
    assert updated.markdown.find("## 報告品質門檻") < updated.markdown.find("## 一頁摘要")
    assert "狀態：資料品質可用" in updated.markdown
    assert "本輪品質門檻後可投入上限：約 700,000 元" in updated.markdown


def test_parse_quality_gate_from_markdown_restores_history_report_metrics() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {"supported_ratio": 0.8},
            "dynamic_queries": {"stored_count": 24},
        },
        promoted_tickers=["2330"],
        market_count=1,
        monthly_revenue_count=1,
        financial_metrics_count=12,
        valuation_count=1,
        investor_capital=1_000_000,
        cash_reserve_pct=0.3,
        source_quality={
            "unique_publisher_count": 5,
            "timestamp_coverage": 0.92,
            "recent_coverage": 0.75,
        },
    )
    response = main.attach_quality_gate_to_report(
        ReportResponse(
            title="AI 產業鏈 自動分析報告",
            markdown="# AI 產業鏈 自動分析報告\n\n## 一頁摘要\n- 測試",
        ),
        gate,
    )

    parsed = parse_quality_gate_from_markdown(response.markdown)

    assert parsed is not None
    assert parsed["status"] == "ready"
    assert parsed["action_policy"]["max_deployable_amount"] == 700_000
    assert parsed["metrics"]["promoted_count"] == 1
    assert parsed["metrics"]["dynamic_source_count"] == 24
    assert parsed["metrics"]["source_unique_publishers"] == 5
    assert parsed["metrics"]["source_timestamp_coverage"] == 0.92
    assert parsed["metrics"]["source_recent_coverage"] == 0.75


def test_attach_quality_gate_adds_action_guard_for_insufficient_report() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {"supported_ratio": 0.3},
            "dynamic_queries": {"stored_count": 3},
        },
        promoted_tickers=[],
        market_count=0,
        monthly_revenue_count=0,
        financial_metrics_count=0,
        valuation_count=0,
    )
    response = ReportResponse(
        title="AI 產業鏈 自動分析報告",
        markdown="# AI 產業鏈 自動分析報告\n\n## 投資建議\n- 測試",
    )

    updated = main.attach_quality_gate_to_report(response, gate)

    assert "## 投資行動限制" in updated.markdown
    assert "不得視為買入清單" in updated.markdown
    assert updated.markdown.find("## 投資行動限制") < updated.markdown.find("## 投資建議")


def test_attach_quality_gate_replaces_existing_quality_sections() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {"supported_ratio": 0.8},
            "dynamic_queries": {"stored_count": 24},
        },
        promoted_tickers=["2330"],
        market_count=1,
        monthly_revenue_count=1,
        financial_metrics_count=12,
        valuation_count=1,
    )
    response = ReportResponse(
        title="AI 產業鏈 自動分析報告",
        markdown=(
            "# AI 產業鏈 自動分析報告\n\n"
            "## 報告品質門檻\n"
            "- 狀態：資料不足\n"
            "- 阻擋項：舊資料不足\n\n"
            "## 投資行動限制\n"
            "- 舊限制段落\n\n"
            "## 一頁摘要\n"
            "- 測試"
        ),
    )

    updated = main.attach_quality_gate_to_report(response, gate)

    assert updated.markdown.count("## 報告品質門檻") == 1
    assert "狀態：資料品質可用" in updated.markdown
    assert "狀態：資料不足" not in updated.markdown
    assert "舊資料不足" not in updated.markdown
    assert "舊限制段落" not in updated.markdown
    assert "## 投資行動限制" not in updated.markdown
    assert updated.markdown.find("## 報告品質門檻") < updated.markdown.find("## 一頁摘要")


def test_attach_quality_gate_replaces_ready_section_with_new_action_guard() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {"supported_ratio": 0.3},
            "dynamic_queries": {"stored_count": 3},
        },
        promoted_tickers=[],
        market_count=0,
        monthly_revenue_count=0,
        financial_metrics_count=0,
        valuation_count=0,
    )
    response = ReportResponse(
        title="AI 產業鏈 自動分析報告",
        markdown=(
            "# AI 產業鏈 自動分析報告\n\n"
            "## 報告品質門檻\n"
            "- 狀態：資料品質可用\n\n"
            "## 投資建議\n"
            "- 舊建議"
        ),
    )

    updated = main.attach_quality_gate_to_report(response, gate)

    assert updated.markdown.count("## 報告品質門檻") == 1
    assert updated.markdown.count("## 投資行動限制") == 1
    assert "狀態：資料不足" in updated.markdown
    assert "狀態：資料品質可用" not in updated.markdown
    assert "不得視為買入清單" in updated.markdown
    assert updated.markdown.find("## 投資行動限制") < updated.markdown.find("## 投資建議")


def test_ready_quality_gate_does_not_add_action_guard() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {"supported_ratio": 0.8},
            "dynamic_queries": {"stored_count": 24},
        },
        promoted_tickers=["2330"],
        market_count=1,
        monthly_revenue_count=1,
        financial_metrics_count=12,
        valuation_count=1,
    )

    assert render_quality_action_guard_markdown(gate) == ""


def test_task_status_failure(monkeypatch) -> None:
    def fake_async_result(task_id: str) -> DummyTaskResult:
        assert task_id == "task-failed"
        return DummyTaskResult("FAILURE", True, False, RuntimeError("boom"))

    monkeypatch.setattr(main.celery_app, "AsyncResult", fake_async_result)

    response = TestClient(main.app).get("/tasks/task-failed")

    assert response.status_code == 200
    assert response.json() == {
        "task_id": "task-failed",
        "status": "FAILURE",
        "ready": True,
        "successful": False,
        "error": "boom",
    }


def test_task_status_pending(monkeypatch) -> None:
    def fake_async_result(task_id: str) -> DummyTaskResult:
        assert task_id == "task-pending"
        return DummyTaskResult("PENDING", False, False, None)

    monkeypatch.setattr(main.celery_app, "AsyncResult", fake_async_result)

    response = TestClient(main.app).get("/tasks/task-pending")

    assert response.status_code == 200
    assert response.json() == {
        "task_id": "task-pending",
        "status": "PENDING",
        "ready": False,
        "successful": False,
    }


def test_get_run_by_task_id(monkeypatch) -> None:
    class FakeRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_celery_task_id(self, task_id: str) -> DummyRun | None:
            assert task_id == "task-linked"
            return DummyRun()

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(main, "AnalysisRunRepository", FakeRunRepository)
    monkeypatch.setattr(main, "session_scope", fake_session_scope)

    response = TestClient(main.app).get("/tasks/task-linked/run")

    assert response.status_code == 200
    assert response.json() == {
        "id": 19,
        "source": "celery",
        "status": "success",
        "payload": '{"celery_task_id": "task-linked"}',
        "report_id": 11,
        "output_path": "reports/demo.md",
        "error": None,
        "started_at": "2026-05-24T04:52:33",
        "finished_at": "2026-05-24T04:52:50",
    }


def test_get_run_by_task_id_not_found(monkeypatch) -> None:
    class FakeRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_celery_task_id(self, task_id: str) -> None:
            assert task_id == "missing"
            return None

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(main, "AnalysisRunRepository", FakeRunRepository)
    monkeypatch.setattr(main, "session_scope", fake_session_scope)

    response = TestClient(main.app).get("/tasks/missing/run")

    assert response.status_code == 404
    assert response.json() == {"detail": "run not found for task"}
