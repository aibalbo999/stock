from __future__ import annotations

import re
from typing import Protocol
from urllib.parse import quote_plus

from app.models.schemas import ReportRequest


class FollowUpQueryAction(Protocol):
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


def follow_up_target_terms(action: FollowUpQueryAction) -> list[str]:
    terms = [*list(action.tickers), company_name_from_follow_up_reason(action.reason)]
    terms.extend(follow_up_query_terms(action.reason)[:3])
    return dedupe_terms(terms, limit=8)


def follow_up_news_queries(action: FollowUpQueryAction, request: ReportRequest) -> list[str]:
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


def company_name_from_follow_up_reason(reason: str) -> str:
    match = re.search(r"股票：\d+\s+([^；]+)", reason)
    return match.group(1).strip() if match else ""


def follow_up_fallback_topic(action: FollowUpQueryAction, request: ReportRequest) -> str:
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
