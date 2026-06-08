from __future__ import annotations

import asyncio
import re
from datetime import timedelta
from typing import Protocol
from urllib.parse import quote_plus

from app.db.session import session_scope
from app.models.schemas import ReportRequest
from app.services.followup_completion import _matched_target_item_count
from app.services.ingestion import IngestionPipeline
from app.services.persistence import CompanyFilingRepository, NewsRepository


FOLLOW_UP_NEWS_QUERY_TIMEOUT_SECONDS = 8
FOLLOW_UP_NEWS_FALLBACK_TIMEOUT_SECONDS = 20
FOLLOW_UP_NEWS_WEB_SEARCH_TIMEOUT_SECONDS = 30


class FollowUpEvidenceAction(Protocol):
    reason: str
    tickers: tuple[str, ...]


def company_filing_document_types_from_reason(reason: str) -> list[str] | None:
    document_types = []
    if "annual_report" in reason or "年報" in reason:
        document_types.append("annual_report")
    if "investor_presentation" in reason or "法說" in reason or "法人說明" in reason:
        document_types.append("investor_presentation")
    if "prospectus" in reason or "公開說明書" in reason:
        document_types.append("prospectus")
    if "material_information" in reason or "重大訊息" in reason:
        document_types.append("material_information")
    return list(dict.fromkeys(document_types)) or None


def needs_company_filing_sources(reason: str) -> bool:
    return any(keyword in reason for keyword in ["年報", "法說", "法人說明", "IR", "公開文件"])


async def ingest_follow_up_news(
    pipeline: IngestionPipeline,
    action: FollowUpEvidenceAction,
    request: ReportRequest,
    news_limit: int,
    today,
) -> dict:
    start_date = today - timedelta(days=max(request.lookback_days, 30))
    queries = follow_up_news_queries(action, request)
    if not queries:
        return await pipeline.ingest_feeds(
            enabled_sources_only=True,
            topic=request.topic,
            limit=news_limit,
            start_date=start_date,
            end_date=today,
        )

    per_query_limit = max(3, min(10, news_limit // max(1, len(queries))))
    results = []
    items = []
    errors = []
    target_terms = follow_up_target_terms(action)
    target_tickers = list(action.tickers)
    cached_items = cached_follow_up_news_items(pipeline, target_tickers, target_terms, news_limit)
    if _has_follow_up_target_match(cached_items, target_tickers, target_terms):
        return {
            "count": len(cached_items),
            "items": cached_items,
            "errors": [],
            "suppressed_errors": [],
            "queries": [],
            "web_search": None,
            "fallback": None,
            "target_terms": target_terms,
            "source": "cached follow-up news evidence",
        }
    semaphore = asyncio.Semaphore(4)

    async def fetch_query(query: str) -> tuple[dict, dict]:
        url = google_news_rss_url(query)
        try:
            async with semaphore:
                result = await asyncio.wait_for(
                    pipeline.ingest_feeds(
                        url=url,
                        publisher="Google News follow-up",
                        limit=per_query_limit,
                        enabled_sources_only=False,
                        start_date=start_date,
                        end_date=today,
                    ),
                    timeout=FOLLOW_UP_NEWS_QUERY_TIMEOUT_SECONDS,
                )
        except Exception as exc:
            result = {
                "count": 0,
                "items": [],
                "errors": [{"source": url, "error": str(exc) or exc.__class__.__name__}],
            }
        return result, {
            "query": query,
            "url": url,
            "count": result.get("count", 0),
            "errors": result.get("errors", []),
        }

    for result, query_result in await asyncio.gather(*(fetch_query(query) for query in queries)):
        results.append(query_result)
        items.extend(result.get("items", []) or [])
        errors.extend(result.get("errors", []) or [])
    deduped_items = filter_follow_up_target_items(
        dedupe_follow_up_items(items),
        target_tickers,
        target_terms,
    )
    fallback = None
    coverage_fallback_count = 0
    suppressed_errors = []
    if coverage_fallback_count <= 0 and not _has_follow_up_target_match(deduped_items, target_tickers, target_terms):
        google_errors = list(errors)
        fallback_topic = follow_up_fallback_topic(action, request)
        try:
            fallback = await asyncio.wait_for(
                pipeline.ingest_feeds(
                    enabled_sources_only=True,
                    topic=fallback_topic,
                    limit=news_limit,
                    start_date=start_date,
                    end_date=today,
                ),
                timeout=FOLLOW_UP_NEWS_FALLBACK_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            fallback = {
                "count": 0,
                "items": [],
                "errors": [{"source": fallback_topic, "error": str(exc) or exc.__class__.__name__}],
            }
        items.extend(fallback.get("items", []) or [])
        fallback_errors = fallback.get("errors", []) or []
        errors = fallback_errors if fallback.get("items") else [*google_errors, *fallback_errors]
        suppressed_errors = google_errors if fallback.get("items") else []
        deduped_items = filter_follow_up_target_items(
            dedupe_follow_up_items(items),
            target_tickers,
            target_terms,
        )
        if not target_tickers and not deduped_items and fallback.get("items"):
            fallback_items = dedupe_follow_up_items(fallback.get("items") or [])
            coverage_fallback_count = len(fallback_items)
            deduped_items = fallback_items[:news_limit]
    web_search = None
    if coverage_fallback_count <= 0 and not _has_follow_up_target_match(deduped_items, target_tickers, target_terms):
        prior_errors = list(errors)
        try:
            web_search = await asyncio.wait_for(
                pipeline.ingest_web_search(
                    queries=queries,
                    topic=follow_up_fallback_topic(action, request),
                    limit_per_query=max(2, min(5, news_limit // max(1, len(queries)))),
                    start_date=start_date,
                    end_date=today,
                    target_terms=target_terms,
                ),
                timeout=FOLLOW_UP_NEWS_WEB_SEARCH_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            web_search = {
                "count": 0,
                "items": [],
                "errors": [{"source": "targeted web search", "error": str(exc) or exc.__class__.__name__}],
                "queries": [],
                "target_terms": target_terms,
            }
        items.extend(web_search.get("items", []) or [])
        web_errors = web_search.get("errors", []) or []
        if web_search.get("items"):
            suppressed_errors.extend(prior_errors)
            errors = web_errors
        else:
            errors.extend(web_errors)
        deduped_items = filter_follow_up_target_items(
            dedupe_follow_up_items(items),
            target_tickers,
            target_terms,
        )
    source_parts = ["Google News targeted follow-up"]
    if fallback:
        source_parts.append("enabled-source fallback")
    if web_search:
        source_parts.append("targeted web search")
    return {
        "count": len(deduped_items),
        "items": deduped_items,
        "errors": errors,
        "suppressed_errors": suppressed_errors,
        "queries": results,
        "web_search": web_search,
        "fallback": fallback,
        "coverage_fallback_count": coverage_fallback_count,
        "target_terms": target_terms,
        "source": " + ".join(source_parts),
    }


def cached_follow_up_news_items(
    pipeline: IngestionPipeline,
    target_tickers: list[str],
    target_terms: list[str],
    limit: int,
) -> list[dict]:
    mapper = getattr(pipeline, "mapper", None)
    if mapper is None:
        return []
    queries = dedupe_terms([*target_tickers, *target_terms], limit=8)
    if not queries:
        return []
    try:
        with session_scope() as session:
            repository = NewsRepository(session)
            filing_repository = CompanyFilingRepository(session)
            documents = []
            for query in queries:
                documents.extend(repository.search_documents(query, limit=max(5, limit)))
                filing_documents = filing_repository.search_documents(
                    query,
                    tickers=target_tickers or None,
                    limit=max(5, limit),
                )
                documents.extend(
                    CompanyFilingRepository.to_news_document(document)
                    for document in filing_documents
                )
    except Exception:
        return []
    deduped_documents = IngestionPipeline._dedupe_documents(documents)
    items = []
    for document in deduped_documents[: max(5, limit * 2)]:
        matches = mapper.match_document(document)
        items.append(
            {
                "id": document.id,
                "title": document.title,
                "publisher": document.source.publisher,
                "published_at": document.source.published_at.isoformat()
                if document.source.published_at
                else None,
                "url": document.source.url,
                "excerpt": document.text[:500],
                "entity_matches": [match.model_dump(mode="json") for match in matches],
            }
        )
    return filter_follow_up_target_items(items, target_tickers, target_terms)[:limit]


def dedupe_follow_up_items(items: list) -> list[dict]:
    return list(
        {
            item.get("id") or item.get("url") or item.get("title"): item
            for item in items
            if isinstance(item, dict)
        }.values()
    )


def filter_follow_up_target_items(
    items: list[dict],
    target_tickers: list[str],
    target_terms: list[str],
) -> list[dict]:
    if not target_tickers and not target_terms:
        return items
    return [
        item
        for item in items
        if _matched_target_item_count([item], target_tickers, target_terms) > 0
    ]


def follow_up_target_terms(action: FollowUpEvidenceAction) -> list[str]:
    terms = [*list(action.tickers), company_name_from_follow_up_reason(action.reason)]
    terms.extend(follow_up_query_terms(action.reason)[:3])
    return dedupe_terms(terms, limit=8)


def follow_up_news_queries(action: FollowUpEvidenceAction, request: ReportRequest) -> list[str]:
    tickers = list(action.tickers)
    company_name = company_name_from_follow_up_reason(action.reason)
    context_terms = follow_up_query_terms(action.reason)
    context = " ".join(context_terms[:4])
    queries = []
    for ticker in tickers:
        if ticker:
            ticker_context = " ".join(part for part in [ticker, company_name, request.topic, context] if part)
            queries.append(ticker_context.strip())
            queries.append(f"{ticker} 台股 {request.topic} 供應鏈 證據".strip())
            queries.append(" ".join(part for part in [ticker, company_name, context, "公司公告 法說會"] if part))
            queries.append(" ".join(part for part in [ticker, company_name, context, "site:mops.twse.com.tw"] if part))
            if needs_company_filing_sources(action.reason):
                queries.append(" ".join(part for part in [ticker, company_name, "年報 法說會 IR"] if part))
            if needs_confidence_sources(action.reason):
                queries.append(f"{ticker} {request.topic} 法說會 近期 來源 日期".strip())
                queries.append(f"{ticker} {request.topic} monthly revenue investor conference".strip())
    for term in context_terms[:4]:
        queries.append(f"{request.topic} {term}".strip())
    if context_terms and needs_confidence_sources(action.reason):
        queries.append(f"{request.topic} 近期 公司來源 發布日期 多來源".strip())
    return dedupe_queries(queries, limit=8)


def _has_follow_up_target_match(items: list[dict], target_tickers: list[str], target_terms: list[str]) -> bool:
    if not items:
        return False
    if not target_tickers and not target_terms:
        return True
    return _matched_target_item_count(items, target_tickers, target_terms) > 0


def company_name_from_follow_up_reason(reason: str) -> str:
    match = re.search(r"股票：\d+\s+([^；]+)", reason)
    return match.group(1).strip() if match else ""


def follow_up_fallback_topic(action: FollowUpEvidenceAction, request: ReportRequest) -> str:
    parts = [request.topic, *list(action.tickers), company_name_from_follow_up_reason(action.reason)]
    parts.extend(follow_up_query_terms(action.reason)[:3])
    return " ".join(part for part in parts if part).strip() or request.topic


def follow_up_query_terms(reason: str) -> list[str]:
    terms = []
    segment = re.search(r"產業位置：([^；]+)", reason)
    if segment:
        terms.append(segment.group(1).strip())
    source_gap = re.search(r"(?:缺少來源覆蓋子題|缺少的資料意圖|資料意圖)：([^；]+)", reason)
    if source_gap:
        for part in re.split(r"[、,，]", source_gap.group(1)):
            if part.strip():
                terms.append(part.strip())
            for subpart in re.split(r"與|和", part):
                if subpart.strip() and subpart.strip() != part.strip():
                    terms.append(subpart.strip())
    for keyword in [
        "協作機器人",
        "人形機器人",
        "減速器",
        "伺服馬達",
        "滾珠螺桿",
        "線性滑軌",
        "法說會",
        "月營收",
        "毛利率",
        "估值",
        "資本支出",
    ]:
        if keyword in reason:
            terms.append(keyword)
    if not terms:
        terms.extend(compact_query_text(reason).split()[:4])
    return dedupe_terms(terms, limit=6)


def dedupe_terms(terms: list[str], limit: int) -> list[str]:
    deduped = []
    seen = set()
    for term in terms:
        normalized = re.sub(r"\s+", " ", term).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
        if len(deduped) >= limit:
            break
    return deduped


def needs_confidence_sources(reason: str) -> bool:
    return any(
        keyword in reason
        for keyword in [
            "證據信心",
            "入選支持度",
            "信心：",
            "有日期",
            "近期",
            "不同發布者",
            "日期來源",
        ]
    )


def compact_query_text(text: str) -> str:
    cleaned = re.sub(r"[|:：；,，。/]+", " ", text)
    terms = [
        term
        for term in cleaned.split()
        if term
        and term not in {"候選公司未升格", "需補齊公司層級證據", "股票", "產業位置", "下一步", "候選入選門檻"}
    ]
    return " ".join(terms[:12])


def dedupe_queries(queries: list[str], limit: int) -> list[str]:
    deduped = []
    seen = set()
    for query in queries:
        normalized = re.sub(r"\s+", " ", query).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
        if len(deduped) >= limit:
            break
    return deduped


def google_news_rss_url(query: str) -> str:
    return (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    )
