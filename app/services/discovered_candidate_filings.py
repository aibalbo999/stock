from __future__ import annotations

from typing import Any

from app.data_sources.company_filing_http import company_filing_error
from app.services.company_filing_results import (
    company_filing_attempt_result,
    company_filing_gap_summary,
    company_filing_next_actions,
    company_filing_ticker_result,
)
from app.services.discovery_workflow import is_deep_discovery


def should_revalidate_candidate_filings(
    candidates: list[dict], min_supported_ratio: float = 0.6
) -> bool:
    if not candidates:
        return False
    supported = sum(
        1 for candidate in candidates if candidate.get("status") == "evidence_supported"
    )
    return (supported / len(candidates)) < min_supported_ratio


def candidate_filing_revalidation_tickers(candidates: list[dict], payload: Any) -> list[str]:
    limit = 20 if is_deep_discovery(payload) else 12
    prioritized = [
        str(candidate.get("ticker"))
        for candidate in candidates
        if candidate.get("ticker") and candidate.get("status") != "evidence_supported"
    ]
    fallback = [str(candidate.get("ticker")) for candidate in candidates if candidate.get("ticker")]
    return list(dict.fromkeys([*prioritized, *fallback]))[:limit]


def company_filing_timeout_result(tickers: list[str], exc: Exception, source: str) -> dict:
    errors = [
        {
            **company_filing_error(source, exc, stage="timeout"),
            "ticker": ticker,
            "company_name": "",
        }
        for ticker in tickers
    ]
    per_ticker_results = [
        company_filing_ticker_result(
            ticker,
            "",
            [],
            ("annual_report",),
            [error],
            [company_filing_attempt_result(source, [], [error])],
        )
        for ticker, error in zip(tickers, errors)
    ]
    return {
        "requested_tickers": tickers,
        "stored_count": 0,
        "items": [],
        "errors": errors,
        "per_ticker_results": per_ticker_results,
        "missing_tickers": list(tickers),
        "gap_summary": company_filing_gap_summary(per_ticker_results),
        "next_actions": company_filing_next_actions(per_ticker_results),
        "source": f"{source} timed out",
    }
