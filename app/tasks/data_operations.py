from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from app.core.time import today_taipei
from app.services.ingestion import IngestionPipeline


def normalize_tickers(tickers: list[Any] | tuple[Any, ...] | None) -> list[str]:
    values = [str(ticker).strip() for ticker in tickers or [] if str(ticker).strip()]
    return list(dict.fromkeys(values))


def payload_date(payload: dict, key: str) -> date | None:
    value = payload.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def payload_smoke(payload: dict) -> bool:
    return bool(payload.get("smoke") or payload.get("task_submission_smoke"))


def market_refresh_smoke_result(
    *,
    tickers: list[str],
    start_date: date | None,
    end_date: date | None,
    today_func: Callable[[], date] = today_taipei,
) -> dict:
    resolved_end_date = end_date or today_func()
    resolved_start_date = start_date or resolved_end_date
    return {
        "smoke": True,
        "operation": "market_refresh",
        "mode": "task_submission_contract",
        "requested_tickers": tickers,
        "start_date": resolved_start_date.isoformat(),
        "end_date": resolved_end_date.isoformat(),
        "stored": [],
        "stored_history_count": 0,
        "stale_source_count": 0,
        "errors": [],
        "sources": [],
        "source": "task submission smoke no-op",
        "note": "No external market data providers are called when payload.smoke is true.",
    }


def cancellable_ingestion_pipeline(
    run_id: int | None = None,
    *,
    raise_if_cancelled_func: Callable[[int], None],
    ingestion_pipeline_cls: type = IngestionPipeline,
):
    if run_id is None:
        return ingestion_pipeline_cls()
    try:
        return ingestion_pipeline_cls(cancellation_checker=lambda: raise_if_cancelled_func(run_id))
    except TypeError:
        return ingestion_pipeline_cls()


async def run_data_operation_payload(
    operation: str,
    payload: dict,
    *,
    api_services_factory: Callable[[], Any],
    pipeline_factory: Callable[[int | None], Any],
    raise_if_cancelled_func: Callable[[int], None],
    today_func: Callable[[], date] = today_taipei,
    run_id: int | None = None,
) -> dict:
    services = api_services_factory()
    pipeline = pipeline_factory(run_id)
    tickers = normalize_tickers(payload.get("tickers") or [])
    start_date = payload_date(payload, "start_date")
    end_date = payload_date(payload, "end_date")
    if operation == "market_refresh":
        if payload_smoke(payload):
            return market_refresh_smoke_result(
                tickers=tickers,
                start_date=start_date,
                end_date=end_date,
                today_func=today_func,
            )
        resolved_end_date = end_date or today_func()
        resolved_start_date = start_date or resolved_end_date - timedelta(days=14)
        return await pipeline.refresh_market(
            tickers,
            resolved_start_date,
            resolved_end_date,
        )
    if operation == "fundamentals_refresh":
        resolved_end_date = end_date or today_func()
        resolved_start_date = start_date or resolved_end_date - timedelta(days=365 * 6)
        financial_metrics = await pipeline.refresh_financial_metrics(
            tickers,
            resolved_start_date,
            resolved_end_date,
        )
        if run_id is not None:
            raise_if_cancelled_func(run_id)
        valuations = await pipeline.refresh_valuations(
            tickers,
            resolved_end_date - timedelta(days=30),
            resolved_end_date,
        )
        return {"financial_metrics": financial_metrics, "valuations": valuations}
    if operation == "valuation_refresh":
        resolved_end_date = end_date or today_func()
        resolved_start_date = start_date or resolved_end_date - timedelta(days=30)
        return await pipeline.refresh_valuations(
            tickers,
            resolved_start_date,
            resolved_end_date,
        )
    if operation == "company_filings_fetch":
        return await pipeline.ingest_company_filings(
            tickers,
            limit_per_query=3,
            filter_allowed=bool(tickers),
        )
    if operation == "company_filing_from_url":
        return await services.company_filing_api().ingest_from_url(
            url=str(payload.get("url") or ""),
            ticker=str(payload.get("ticker") or ""),
            company_name=str(payload.get("company_name") or ""),
            document_type=str(payload.get("document_type") or "company_disclosure"),
            publisher=payload.get("publisher"),
            published_at=payload_date(payload, "published_at"),
        )
    if operation == "feed_fetch":
        return await pipeline.ingest_feeds(
            url=payload.get("url"),
            publisher=payload.get("publisher"),
            limit=int(payload.get("limit") or 10),
            enabled_sources_only=bool(payload.get("enabled_sources_only", True)),
            topic=payload.get("topic"),
        )
    raise ValueError(f"unsupported data operation task: {operation or 'missing'}")
