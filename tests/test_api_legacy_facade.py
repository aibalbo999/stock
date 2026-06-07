from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.api.compatibility_helpers import compatibility_helper_namespace
from app.api.legacy_facade import LegacyApiFacade
from app.api.schemas import FollowUpRunRequest
from app.services.api_compatibility import ApiCompatibilityService
from app.services.report_generator import ReportExecutionError


def test_legacy_api_facade_is_deprecated_service_alias() -> None:
    assert issubclass(LegacyApiFacade, ApiCompatibilityService)


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


def test_api_compatibility_service_builds_default_follow_up_payload() -> None:
    captured = {}

    class FollowUpRunService:
        async def run(self, report_id, payload):
            captured["report_id"] = report_id
            captured["payload"] = payload
            return {"status": "queued"}

    class Services:
        def report_follow_up_run(self):
            return FollowUpRunService()

    class Request:
        pass

    facade = ApiCompatibilityService(
        api_services=Services(),
        candidate_revalidation_module=object(),
        follow_up_run_request_cls=Request,
    )

    result = asyncio.run(facade.run_report_follow_up(7))

    assert result == {"status": "queued"}
    assert captured["report_id"] == 7
    assert isinstance(captured["payload"], Request)


def test_compatibility_helper_namespace_lazily_delegates_and_uses_global_provider() -> None:
    captured = {}

    class Compatibility:
        def sufficient_company_filing_tickers(self, tickers):
            return {"never-called"}

        def count_sufficient_company_filings(self, tickers):
            return 2

        def apply_company_filing_gate_to_candidate_payload(self, candidates, sufficient_tickers_provider):
            captured["sufficient"] = sufficient_tickers_provider(["2330"])
            return candidates

    globals_map = {
        "sufficient_company_filing_tickers": lambda tickers: {"2330"},
    }
    namespace = compatibility_helper_namespace(
        lambda: Compatibility(),
        globals_provider=lambda: globals_map,
    )

    assert namespace["count_sufficient_company_filings"](["2330"]) == 2
    assert namespace["apply_company_filing_gate_to_candidate_payload"]([{"ticker": "2330"}]) == [
        {"ticker": "2330"}
    ]
    assert captured["sufficient"] == {"2330"}
