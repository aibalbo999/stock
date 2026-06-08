from __future__ import annotations

from datetime import date, datetime, timedelta

from app.core.time import now_taipei
from app.models.schemas import NewsDocument
from app.services.source_quality import summarize_source_credibility


STALE_MARKET_SOURCE_MARKER = "cached-stale"
LATEST_ONLY_MARKET_SOURCE_MARKER = "latest-only"


def summarize_document_source_quality(documents: list[NewsDocument], lookback_days: int) -> dict:
    total = len(documents)
    if not total:
        return {
            "total_documents": 0,
            "unique_publisher_count": 0,
            "timestamped_count": 0,
            "timestamp_coverage": 0,
            "recent_count": 0,
            "recent_coverage": 0,
            "lookback_days": lookback_days,
            "publisher_sample": [],
            "average_credibility": None,
            "high_credibility_count": 0,
            "low_credibility_count": 0,
            "high_credibility_ratio": None,
            "low_credibility_ratio": None,
            "credibility_tier_counts": {},
        }
    cutoff = now_taipei().date() - timedelta(days=max(1, lookback_days))
    publishers = {
        _normalize_publisher(
            document.source.publisher or document.source.url or document.source.title
        )
        for document in documents
        if _normalize_publisher(
            document.source.publisher or document.source.url or document.source.title
        )
    }
    published_dates = [
        _source_date(document.source.published_at)
        for document in documents
        if _source_date(document.source.published_at) is not None
    ]
    recent_count = sum(1 for published_at in published_dates if published_at >= cutoff)
    return {
        "total_documents": total,
        "unique_publisher_count": len(publishers),
        "timestamped_count": len(published_dates),
        "timestamp_coverage": len(published_dates) / total,
        "recent_count": recent_count,
        "recent_coverage": recent_count / total,
        "lookback_days": lookback_days,
        "publisher_sample": sorted(publishers)[:5],
        **_source_credibility_quality(documents),
    }


def _source_credibility_quality(documents: list[NewsDocument]) -> dict:
    credibility = summarize_source_credibility(documents)
    return {
        "average_credibility": credibility["average_weight"],
        "high_credibility_count": credibility["high_credibility_count"],
        "low_credibility_count": credibility["low_credibility_count"],
        "high_credibility_ratio": credibility["high_credibility_ratio"],
        "low_credibility_ratio": credibility["low_credibility_ratio"],
        "credibility_tier_counts": credibility["tier_counts"],
    }


def _source_date(value: date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def date_value(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def date_lag_days(
    value: date | datetime | str | None, reference: date | datetime | str | None
) -> int | None:
    value_date = date_value(value)
    reference_date = date_value(reference)
    if value_date is None or reference_date is None:
        return None
    return max(0, (reference_date - value_date).days)


def date_to_text(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _normalize_publisher(value: str | None) -> str:
    return (value or "").strip()


def is_stale_market_data_source(source: object) -> bool:
    return STALE_MARKET_SOURCE_MARKER in str(source or "").lower()


def is_latest_only_market_data_source(source: object) -> bool:
    return LATEST_ONLY_MARKET_SOURCE_MARKER in str(source or "").lower()


def _is_stale_market_data(row: object) -> bool:
    return is_stale_market_data_source(getattr(row, "source", ""))


def _is_latest_only_market_data(row: object) -> bool:
    return is_latest_only_market_data_source(getattr(row, "source", ""))


def stale_market_data_count(rows: list[object]) -> int:
    return sum(1 for row in rows if _is_stale_market_data(row))


def stale_financial_metric_ticker_count(metrics: list[object]) -> int:
    return len(
        {str(getattr(metric, "ticker", "")) for metric in metrics if _is_stale_market_data(metric)}
    )


def latest_only_market_data_count(rows: list[object]) -> int:
    return sum(1 for row in rows if _is_latest_only_market_data(row))


def latest_only_financial_metric_ticker_count(metrics: list[object]) -> int:
    return len(
        {
            str(getattr(metric, "ticker", ""))
            for metric in metrics
            if _is_latest_only_market_data(metric)
        }
    )


def market_trade_date_summary(
    snapshots: list[object],
    promoted_tickers: list[str],
    database_latest_trade_date: date | None = None,
) -> dict:
    ticker_dates = {
        str(getattr(snapshot, "ticker", "")): date_value(getattr(snapshot, "trade_date", None))
        for snapshot in snapshots
        if getattr(snapshot, "ticker", None) and getattr(snapshot, "trade_date", None)
    }
    dates = [value for value in ticker_dates.values() if value is not None]
    if not dates:
        return {
            "latest_trade_date": None,
            "latest_trade_date_coverage": None,
            "database_latest_trade_date": database_latest_trade_date,
            "older_than_database_latest_count": 0,
            "max_trade_date_lag_days": None,
        }
    latest_trade_date = max(dates)
    latest_count = sum(1 for value in dates if value == latest_trade_date)
    promoted_count = len(promoted_tickers)
    database_latest_trade_date = database_latest_trade_date or latest_trade_date
    database_latest_trade_date = date_value(database_latest_trade_date) or latest_trade_date
    older_than_database_latest_count = sum(
        1
        for ticker in promoted_tickers
        if ticker_dates.get(ticker) is not None
        and ticker_dates[ticker] < database_latest_trade_date
    )
    lag_days = (
        date_lag_days(ticker_dates.get(ticker), database_latest_trade_date)
        for ticker in promoted_tickers
        if ticker_dates.get(ticker) is not None
    )
    max_trade_date_lag_days = max(lag_days, default=0)
    return {
        "latest_trade_date": latest_trade_date,
        "latest_trade_date_coverage": latest_count / promoted_count if promoted_count else None,
        "database_latest_trade_date": database_latest_trade_date,
        "older_than_database_latest_count": older_than_database_latest_count,
        "max_trade_date_lag_days": max_trade_date_lag_days,
    }


def market_provider_summary(
    snapshots: list[object],
    monthly_revenues: list[object],
    financial_metrics: list[object],
    valuations: list[object],
) -> dict:
    return {
        "price_history": _market_source_summary("股價", snapshots),
        "monthly_revenue": _market_source_summary("月營收", monthly_revenues),
        "financial_metrics": _market_source_summary("五年財務", financial_metrics),
        "valuation": _market_source_summary("估值", valuations),
    }


def _market_source_summary(label: str, rows: list[object]) -> dict:
    sources = _unique_market_sources(rows)
    return {
        "label": label,
        "row_count": len(rows),
        "sources": sources,
        "providers": _market_provider_names(sources),
        "stale_count": stale_market_data_count(rows),
        "latest_only_count": latest_only_market_data_count(rows),
    }


def _unique_market_sources(rows: list[object]) -> list[str]:
    sources: list[str] = []
    for row in rows:
        source = str(getattr(row, "source", "") or "").strip()
        if source and source not in sources:
            sources.append(source)
    return sources


def _market_provider_names(sources: list[str]) -> list[str]:
    providers: list[str] = []
    for source in sources:
        provider = _market_provider_name(source)
        if provider and provider not in providers:
            providers.append(provider)
    return providers


def _market_provider_name(source: str) -> str:
    normalized = source.lower()
    if "fugle" in normalized:
        return "Fugle"
    if "finmind" in normalized:
        return "FinMind"
    if "twse openapi" in normalized:
        return "TWSE OpenAPI"
    if "tpex openapi" in normalized:
        return "TPEx OpenAPI"
    if STALE_MARKET_SOURCE_MARKER in normalized:
        return "Redis cached-stale"
    return source.split()[0] if source else ""
