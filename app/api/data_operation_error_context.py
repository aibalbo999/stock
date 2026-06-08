from __future__ import annotations

from typing import Any


DATA_OPERATION_PROVIDER_HINTS = {
    "market_refresh": "FinMind / Fugle / TWSE fallback",
    "fundamentals_refresh": "FinMind / Fugle fundamentals fallback",
    "valuation_refresh": "FinMind / Fugle valuation fallback",
    "company_filings_fetch": "MOPS/TWSE/TPEx filing fetch with render/unlocker fallback",
    "company_filing_from_url": "direct filing URL fetch",
    "feed_fetch": "RSS/news feed fetch",
}


def data_operation_error_context(operation: str, payload: dict[str, Any] | None) -> dict:
    body = payload if isinstance(payload, dict) else {}
    tickers = _context_tickers(body)
    context = {
        "task": "data_operation",
        "failure_stage": "task_submission",
        "operation": operation,
        "provider_hint": DATA_OPERATION_PROVIDER_HINTS.get(operation, "configured data operation provider"),
        "payload_keys": sorted(str(key) for key in body.keys()),
    }
    if tickers:
        context["tickers"] = tickers[:20]
        context["ticker_count"] = len(tickers)
    for key in ("start_date", "end_date", "published_at", "document_type", "topic"):
        if body.get(key) is not None:
            context[key] = str(body[key])
    return context


def _context_tickers(payload: dict) -> list[str]:
    raw_tickers = payload.get("tickers")
    if isinstance(raw_tickers, list):
        return [str(ticker).strip() for ticker in raw_tickers if str(ticker).strip()]
    ticker = str(payload.get("ticker") or "").strip()
    return [ticker] if ticker else []
