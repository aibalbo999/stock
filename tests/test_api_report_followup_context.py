from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

from app.core.time import now_taipei
from app.models.schemas import ReportRequest
from app.services.discovery_workflow import summarize_candidate_support
from app.services.followup_actions import FollowUpAction
from app.services.report_followup import (
    latest_follow_up_run_for_report,
    should_require_candidate_audit_follow_up,
)
from app.services.report_followup_context import (
    ReportFollowUpContextNotFound,
    ReportFollowUpContextService,
)
from app.services.report_query import ReportQueryService


def test_candidate_audit_follow_up_is_tracking_when_report_is_ready() -> None:
    assert (
        should_require_candidate_audit_follow_up(
            {"status": "ready"},
            {"status": "sufficient"},
        )
        is False
    )


def test_candidate_audit_follow_up_is_required_when_candidates_have_gaps() -> None:
    assert (
        should_require_candidate_audit_follow_up(
            {"status": "ready"},
            {"status": "sufficient"},
            [
                {"ticker": "2330", "status": "evidence_supported"},
                {"ticker": "2308", "status": "weak_evidence"},
                {"ticker": "2359", "status": "needs_evidence"},
            ],
        )
        is True
    )


def test_candidate_audit_follow_up_is_required_when_company_data_has_gaps() -> None:
    assert (
        should_require_candidate_audit_follow_up(
            {"status": "ready"},
            {"status": "needs_attention"},
        )
        is True
    )


def test_candidate_audit_follow_up_is_required_when_candidates_were_unavailable() -> None:
    assert (
        should_require_candidate_audit_follow_up(
            {"status": "ready"},
            {"status": "sufficient"},
            [{"ticker": "6235", "status": "evidence_unavailable"}],
        )
        is True
    )


def test_candidate_audit_follow_up_is_tracking_for_source_only_gap() -> None:
    assert (
        should_require_candidate_audit_follow_up(
            {
                "status": "insufficient",
                "blockers": ["主題拆解子題仍有 3 個完全缺少相關來源"],
                "warnings": ["主題拆解子題仍有 3 個來源或資料意圖不足"],
                "metrics": {
                    "promoted_count": 1,
                    "candidate_supported_ratio": 1.0,
                    "discovery_plan_status": "ready",
                },
            },
            {"status": "sufficient"},
        )
        is False
    )


def test_candidate_audit_follow_up_is_required_when_no_formal_stock() -> None:
    assert (
        should_require_candidate_audit_follow_up(
            {
                "status": "insufficient",
                "blockers": ["沒有通過證據驗證的正式分析股票"],
                "metrics": {
                    "promoted_count": 0,
                    "candidate_supported_ratio": 0.0,
                    "discovery_plan_status": "ready",
                },
            },
            {"status": "sufficient"},
        )
        is True
    )


def test_candidate_support_summarizes_formal_confidence_scores() -> None:
    summary = summarize_candidate_support(
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


def test_load_report_follow_up_context_restores_original_request() -> None:
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

    @contextmanager
    def fake_session_scope():
        yield object()

    service = ReportFollowUpContextService(
        session_scope_factory=fake_session_scope,
        report_repository_cls=FakeReportRepository,
        analysis_run_repository_cls=FakeAnalysisRunRepository,
        audit_company_data_func=lambda *args, **kwargs: {},
    )

    context = service.load(7)

    assert context["request"].topic == "AI 產業鏈"
    assert context["request"].tickers == ["2330", "2382"]
    assert context["request"].lookback_days == 45
    assert context["request"].evidence_limit == 120
    assert "## 候選公司審計" in context["markdown"]
    assert "3324 雙鴻" in context["markdown"]
    assert len(context["candidate_whitelist"]) == 2


def test_report_candidate_audit_service_restores_history_payload() -> None:
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

    @contextmanager
    def fake_session_scope():
        yield object()

    service = ReportQueryService(
        session_scope_factory=fake_session_scope,
        report_repository_cls=FakeReportRepository,
        analysis_run_repository_cls=FakeAnalysisRunRepository,
        latest_follow_up_run_for_report_func=lambda *args: None,
    )

    body = service.candidate_audit(7)
    assert body["summary"]["total"] == 2
    assert body["summary"]["weak_count"] == 1
    assert "3324 雙鴻" in body["markdown"]

    assert "## 候選公司審計" in service.get_report(7)["markdown"]


def test_get_report_includes_latest_auto_follow_up_run() -> None:
    class FakeReport:
        id = 7
        title = "AI 產業鏈 自動分析報告"
        topic = "AI 產業鏈"
        tickers_json = '["2330"]'
        markdown = (
            "# AI 產業鏈 自動分析報告\n\n"
            "## 一頁摘要\n測試\n"
            "- 2026-05-12 CMoney《1815 富喬-股市爆料同學會》\n"
        )
        generated_at = datetime(2026, 5, 28, 10, 0, 0)

    class ReportRun:
        payload_json = (
            '{"request":{"topic":"AI 產業鏈","tickers":["2330"]},'
            '"workflow":{"name":"standard_report_pipeline","status":"success"}}'
        )

    class FollowUpRun:
        id = 31
        source = "follow_up_api"
        status = "success"
        payload_json = (
            '{"source_report_id":7,"source_report_topic":"AI 產業鏈",'
            '"source_report_tickers":["2330"],'
            '"request":{"topic":"AI 產業鏈","tickers":["2330","2382"]},'
            '"summary":{"selected":{"required_count":2}},'
            '"planned_actions":[{"action_type":"ingest_news"}],'
            '"rerun_report":{"report_id":8}}'
        )
        report_id = 8
        output_path = None
        error = None
        started_at = datetime(2026, 5, 28, 10, 1, 0)
        finished_at = datetime(2026, 5, 28, 10, 5, 0)

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get(self, report_id: int):
            if report_id == 7:
                return FakeReport()
            if report_id == 8:
                return SimpleNamespace(
                    id=8,
                    title="AI 產業鏈 自動分析報告",
                    topic="AI 產業鏈",
                    tickers_json='["2330","2382"]',
                    markdown="# AI 產業鏈 自動分析報告\n",
                    generated_at=datetime(2026, 5, 28, 10, 6, 0),
                )
            raise AssertionError(f"unexpected report_id: {report_id}")

    class FakeAnalysisRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_report_id(self, report_id: int) -> ReportRun:
            assert report_id == 7
            return ReportRun()

        def latest(self, limit: int = 100) -> list[FollowUpRun]:
            return [FollowUpRun()]

    @contextmanager
    def fake_session_scope():
        yield object()

    service = ReportQueryService(
        session_scope_factory=fake_session_scope,
        report_repository_cls=FakeReportRepository,
        analysis_run_repository_cls=FakeAnalysisRunRepository,
    )

    body = service.get_report(7)
    auto_follow_up = body["auto_follow_up"]
    assert auto_follow_up["id"] == 31
    assert auto_follow_up["status"] == "success"
    assert auto_follow_up["summary"]["selected"]["required_count"] == 2
    assert auto_follow_up["rerun_report"]["report_id"] == 8
    assert body["workflow"]["name"] == "standard_report_pipeline"
    assert "股市爆料同學會" not in body["markdown"]


def test_get_report_ignores_stale_or_mismatched_auto_follow_up_run() -> None:
    class FakeReport:
        id = 7
        title = "AI 產業鏈 自動分析報告"
        topic = "AI 產業鏈"
        tickers_json = '["2330"]'
        markdown = "# AI 產業鏈 自動分析報告\n\n## 一頁摘要\n測試"
        generated_at = datetime(2026, 5, 28, 10, 0, 0)

    class ReportRun:
        payload_json = '{"request":{"topic":"AI 產業鏈","tickers":["2330"]}}'

    class MismatchedFollowUpRun:
        id = 31
        source = "follow_up_api"
        status = "success"
        payload_json = (
            '{"source_report_id":7,"request":{"topic":"機器人 產業鏈","tickers":["2308"]},'
            '"summary":{"selected":{"required_count":2}}}'
        )
        report_id = 8
        output_path = None
        error = None
        started_at = datetime(2026, 5, 28, 10, 2, 0)
        finished_at = datetime(2026, 5, 28, 10, 5, 0)

    class StaleFollowUpRun:
        id = 30
        source = "follow_up_api"
        status = "success"
        payload_json = (
            '{"source_report_id":7,"request":{"topic":"AI 產業鏈","tickers":["2330"]},'
            '"summary":{"selected":{"required_count":1}}}'
        )
        report_id = 7
        output_path = None
        error = None
        started_at = datetime(2026, 5, 28, 1, 59, 0)
        finished_at = datetime(2026, 5, 28, 1, 59, 30)

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get(self, report_id: int) -> FakeReport | None:
            assert report_id == 7
            return FakeReport()

    class FakeAnalysisRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_report_id(self, report_id: int) -> ReportRun:
            assert report_id == 7
            return ReportRun()

        def latest(self, limit: int = 100) -> list:
            return [MismatchedFollowUpRun(), StaleFollowUpRun()]

    @contextmanager
    def fake_session_scope():
        yield object()

    service = ReportQueryService(
        session_scope_factory=fake_session_scope,
        report_repository_cls=FakeReportRepository,
        analysis_run_repository_cls=FakeAnalysisRunRepository,
    )

    assert service.get_report(7)["auto_follow_up"] is None


def test_latest_follow_up_prefers_latest_finished_matching_run() -> None:
    report = SimpleNamespace(
        id=7,
        topic="AI 產業鏈",
        tickers_json='["2330"]',
        generated_at=datetime(2026, 5, 28, 10, 0, 0),
    )
    newer_started_run = SimpleNamespace(
        id=31,
        source="follow_up_api",
        status="success",
        payload_json=(
            '{"source_report_id":7,"source_report_topic":"AI 產業鏈",'
            '"source_report_tickers":["2330"],"rerun_report":{"report_id":8}}'
        ),
        report_id=8,
        output_path=None,
        error=None,
        started_at=datetime(2026, 5, 28, 3, 30, 0),
        finished_at=datetime(2026, 5, 28, 3, 35, 0),
    )
    later_finished_run = SimpleNamespace(
        id=30,
        source="follow_up_api",
        status="success",
        payload_json=(
            '{"source_report_id":7,"source_report_topic":"AI 產業鏈",'
            '"source_report_tickers":["2330"],"rerun_report":{"report_id":9}}'
        ),
        report_id=9,
        output_path=None,
        error=None,
        started_at=datetime(2026, 5, 28, 3, 0, 0),
        finished_at=datetime(2026, 5, 28, 3, 40, 0),
    )
    repository = SimpleNamespace(latest=lambda limit=100: [newer_started_run, later_finished_run])

    auto_follow_up = latest_follow_up_run_for_report(repository, report)

    assert auto_follow_up["id"] == 30
    assert auto_follow_up["rerun_report"]["report_id"] == 9


def test_latest_follow_up_rejects_rerun_report_with_different_actual_topic() -> None:
    report = SimpleNamespace(
        id=18,
        topic="機器人 產業鏈",
        tickers_json='["2308"]',
        generated_at=datetime(2026, 5, 31, 22, 8, 0),
    )
    run = SimpleNamespace(
        id=147,
        source="follow_up_api",
        status="success",
        payload_json=(
            '{"source_report_id":18,'
            '"request":{"topic":"機器人 產業鏈","tickers":["2308"]},'
            '"rerun_report":{"report_id":19}}'
        ),
        report_id=19,
        output_path=None,
        error=None,
        started_at=datetime(2026, 5, 31, 22, 9, 0),
        finished_at=datetime(2026, 5, 31, 22, 10, 0),
    )
    report_repository = SimpleNamespace(
        get=lambda report_id: SimpleNamespace(
            id=report_id,
            topic="AI 產業鏈低關注潛力股",
            generated_at=datetime(2026, 5, 31, 22, 10, 0),
        )
    )
    repository = SimpleNamespace(latest=lambda limit=100: [run])

    auto_follow_up = latest_follow_up_run_for_report(repository, report, report_repository)

    assert auto_follow_up is None


def test_prepare_follow_up_report_context_revalidates_and_refreshes() -> None:
    refreshed = {}

    async def fake_refresh(request):
        refreshed["tickers"] = request.tickers
        return {"market": {"stored_count": 2}}

    service = ReportFollowUpContextService(
        revalidate_candidate_whitelist_func=lambda run_payload, candidates: {
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
        refresh_market_data_func=fake_refresh,
    )

    context = {
        "run_payload": {"discovery": {"plan": {}}},
        "candidate_whitelist": [
            {
                "ticker": "2330",
                "name": "台積電",
                "segment": "晶圓代工",
                "status": "evidence_supported",
            },
            {"ticker": "3324", "name": "雙鴻", "segment": "散熱模組", "status": "weak_evidence"},
        ],
    }
    prepared = asyncio.run(
        service.prepare(
            context,
            ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
            [FollowUpAction("ingest_news", "補候選", ("3324",), purpose="required")],
        )
    )

    assert prepared["request"].tickers == ["2330", "3324"]
    assert prepared["candidate_revalidation"]["changed"] is True
    assert prepared["candidate_revalidation"]["newly_promoted"] == ["3324"]
    assert refreshed["tickers"] == ["2330", "3324"]


def test_prepare_follow_up_report_context_keeps_previous_promotions_when_revalidation_is_inconclusive() -> (
    None
):
    async def fake_refresh(request):
        raise AssertionError("unchanged promotions should not force market refresh")

    service = ReportFollowUpContextService(
        revalidate_candidate_whitelist_func=lambda run_payload, candidates: {
            "candidate_whitelist": [
                {
                    "ticker": "2330",
                    "name": "台積電",
                    "segment": "晶圓代工",
                    "status": "needs_evidence",
                }
            ],
            "promoted_tickers": [],
            "newly_promoted": [],
            "no_longer_promoted": ["2330"],
            "status_changes": [
                {
                    "ticker": "2330",
                    "previous_status": "evidence_supported",
                    "current_status": "needs_evidence",
                }
            ],
            "changed": True,
        },
        refresh_market_data_func=fake_refresh,
    )

    context = {
        "run_payload": {"discovery": {"plan": {}}},
        "candidate_whitelist": [
            {
                "ticker": "2330",
                "name": "台積電",
                "segment": "晶圓代工",
                "status": "evidence_supported",
            },
        ],
    }
    prepared = asyncio.run(
        service.prepare(
            context,
            ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
            [FollowUpAction("ingest_news", "補候選", ("2330",), purpose="required")],
        )
    )

    assert prepared["request"].tickers == ["2330"]
    assert prepared["candidate_whitelist"][0]["status"] == "evidence_supported"
    assert prepared["candidate_revalidation"]["revalidation_status"] == "kept_previous_promotions"
    assert prepared["candidate_revalidation"]["changed"] is False


def test_load_report_follow_up_context_raises_404() -> None:
    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get(self, report_id: int) -> None:
            assert report_id == 404
            return None

    @contextmanager
    def fake_session_scope():
        yield object()

    service = ReportFollowUpContextService(
        session_scope_factory=fake_session_scope,
        report_repository_cls=FakeReportRepository,
        audit_company_data_func=lambda *args, **kwargs: {},
    )
    try:
        service.load(404)
    except ReportFollowUpContextNotFound as exc:
        assert str(exc) == "report not found"
    else:
        raise AssertionError("expected ReportFollowUpContextNotFound")
