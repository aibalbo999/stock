from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.time import now_taipei
from app.api import main
from app.models.schemas import NewsDocument, ReportResponse, Source
from app.services.followup_actions import FollowUpAction
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


def test_generate_report_async_requires_whitelisted_ticker(monkeypatch) -> None:
    def fake_delay(payload: dict) -> DummyQueuedTask:
        raise AssertionError("task should not be queued without whitelisted tickers")

    monkeypatch.setattr(main.generate_report_task, "delay", fake_delay)

    response = TestClient(main.app).post(
        "/reports/generate_async",
        json={
            "topic": "AI 產業鏈",
            "tickers": [],
            "lookback_days": 7,
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "async report generation requires at least one whitelisted ticker"
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

    def fake_quality_gate_for_request(request, documents=None, source_count=None, llm_result=None) -> dict:
        captured["quality_documents"] = documents
        captured["quality_source_count"] = source_count
        captured["quality_llm_result"] = llm_result
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
        query_metadata=[
            {
                "url": "https://news.google.com/search?q=AI",
                "query": "AI",
                "source_type": "subtopic",
                "hypothesis": "驗證 AI 需求",
                "evidence_type": "需求/成長",
                "language": "en",
            },
            {
                "url": "https://news.google.com/search?q=HBM",
                "query": "HBM",
                "source_type": "coverage_gap",
                "hypothesis": "補齊 HBM 缺口",
                "evidence_type": "品質缺口補強",
                "language": "en",
            },
        ],
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
    assert audit["query_type_counts"] == {"subtopic": 1, "coverage_gap": 1}
    assert audit["query_type_labels"]["subtopic"]["label"] == "子題查詢"
    assert audit["query_type_labels"]["coverage_gap"]["label"] == "缺口補強查詢"
    assert audit["query_metadata_sample"][1]["source_type"] == "coverage_gap"
    assert audit["query_metadata_sample"][0]["hypothesis"] == "驗證 AI 需求"
    assert audit["query_metadata_sample"][1]["evidence_type"] == "品質缺口補強"


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


def test_source_audit_supplements_when_plan_query_quality_is_not_ready() -> None:
    audit = {
        "dynamic_queries": {"stored_count": 30},
        "plan_quality": {
            "status": "caution",
            "query_quality": {
                "total_queries": 2,
                "generic_query_count": 1,
            },
        },
    }
    candidate_support = {
        "total": 5,
        "supported": 5,
        "unsupported": 0,
        "supported_ratio": 1,
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
            "candidate_support": {
                "supported_ratio": 0.8,
                "formal_confidence_avg": 88.5,
                "formal_confidence_min": 80,
            },
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


def test_report_quality_gate_warns_when_llm_falls_back() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {
                "supported_ratio": 1.0,
                "formal_confidence_avg": 88.5,
                "formal_confidence_min": 80,
            },
            "dynamic_queries": {"stored_count": 24},
        },
        promoted_tickers=["2330"],
        market_count=1,
        monthly_revenue_count=1,
        financial_metrics_count=12,
        valuation_count=1,
        llm_status={"fallback": True, "model": None, "key_index": None},
    )

    assert gate["status"] == "caution"
    assert "LLM 補充分析未啟用或呼叫失敗，個股結論需視為規則引擎草稿" in gate["warnings"]
    assert gate["metrics"]["llm_analysis_status"] == "fallback"
    assert any("檢查 LLM API key" in action for action in gate["remediation_actions"])


def test_report_company_data_audit_endpoint(monkeypatch) -> None:
    class FakeSession:
        pass

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    def fake_audit(session, report_id):
        assert isinstance(session, FakeSession)
        assert report_id == 7
        return {"status": "needs_attention", "rows": [{"ticker": "3017", "status": "partial"}]}

    monkeypatch.setattr(main, "session_scope", fake_session_scope)
    monkeypatch.setattr(main, "audit_report_company_data", fake_audit)

    response = TestClient(main.app).get("/reports/7/company-data-audit")

    assert response.status_code == 200
    assert response.json()["rows"][0]["ticker"] == "3017"


def test_report_quality_gate_records_enabled_llm_as_observation() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {
                "supported_ratio": 1.0,
                "formal_confidence_avg": 88.5,
                "formal_confidence_min": 80,
            },
            "dynamic_queries": {"stored_count": 24},
        },
        promoted_tickers=["2330"],
        market_count=1,
        monthly_revenue_count=1,
        financial_metrics_count=12,
        valuation_count=1,
        llm_status={"fallback": False, "model": "gemini-test", "key_index": 2},
    )

    assert gate["status"] == "ready"
    assert gate["metrics"]["llm_analysis_status"] == "enabled"
    assert gate["metrics"]["llm_model"] == "gemini-test"
    assert gate["metrics"]["llm_key_index"] == 2
    assert "LLM 補充分析已完成，且仍受來源與白名單驗證約束" in gate["observations"]


def test_candidate_support_summarizes_formal_confidence_scores() -> None:
    summary = main.summarize_candidate_support(
        [
            SimpleNamespace(status="evidence_supported", evidence_confidence_score=88),
            SimpleNamespace(status="evidence_supported", evidence_confidence_score=76),
            SimpleNamespace(status="weak_evidence", evidence_confidence_score=60),
        ]
    )

    assert summary["supported"] == 2
    assert summary["formal_confidence_avg"] == 82
    assert summary["formal_confidence_min"] == 76
    assert summary["formal_low_confidence_count"] == 0


def test_report_quality_gate_blocks_low_confidence_formal_stocks() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {
                "supported_ratio": 1.0,
                "formal_supported_ratio": 1.0,
                "formal_confidence_avg": 72,
                "formal_confidence_min": 68,
                "formal_low_confidence_count": 1,
            },
            "dynamic_queries": {"stored_count": 24},
        },
        promoted_tickers=["2330"],
        market_count=1,
        monthly_revenue_count=1,
        financial_metrics_count=12,
        valuation_count=1,
    )

    assert gate["status"] == "insufficient"
    assert "正式分析股票含低信心證據公司" in gate["blockers"]
    assert gate["metrics"]["formal_confidence_avg"] == 72
    assert any("低信心正式股票" in action for action in gate["remediation_actions"])


def test_report_quality_gate_treats_broad_candidate_list_as_observation_after_promotion() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {
                "supported_ratio": 0.4,
                "exploration_supported_ratio": 0.4,
                "formal_supported_ratio": 1.0,
            },
            "dynamic_queries": {"stored_count": 24},
        },
        promoted_tickers=["2330", "2382"],
        market_count=2,
        monthly_revenue_count=2,
        financial_metrics_count=20,
        valuation_count=2,
    )

    assert gate["status"] == "ready"
    assert gate["blockers"] == []
    assert gate["warnings"] == []
    assert "AI 初始候選清單較廣，已由二次篩選收斂為正式分析股票" in gate["observations"]
    assert gate["metrics"]["candidate_supported_ratio"] == 1.0
    assert gate["metrics"]["exploration_candidate_supported_ratio"] == 0.4
    assert gate["remediation_actions"] == []


def test_report_quality_gate_accepts_diffuse_exploration_when_formal_stocks_are_verified() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {
                "supported_ratio": 0.2,
                "exploration_supported_ratio": 0.2,
                "formal_supported_ratio": 1.0,
            },
            "dynamic_queries": {"stored_count": 24},
        },
        promoted_tickers=["2330"],
        market_count=1,
        monthly_revenue_count=1,
        financial_metrics_count=12,
        valuation_count=1,
    )

    assert gate["status"] == "ready"
    assert gate["blockers"] == []
    assert "AI 初始候選清單較廣，已由二次篩選收斂為正式分析股票" in gate["observations"]


def test_report_quality_gate_blocks_weak_formal_stocks() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {
                "supported_ratio": 0.8,
                "exploration_supported_ratio": 0.8,
                "formal_supported_ratio": 0.75,
            },
            "dynamic_queries": {"stored_count": 24},
        },
        promoted_tickers=["2330", "2382"],
        market_count=2,
        monthly_revenue_count=2,
        financial_metrics_count=20,
        valuation_count=2,
    )

    assert gate["status"] == "insufficient"
    assert "正式分析股票仍含弱證據公司" in gate["blockers"]


def test_report_quality_gate_warns_when_leading_signal_coverage_is_low() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {"supported_ratio": 1.0},
            "dynamic_queries": {"stored_count": 24},
        },
        promoted_tickers=["2330", "2382"],
        market_count=2,
        monthly_revenue_count=2,
        financial_metrics_count=20,
        valuation_count=2,
        leading_signal_count=0,
    )

    assert gate["status"] == "caution"
    assert "領先訊號覆蓋偏低，潛力/風險排序信心需下修" in gate["warnings"]
    assert gate["metrics"]["leading_signal_coverage"] == 0
    assert any("補齊股價歷史" in action for action in gate["remediation_actions"])


def test_report_quality_gate_blocks_incomplete_discovery_plan() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {
                "supported_ratio": 0.8,
                "formal_confidence_avg": 88.5,
                "formal_confidence_min": 80,
            },
            "dynamic_queries": {"stored_count": 24},
        },
        promoted_tickers=["2330"],
        market_count=1,
        monthly_revenue_count=1,
        financial_metrics_count=12,
        valuation_count=1,
        plan_quality={
            "status": "insufficient",
            "score": 30,
            "missing": ["缺少估值/股價研究任務"],
        },
    )

    assert gate["status"] == "insufficient"
    assert gate["action_policy"]["policy"] == "research_only"
    assert any("AI 拆解任務品質不足" in blocker for blocker in gate["blockers"])
    assert gate["metrics"]["discovery_plan_status"] == "insufficient"
    assert gate["metrics"]["discovery_plan_score"] == 30


def test_report_quality_gate_warns_on_caution_discovery_plan() -> None:
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
        plan_quality={
            "status": "caution",
            "score": 70,
            "missing": ["缺少風險/瓶頸研究任務"],
        },
    )

    assert gate["status"] == "caution"
    assert gate["action_policy"]["policy"] == "manual_review_required"
    assert gate["action_policy"]["max_deployable_amount"] == 175_000
    assert any("AI 拆解任務仍有缺口" in warning for warning in gate["warnings"])


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
            "candidate_support": {
                "supported_ratio": 0.8,
                "formal_confidence_avg": 88.5,
                "formal_confidence_min": 80,
            },
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
        plan_quality={
            "status": "ready",
            "score": 95,
            "missing": [],
        },
    )
    response = main.attach_quality_gate_to_report(
        ReportResponse(
            title="AI 產業鏈 自動分析報告",
            markdown="# AI 產業鏈 自動分析報告\n\n## 一頁摘要\n- 測試",
        ),
        gate,
    )

    assert "正式股票證據信心：平均 高 88.5 / 最低 高 80" in response.markdown

    parsed = parse_quality_gate_from_markdown(response.markdown)

    assert parsed is not None
    assert parsed["status"] == "ready"
    assert parsed["action_policy"]["max_deployable_amount"] == 700_000
    assert parsed["metrics"]["promoted_count"] == 1
    assert parsed["metrics"]["dynamic_source_count"] == 24
    assert parsed["metrics"]["source_unique_publishers"] == 5
    assert parsed["metrics"]["source_timestamp_coverage"] == 0.92
    assert parsed["metrics"]["source_recent_coverage"] == 0.75
    assert parsed["metrics"]["discovery_plan_status"] == "ready"
    assert parsed["metrics"]["discovery_plan_score"] == 95
    assert parsed["metrics"]["exploration_candidate_supported_ratio"] == 0.8
    assert parsed["metrics"]["formal_confidence_avg"] == 88.5
    assert parsed["metrics"]["formal_confidence_min"] == 80


def test_parse_quality_gate_from_markdown_restores_remediation_actions() -> None:
    gate = main.build_report_quality_gate(
        source_audit={
            "candidate_support": {"supported_ratio": 1.0},
            "dynamic_queries": {"stored_count": 10},
        },
        promoted_tickers=["2330"],
        market_count=1,
        monthly_revenue_count=1,
        financial_metrics_count=12,
        valuation_count=1,
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
    assert parsed["remediation_actions"] == gate["remediation_actions"]


def test_load_report_follow_up_context_restores_original_request(monkeypatch) -> None:
    class FakeReport:
        topic = "舊主題"
        tickers_json = '["2330"]'
        markdown = "# AI 產業鏈 自動分析報告\n\n## 一頁摘要\n- 測試"

    class FakeRun:
        payload_json = (
            '{"request":{"topic":"AI 產業鏈","tickers":["2330","2382"],'
            '"lookback_days":45,"evidence_limit":120},'
            '"candidate_whitelist":['
            '{"ticker":"2330","name":"台積電","segment":"晶圓代工","status":"evidence_supported",'
            '"evidence_count":2,"evidence_source_count":2},'
            '{"ticker":"3324","name":"雙鴻","segment":"散熱模組","status":"weak_evidence",'
            '"evidence_count":1,"evidence_source_count":1}]}'
        )

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get(self, report_id: int) -> FakeReport | None:
            assert report_id == 7
            return FakeReport()

    class FakeAnalysisRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_report_id(self, report_id: int) -> FakeRun:
            assert report_id == 7
            return FakeRun()

    monkeypatch.setattr(main, "ReportRepository", FakeReportRepository)
    monkeypatch.setattr(main, "AnalysisRunRepository", FakeAnalysisRunRepository)

    context = main.load_report_follow_up_context(7)

    assert context["request"].topic == "AI 產業鏈"
    assert context["request"].tickers == ["2330", "2382"]
    assert context["request"].lookback_days == 45
    assert context["request"].evidence_limit == 120
    assert "## 候選公司審計" in context["markdown"]
    assert "3324 雙鴻" in context["markdown"]
    assert len(context["candidate_whitelist"]) == 2


def test_report_candidate_audit_endpoint_restores_history_payload(monkeypatch) -> None:
    class FakeReport:
        id = 7
        title = "AI 產業鏈 自動分析報告"
        topic = "AI 產業鏈"
        tickers_json = '["2330"]'
        markdown = "# AI 產業鏈 自動分析報告\n\n## 一頁摘要\n測試"
        generated_at = now_taipei()

    class FakeRun:
        payload_json = (
            '{"candidate_whitelist":['
            '{"ticker":"2330","name":"台積電","segment":"晶圓代工","status":"evidence_supported",'
            '"evidence_count":2,"evidence_source_count":2},'
            '{"ticker":"3324","name":"雙鴻","segment":"散熱模組","status":"weak_evidence",'
            '"evidence_count":1,"evidence_source_count":1,"validation_reason":"弱證據：來源不足"}]}'
        )

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get(self, report_id: int) -> FakeReport | None:
            assert report_id == 7
            return FakeReport()

    class FakeAnalysisRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_report_id(self, report_id: int) -> FakeRun:
            assert report_id == 7
            return FakeRun()

    monkeypatch.setattr(main, "ReportRepository", FakeReportRepository)
    monkeypatch.setattr(main, "AnalysisRunRepository", FakeAnalysisRunRepository)

    response = TestClient(main.app).get("/reports/7/candidate-audit")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total"] == 2
    assert body["summary"]["weak_count"] == 1
    assert "3324 雙鴻" in body["markdown"]

    report_response = TestClient(main.app).get("/reports/7")
    assert "## 候選公司審計" in report_response.json()["markdown"]


def test_prepare_follow_up_report_context_revalidates_and_refreshes(monkeypatch) -> None:
    refreshed = {}

    async def fake_refresh(request):
        refreshed["tickers"] = request.tickers
        return {"market": {"stored_count": 2}}

    monkeypatch.setattr(
        main,
        "revalidate_candidate_whitelist",
        lambda run_payload, candidates: {
            "candidate_whitelist": [
                {
                    "ticker": "2330",
                    "name": "台積電",
                    "segment": "晶圓代工",
                    "status": "evidence_supported",
                },
                {
                    "ticker": "3324",
                    "name": "雙鴻",
                    "segment": "散熱模組",
                    "status": "evidence_supported",
                },
            ],
            "promoted_tickers": ["2330", "3324"],
            "newly_promoted": ["3324"],
            "no_longer_promoted": [],
            "status_changes": [
                {
                    "ticker": "3324",
                    "previous_status": "weak_evidence",
                    "current_status": "evidence_supported",
                }
            ],
            "changed": True,
        },
    )
    monkeypatch.setattr(main, "refresh_market_data_for_report", fake_refresh)

    context = {
        "run_payload": {"discovery": {"plan": {}}},
        "candidate_whitelist": [
            {"ticker": "2330", "name": "台積電", "segment": "晶圓代工", "status": "evidence_supported"},
            {"ticker": "3324", "name": "雙鴻", "segment": "散熱模組", "status": "weak_evidence"},
        ],
    }
    prepared = asyncio.run(
        main.prepare_follow_up_report_context(
            context,
            main.ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
            [FollowUpAction("ingest_news", "補候選", ("3324",), purpose="required")],
        )
    )

    assert prepared["request"].tickers == ["2330", "3324"]
    assert prepared["candidate_revalidation"]["changed"] is True
    assert prepared["candidate_revalidation"]["newly_promoted"] == ["3324"]
    assert refreshed["tickers"] == ["2330", "3324"]


def test_candidate_revalidation_queries_are_company_specific() -> None:
    plan = main.TopicDiscoveryPlan.model_validate(
        {
            "subtopics": [
                {
                    "name": "液冷散熱",
                    "required_evidence": ["水冷訂單", "機櫃功耗"],
                }
            ],
            "candidate_companies": [
                {
                    "ticker": "3324",
                    "name": "雙鴻",
                    "segment": "散熱模組",
                    "rationale": "",
                    "evidence_keywords": ["液冷", "AI 伺服器"],
                }
            ],
        }
    )

    queries = main.candidate_revalidation_queries(plan, "AI 產業鏈")

    assert any("3324" in query and "雙鴻" in query and "AI 產業鏈" in query for query in queries)
    assert any("液冷散熱" in query and "水冷訂單" in query for query in queries)


def test_collect_revalidation_documents_dedupes_and_falls_back() -> None:
    document = NewsDocument(
        id="doc-1",
        title="雙鴻 液冷散熱",
        text="雙鴻 AI 伺服器液冷散熱。",
        source=Source(title="雙鴻 液冷散熱"),
    )

    class FakeRepository:
        def __init__(self) -> None:
            self.queries = []

        def search_documents(self, query: str, limit: int = 20) -> list[NewsDocument]:
            self.queries.append(query)
            return [document, document]

        def latest_documents(self, limit: int = 20) -> list[NewsDocument]:
            raise AssertionError("should not fall back when search found documents")

    repository = FakeRepository()

    documents = main.collect_revalidation_documents(repository, ["3324 雙鴻", "散熱模組"], 10)

    assert repository.queries == ["3324 雙鴻", "散熱模組"]
    assert documents == [document]


def test_load_report_follow_up_context_raises_404(monkeypatch) -> None:
    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get(self, report_id: int) -> None:
            assert report_id == 404
            return None

    monkeypatch.setattr(main, "ReportRepository", FakeReportRepository)

    try:
        main.load_report_follow_up_context(404)
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "report not found"
    else:
        raise AssertionError("expected HTTPException")


def test_report_follow_up_endpoint_executes_actions_and_reruns(monkeypatch) -> None:
    class FakeReport:
        id = 7
        title = "AI 產業鏈 自動分析報告"
        topic = "AI 產業鏈"
        tickers_json = '["2330"]'
        markdown = (
            "# AI 產業鏈 自動分析報告\n\n"
            "## 監控清單\n"
            "| 股票 | 目前動作 | 重新研究條件 | 繼續避開/觀察條件 | 監控頻率 |\n"
            "|---|---|---|---|---|\n"
            "| 2330 台積電 | 觀察 / 等風險降低 | 補齊月營收與估值 | 降值風險高於 5% | 每週 |\n"
        )

    class NewReport:
        id = 8

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get(self, report_id: int) -> FakeReport | None:
            assert report_id == 7
            return FakeReport()

        def create(self, request, response) -> NewReport:
            assert request.tickers == ["2330"]
            assert "重跑後報告" in response.markdown
            return NewReport()

    class FakeRun:
        id = 31
        payload_json = '{"request":{"topic":"AI 產業鏈","tickers":["2330"],"lookback_days":30}}'

    class FakeAnalysisRunRepository:
        success_report_id = None

        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_report_id(self, report_id: int) -> FakeRun | None:
            assert report_id == 7
            return FakeRun()

        def start(self, source: str, payload: dict) -> FakeRun:
            assert source == "follow_up_api"
            assert payload["source_report_id"] == 7
            assert payload["planned_actions"]
            return FakeRun()

        def update_payload(self, run_id: int, payload: dict) -> FakeRun:
            assert run_id == 31
            assert payload["execution"] == {
                "actions": payload["planned_actions"],
                "results": {"refresh_monthly_revenue:2330": {"stored_count": 12, "errors": []}},
                "execution_summary": {
                    "task_result_count": 1,
                    "stored_count": 12,
                    "error_count": 0,
                    "has_errors": False,
                    "items": [],
                },
            }
            return FakeRun()

        def mark_success(self, run_id: int, report_id: int, output_path: str | None = None) -> FakeRun:
            assert run_id == 31
            FakeAnalysisRunRepository.success_report_id = report_id
            return FakeRun()

    class FakeGenerator:
        last_evidence_documents = []

        def generate(self, request):
            assert request.topic == "AI 產業鏈"
            return ReportResponse(title="重跑後報告", markdown="# 重跑後報告")

    async def fake_execute(actions, request, news_limit=30):
        assert {action.action_type for action in actions} >= {
            "refresh_monthly_revenue",
            "refresh_valuations",
            "rerun_analysis",
        }
        assert request.tickers == ["2330"]
        return {
            "actions": [action.to_dict() for action in actions],
            "results": {"refresh_monthly_revenue:2330": {"stored_count": 12, "errors": []}},
            "execution_summary": {
                "task_result_count": 1,
                "stored_count": 12,
                "error_count": 0,
                "has_errors": False,
                "items": [],
            },
        }

    monkeypatch.setattr(main, "ReportRepository", FakeReportRepository)
    monkeypatch.setattr(main, "AnalysisRunRepository", FakeAnalysisRunRepository)
    monkeypatch.setattr(main, "ReportGenerator", FakeGenerator)
    monkeypatch.setattr(main, "execute_follow_up_actions", fake_execute)
    monkeypatch.setattr("app.services.followup_actions.tracking_freshness_details_by_action", lambda actions, request: {})
    monkeypatch.setattr(
        main,
        "build_quality_gate_for_request",
        lambda request, documents, **kwargs: {"status": "ready", "warnings": [], "blockers": []},
    )

    response = TestClient(main.app).post("/reports/7/follow-up/run", json={"rerun_report": True})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "executed"
    assert body["run_id"] == 31
    assert body["summary"]["selected"]["total_count"] >= 3
    assert body["summary"]["execution"]["stored_count"] == 12
    assert body["rerun_report"]["report_id"] == 8
    assert FakeAnalysisRunRepository.success_report_id == 8


def test_report_follow_up_rerun_persists_revalidated_request(monkeypatch) -> None:
    captured = {}

    class FakeReport:
        topic = "AI 產業鏈"
        tickers_json = '["2330"]'
        markdown = (
            "# AI 產業鏈 自動分析報告\n\n"
            "## 候選公司審計\n"
            "| 股票 | 產業位置 | 狀態 | 證據 | 排除 / 升格原因 | 下一步 |\n"
            "|---|---|---|---:|---|---|\n"
            "| 2330 台積電 | 晶圓代工 | 正式分析 | 2 篇 / 2 來源 | 通過 | 納入正式分析 |\n"
            "| 3324 雙鴻 | 散熱模組 | 弱證據觀察 | 1 篇 / 1 來源 | 弱證據 | 補抓公司新聞 |\n"
        )

    class NewReport:
        id = 18

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get(self, report_id: int) -> FakeReport | None:
            assert report_id == 7
            return FakeReport()

        def create(self, request, response) -> NewReport:
            captured["created_request"] = request.model_dump(mode="json")
            return NewReport()

    class FakeRun:
        id = 61
        payload_json = (
            '{"request":{"topic":"AI 產業鏈","tickers":["2330"],"lookback_days":30},'
            '"candidate_whitelist":['
            '{"ticker":"2330","name":"台積電","segment":"晶圓代工","status":"evidence_supported"},'
            '{"ticker":"3324","name":"雙鴻","segment":"散熱模組","status":"weak_evidence"}]}'
        )

    class FakeAnalysisRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_report_id(self, report_id: int) -> FakeRun:
            assert report_id == 7
            return FakeRun()

        def start(self, source: str, payload: dict) -> FakeRun:
            return FakeRun()

        def update_payload(self, run_id: int, payload: dict) -> FakeRun:
            captured["payload"] = payload
            return FakeRun()

        def mark_success(self, run_id: int, report_id: int, output_path: str | None = None) -> FakeRun:
            return FakeRun()

    class FakeGenerator:
        last_evidence_documents = []

        def __init__(self, whitelist=None):
            self.whitelist = whitelist

        def generate(self, request):
            assert request.tickers == ["2330", "3324"]
            return ReportResponse(title="升格後報告", markdown="# 升格後報告")

    async def fake_execute(actions, request, news_limit=30):
        return {"actions": [action.to_dict() for action in actions], "results": {}, "execution_summary": {}}

    async def fake_refresh_market_data(request):
        captured["refreshed_request"] = request.model_dump(mode="json")
        return {}

    monkeypatch.setattr(main, "ReportRepository", FakeReportRepository)
    monkeypatch.setattr(main, "AnalysisRunRepository", FakeAnalysisRunRepository)
    monkeypatch.setattr(main, "ReportGenerator", FakeGenerator)
    monkeypatch.setattr(main, "execute_follow_up_actions", fake_execute)
    monkeypatch.setattr("app.services.followup_actions.tracking_freshness_details_by_action", lambda actions, request: {})
    monkeypatch.setattr(
        main,
        "revalidate_candidate_whitelist",
        lambda run_payload, candidates: {
            "candidate_whitelist": [
                {"ticker": "2330", "name": "台積電", "segment": "晶圓代工", "status": "evidence_supported"},
                {"ticker": "3324", "name": "雙鴻", "segment": "散熱模組", "status": "evidence_supported"},
            ],
            "promoted_tickers": ["2330", "3324"],
            "newly_promoted": ["3324"],
            "no_longer_promoted": [],
            "status_changes": [
                {
                    "ticker": "3324",
                    "previous_status": "weak_evidence",
                    "current_status": "evidence_supported",
                }
            ],
            "changed": True,
        },
    )
    monkeypatch.setattr(main, "refresh_market_data_for_report", fake_refresh_market_data)
    monkeypatch.setattr(main, "build_quality_gate_for_request", lambda request, documents, **kwargs: {"status": "ready"})

    response = TestClient(main.app).post("/reports/7/follow-up/run", json={"rerun_report": True})

    assert response.status_code == 200
    assert captured["created_request"]["tickers"] == ["2330", "3324"]
    assert captured["refreshed_request"]["tickers"] == ["2330", "3324"]
    assert captured["payload"]["request"]["tickers"] == ["2330", "3324"]
    assert captured["payload"]["candidate_whitelist"][1]["status"] == "evidence_supported"
    assert captured["payload"]["rerun_report"]["candidate_revalidation"]["newly_promoted"] == ["3324"]


def test_report_follow_up_endpoint_can_skip_tracking_when_required_only(monkeypatch) -> None:
    class FakeReport:
        topic = "AI 產業鏈"
        tickers_json = '["2330"]'
        markdown = (
            "# AI 產業鏈 自動分析報告\n\n"
            "## 監控清單\n"
            "| 股票 | 目前動作 | 重新研究條件 | 繼續避開/觀察條件 | 監控頻率 |\n"
            "|---|---|---|---|---|\n"
            "| 2330 台積電 | 觀察 / 等風險降低 | 領先訊號由偏空轉為中性以上 | 降值風險高於 5% | 每週 |\n"
        )

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get(self, report_id: int) -> FakeReport | None:
            assert report_id == 7
            return FakeReport()

    class FakeRun:
        id = 41
        payload_json = "{}"

    class FakeAnalysisRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_report_id(self, report_id: int) -> None:
            assert report_id == 7
            return None

        def start(self, source: str, payload: dict) -> FakeRun:
            raise AssertionError("no-op follow-up should not create a run by default")

        def update_payload(self, run_id: int, payload: dict) -> FakeRun:
            assert run_id == 41
            assert payload["planned_actions"] == []
            assert payload["status"] == "no_action_required"
            return FakeRun()

        def mark_success(self, run_id: int, report_id: int, output_path: str | None = None) -> FakeRun:
            assert run_id == 41
            FakeAnalysisRunRepository.marked_report_id = report_id
            return FakeRun()

    async def fake_execute(actions, request, news_limit=30):
        raise AssertionError("required-only run should skip tracking actions")

    monkeypatch.setattr(main, "ReportRepository", FakeReportRepository)
    monkeypatch.setattr(main, "AnalysisRunRepository", FakeAnalysisRunRepository)
    monkeypatch.setattr(main, "execute_follow_up_actions", fake_execute)
    monkeypatch.setattr("app.services.followup_actions.tracking_freshness_details_by_action", lambda actions, request: {})

    response = TestClient(main.app).post(
        "/reports/7/follow-up/run",
        json={"rerun_report": True, "purpose": "required"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "no_action_required"
    assert response.json()["run_id"] is None
    assert response.json()["summary"]["selected"]["total_count"] == 0
    assert response.json()["summary"]["available"]["tracking_count"] >= 1
    assert response.json()["available_actions"]


def test_report_follow_up_endpoint_can_force_fresh_tracking_actions(monkeypatch) -> None:
    class FakeReport:
        topic = "AI 產業鏈"
        tickers_json = '["2330"]'
        markdown = (
            "# AI 產業鏈 自動分析報告\n\n"
            "## 監控清單\n"
            "| 股票 | 目前動作 | 重新研究條件 | 繼續避開/觀察條件 | 監控頻率 |\n"
            "|---|---|---|---|---|\n"
            "| 2330 台積電 | 觀察 / 等風險降低 | 領先訊號由偏空轉為中性以上 | 降值風險高於 5% | 每週 |\n"
        )

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get(self, report_id: int) -> FakeReport | None:
            assert report_id == 7
            return FakeReport()

    class FakeRun:
        id = 51
        payload_json = "{}"

    class FakeAnalysisRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_report_id(self, report_id: int) -> None:
            assert report_id == 7
            return None

        def start(self, source: str, payload: dict) -> FakeRun:
            assert source == "follow_up_api"
            assert payload["force_refresh"] is True
            assert payload["planned_actions"]
            return FakeRun()

        def update_payload(self, run_id: int, payload: dict) -> FakeRun:
            assert run_id == 51
            assert payload["force_refresh"] is True
            return FakeRun()

        def mark_success(self, run_id: int, report_id: int, output_path: str | None = None) -> FakeRun:
            assert run_id == 51
            return FakeRun()

    async def fake_execute(actions, request, news_limit=30):
        assert any(action.action_type == "refresh_market" for action in actions)
        return {"actions": [action.to_dict() for action in actions], "results": {}, "execution_summary": {}}

    monkeypatch.setattr(main, "ReportRepository", FakeReportRepository)
    monkeypatch.setattr(main, "AnalysisRunRepository", FakeAnalysisRunRepository)
    monkeypatch.setattr(main, "execute_follow_up_actions", fake_execute)
    monkeypatch.setattr(
        main,
        "split_fresh_tracking_actions",
        lambda actions, request: (
            [],
            [
                {
                    **action.to_dict(),
                    "freshness": {"is_fresh": True, "max_age_days": 5, "latest_dates": {"2330": "2026-05-25"}},
                }
                for action in actions
                if action.action_type == "refresh_market"
            ],
        ),
    )

    response = TestClient(main.app).post(
        "/reports/7/follow-up/run",
        json={"rerun_report": False, "purpose": "tracking", "force_refresh": True},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "executed"
    assert response.json()["force_refresh"] is True


def test_report_follow_up_plan_preview_uses_report_history(monkeypatch) -> None:
    class FakeReport:
        topic = "AI 產業鏈"
        tickers_json = '["2330"]'
        markdown = (
            "# AI 產業鏈 自動分析報告\n\n"
            "## 監控清單\n"
            "| 股票 | 目前動作 | 重新研究條件 | 繼續避開/觀察條件 | 監控頻率 |\n"
            "|---|---|---|---|---|\n"
            "| 2330 台積電 | 觀察 / 等風險降低 | 補齊月營收與估值 | 降值風險高於 5% | 每週 |\n"
        )

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get(self, report_id: int) -> FakeReport | None:
            assert report_id == 7
            return FakeReport()

    class FakeRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_report_id(self, report_id: int) -> None:
            assert report_id == 7
            return None

    monkeypatch.setattr(main, "ReportRepository", FakeReportRepository)
    monkeypatch.setattr(main, "AnalysisRunRepository", FakeRunRepository)
    monkeypatch.setattr("app.services.followup_actions.tracking_freshness_details_by_action", lambda actions, request: {})

    response = TestClient(main.app).get("/reports/7/follow-up/plan")

    assert response.status_code == 200
    body = response.json()
    assert body["freshness"]["thresholds"]["refresh_market"] == 5
    action_types = {action["action_type"] for action in body["actions"]}
    assert "refresh_monthly_revenue" in action_types
    assert "refresh_valuations" in action_types
    assert "rerun_analysis" in action_types
    assert body["summary"]["tracking_count"] >= 1
    assert "| 任務 | 股票 | 性質 | 優先級 | 頻率 | 觸發原因 |" in body["markdown_preview"]


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
