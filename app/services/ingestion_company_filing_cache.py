from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from app.data_sources.company_filing_discovery import is_high_quality_company_filing
from app.db.models import NewsArticle
from app.db.session import session_scope
from app.services.company_filing_repository import CompanyFilingRepository


def company_name_from_cached_evidence(
    ticker: str,
    *,
    session_scope_func: Callable[[], Any] | None = None,
    news_article_cls: type | None = None,
) -> str:
    session_scope_func = session_scope if session_scope_func is None else session_scope_func
    news_article_cls = NewsArticle if news_article_cls is None else news_article_cls
    try:
        with session_scope_func() as session:
            rows = session.scalars(
                select(news_article_cls.entity_matches_json)
                .where(news_article_cls.entity_matches_json.like(f"%{ticker}%"))
                .limit(50)
            )
            names = []
            for raw in rows:
                for match in json.loads(raw or "[]"):
                    if str(match.get("ticker") or "") == ticker and match.get("name"):
                        names.append(str(match["name"]))
            if names:
                return max(set(names), key=names.count)
    except Exception:
        return ""
    return ""


def cached_company_filings_by_ticker(
    tickers: list[str],
    limit_per_ticker: int = 8,
    *,
    session_scope_func: Callable[[], Any] | None = None,
    repository_cls: type | None = None,
    quality_checker: Callable[[Any, str, str], bool] | None = None,
) -> dict[str, list]:
    if not tickers:
        return {}
    cached: dict[str, list] = {ticker: [] for ticker in tickers}
    session_scope_func = session_scope if session_scope_func is None else session_scope_func
    repository_cls = CompanyFilingRepository if repository_cls is None else repository_cls
    quality_checker = is_high_quality_company_filing if quality_checker is None else quality_checker
    try:
        with session_scope_func() as session:
            repository = repository_cls(session)
            latest_by_tickers = getattr(repository, "latest_by_tickers", None)
            if latest_by_tickers is None:
                return cached
            documents = latest_by_tickers(tickers, limit_per_ticker=limit_per_ticker)
    except Exception:
        return cached
    for document in documents:
        ticker = str(getattr(document, "ticker", "") or "")
        if ticker not in cached:
            continue
        company_name = str(getattr(document, "company_name", "") or "")
        if quality_checker(document, ticker, company_name):
            cached[ticker].append(document)
    return cached


__all__ = [
    "cached_company_filings_by_ticker",
    "company_name_from_cached_evidence",
]
