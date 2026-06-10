from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.models.schemas import ReportRequest
from app.services.followup_actions import FollowUpAction
from app.services.report_followup_context import (
    ReportFollowUpContextNotFound,
    ReportFollowUpContextService,
)


@contextmanager
def fake_session_scope():
    yield object()


class FakeReportRepository:
    def __init__(self, session):
        pass

    def get(self, report_id):
        if report_id != 7:
            return None
        return SimpleNamespace(
            id=7,
            topic="AI 產業鏈",
            tickers_json='["2330"]',
            markdown="# AI 產業鏈\n",
            generated_at=datetime(2026, 5, 30, 10, 0, 0),
            created_at=datetime(2026, 5, 30, 10, 1, 0),
        )


class FakeAnalysisRunRepository:
    def __init__(self, session):
        pass

    def get_by_report_id(self, report_id):
        if report_id != 7:
            return None
        return SimpleNamespace(
            payload_json=(
                '{"request":{"topic":"AI 產業鏈","tickers":["2330"],"lookback_days":120},'
                '"candidate_whitelist":[{"ticker":"2330","status":"evidence_supported"}],'
                '"source_audit":{"stored_count":4}}'
            )
        )


class FakePipeline:
    def __init__(self):
        self.calls = []

    async def refresh_market(self, tickers, start_date, end_date, filter_allowed=True):
        self.calls.append(("market", tickers, start_date, end_date, filter_allowed))
        return {"stored_count": 1}

    async def refresh_monthly_revenue(self, tickers, start_date, end_date, filter_allowed=True):
        self.calls.append(("monthly_revenue", tickers, start_date, end_date, filter_allowed))
        return {"stored_count": 2}

    async def refresh_financial_metrics(self, tickers, start_date, end_date, filter_allowed=True):
        self.calls.append(("financial_metrics", tickers, start_date, end_date, filter_allowed))
        return {"stored_count": 3}

    async def refresh_valuations(self, tickers, start_date, end_date, filter_allowed=True):
        self.calls.append(("valuations", tickers, start_date, end_date, filter_allowed))
        return {"stored_count": 4}


def test_report_follow_up_context_service_loads_request_and_audits() -> None:
    captured = {}

    def fake_audit(session, tickers, markdown, run_payload):
        captured["audit"] = {
            "tickers": tickers,
            "markdown": markdown,
            "run_payload": run_payload,
        }
        return {"status": "sufficient"}

    service = ReportFollowUpContextService(
        session_scope_factory=fake_session_scope,
        report_repository_cls=FakeReportRepository,
        analysis_run_repository_cls=FakeAnalysisRunRepository,
        audit_company_data_func=fake_audit,
        parse_quality_gate_func=lambda markdown: {"status": "ready"},
        candidate_revalidation_service=SimpleNamespace(revalidate_candidate_whitelist=lambda payload, candidates: {}),
    )

    context = service.load(7)

    assert context["request"].lookback_days == 120
    assert context["candidate_whitelist"] == [{"ticker": "2330", "status": "evidence_supported"}]
    assert context["source_audit"] == {"stored_count": 4}
    assert context["company_data_audit"] == {"status": "sufficient"}
    assert captured["audit"]["tickers"] == ["2330"]


def test_report_follow_up_context_service_raises_not_found() -> None:
    service = ReportFollowUpContextService(
        session_scope_factory=fake_session_scope,
        report_repository_cls=FakeReportRepository,
        analysis_run_repository_cls=FakeAnalysisRunRepository,
        candidate_revalidation_service=SimpleNamespace(revalidate_candidate_whitelist=lambda payload, candidates: {}),
    )

    with pytest.raises(ReportFollowUpContextNotFound):
        service.load(404)


def test_report_follow_up_context_service_prepare_revalidates_and_refreshes() -> None:
    refreshed = {}

    async def fake_refresh(request):
        refreshed["tickers"] = request.tickers
        return {"market": {"stored_count": 1}}

    service = ReportFollowUpContextService(
        session_scope_factory=fake_session_scope,
        candidate_revalidation_service=SimpleNamespace(revalidate_candidate_whitelist=lambda payload, candidates: {}),
        revalidate_candidate_whitelist_func=lambda payload, candidates: {
            "candidate_whitelist": [
                {"ticker": "2330", "name": "台積電", "segment": "晶圓代工", "status": "evidence_supported"},
                {"ticker": "3324", "name": "雙鴻", "segment": "散熱模組", "status": "evidence_supported"},
            ],
            "promoted_tickers": ["2330", "3324"],
            "newly_promoted": ["3324"],
            "no_longer_promoted": [],
            "status_changes": [],
            "changed": True,
        },
        refresh_market_data_func=fake_refresh,
    )

    prepared = run_async(
            service.prepare(
                {
                    "run_payload": {},
                    "candidate_whitelist": [
                        {"ticker": "2330", "name": "台積電", "segment": "晶圓代工", "status": "evidence_supported"}
                    ],
                },
            ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
            [FollowUpAction("ingest_news", "補候選", ("3324",), purpose="required")],
        )
    )

    assert prepared["request"].tickers == ["2330", "3324"]
    assert prepared["candidate_revalidation"]["newly_promoted"] == ["3324"]
    assert refreshed["tickers"] == ["2330", "3324"]


def test_report_follow_up_context_service_prepare_builds_whitelist_from_legacy_report_tickers() -> None:
    service = ReportFollowUpContextService(
        session_scope_factory=fake_session_scope,
        candidate_revalidation_service=SimpleNamespace(revalidate_candidate_whitelist=lambda payload, candidates: {}),
    )

    prepared = run_async(
        service.prepare(
            {
                "source_report_tickers": ["2408", "2344", "8299", "2451", "3260", "4967", "2337", "8150"],
                "source_report_topic": "記憶體產業鏈",
                "run_payload": {},
                "candidate_whitelist": [],
            },
            ReportRequest(
                topic="記憶體產業鏈",
                tickers=["2408", "2344", "8299", "2451", "3260", "4967", "2337", "8150"],
                lookback_days=120,
            ),
            [FollowUpAction("rerun_analysis", "重跑分析報告", ("8150",), purpose="tracking")],
        )
    )

    assert prepared["request"].tickers[-1] == "8150"
    assert prepared["whitelist"] is not None
    assert "8150" in prepared["whitelist"].allowed_tickers()
    assert prepared["candidate_whitelist"][-1] == {
        "ticker": "8150",
        "name": "8150",
        "segment": "記憶體產業鏈",
        "status": "evidence_supported",
        "metadata": {"source": "legacy_report_tickers"},
    }


def test_report_follow_up_context_service_refresh_market_data_uses_calendar_windows() -> None:
    pipeline = FakePipeline()
    service = ReportFollowUpContextService(
        session_scope_factory=fake_session_scope,
        candidate_revalidation_service=SimpleNamespace(revalidate_candidate_whitelist=lambda payload, candidates: {}),
        ingestion_pipeline_cls=lambda: pipeline,
        today_func=lambda: date(2026, 6, 1),
    )

    result = run_async(service.refresh_market_data(ReportRequest(topic="AI", tickers=["2330"], lookback_days=120)))

    assert result["market"] == {"stored_count": 1}
    assert [call[0] for call in pipeline.calls] == ["market", "monthly_revenue", "financial_metrics", "valuations"]
    assert all(call[-1] is False for call in pipeline.calls)
    assert pipeline.calls[0][2] == date(2025, 10, 4)
    assert pipeline.calls[1][2] == date(2025, 3, 8)
    assert pipeline.calls[2][2] == date(2020, 6, 2)
    assert pipeline.calls[3][2] == date(2026, 2, 1)


def run_async(coro):
    import asyncio

    return asyncio.run(coro)
