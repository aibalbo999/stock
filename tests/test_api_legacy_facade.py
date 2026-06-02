from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.api.legacy_facade import LegacyApiFacade
from app.api.schemas import FollowUpRunRequest
from app.services.report_generator import ReportExecutionError


def test_legacy_api_facade_delegates_candidate_filing_gate() -> None:
    captured = {}

    class CandidateModule:
        @staticmethod
        def apply_company_filing_gate_to_candidate_payload(candidates, sufficient_tickers_provider):
            captured["sufficient"] = sufficient_tickers_provider(["2330"])
            return [{**candidate, "gated": candidate["ticker"] in captured["sufficient"]} for candidate in candidates]

    class CandidateService:
        def sufficient_company_filing_tickers(self, tickers):
            return {"2330"}

    class Services:
        def candidate_revalidation(self):
            return CandidateService()

    facade = LegacyApiFacade(api_services=Services(), candidate_revalidation_module=CandidateModule)

    result = facade.apply_company_filing_gate_to_candidate_payload(
        [{"ticker": "2330"}, {"ticker": "2382"}]
    )

    assert captured["sufficient"] == {"2330"}
    assert result == [{"ticker": "2330", "gated": True}, {"ticker": "2382", "gated": False}]


def test_legacy_api_facade_maps_follow_up_report_errors_to_http() -> None:
    class FollowUpRunService:
        async def run(self, report_id, payload):
            raise ReportExecutionError("bad rerun")

    class Services:
        def report_follow_up_run(self):
            return FollowUpRunService()

    facade = LegacyApiFacade(api_services=Services(), candidate_revalidation_module=object())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(facade.run_report_follow_up(7, FollowUpRunRequest()))

    assert exc.value.status_code == 400
    assert exc.value.detail == "bad rerun"
