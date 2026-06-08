from __future__ import annotations

from datetime import date

from app.services.report_quality import is_stale_market_data_source
from app.services.source_quality import is_low_quality_investor_forum_document


def source_selection_limit(limit: int) -> int:
    return max(20, min(40, limit + 16))


def select_diverse_sources(sources: list, limit: int) -> list:
    if len(sources) <= limit:
        return sources
    selected: list = []
    used_names: set[str] = set()
    seen_categories: set[str] = set()
    for source in sources:
        if source.category in seen_categories:
            continue
        selected.append(source)
        used_names.add(source.name)
        seen_categories.add(source.category)
        if len(selected) >= limit:
            return selected
    for source in sources:
        if source.name in used_names:
            continue
        selected.append(source)
        if len(selected) >= limit:
            break
    return selected


def source_category_counts(source_results: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for result in source_results:
        category = str(result.get("category") or "news")
        counts[category] = counts.get(category, 0) + int(result.get("stored_count") or 0)
    return counts


def matches_target_terms(document, target_terms: list[str] | None) -> bool:
    terms = [term.casefold() for term in (target_terms or []) if term and len(term.strip()) >= 2]
    if not terms:
        return True
    haystack = " ".join(
        str(part or "")
        for part in [
            getattr(document, "title", ""),
            getattr(document, "text", ""),
            getattr(getattr(document, "source", None), "url", ""),
            getattr(getattr(document, "source", None), "publisher", ""),
        ]
    ).casefold()
    return any(term in haystack for term in terms)


def stale_market_source_count(rows: list[object]) -> int:
    return sum(1 for row in rows if is_stale_market_data_source(getattr(row, "source", "")))


def market_sources(rows: list[object]) -> list[str]:
    sources: list[str] = []
    for row in rows:
        source = str(getattr(row, "source", "") or "").strip()
        if source and source not in sources:
            sources.append(source)
    return sources


def dedupe_documents(documents):
    deduped = {}
    for document in documents:
        deduped.setdefault(document.id, document)
    return list(deduped.values())


def filter_documents(
    documents,
    start_date: date | None,
    end_date: date | None,
    quality_filter: bool,
):
    filtered = []
    for document in documents:
        published_at = document.source.published_at
        if published_at and start_date and published_at < start_date:
            continue
        if published_at and end_date and published_at > end_date:
            continue
        if quality_filter and is_low_quality_investor_forum_document(document):
            continue
        if quality_filter and is_low_quality_market_source(document):
            continue
        filtered.append(document)
    return filtered


def is_low_quality_market_source(document) -> bool:
    text = f"{document.title}\n{document.text}"
    political_noise = [
        "選舉",
        "立委",
        "政黨",
        "民進黨",
        "國民黨",
        "藍白",
        "嗆",
        "打臉",
        "公投",
        "市長",
    ]
    market_terms = [
        "營收",
        "獲利",
        "EPS",
        "訂單",
        "出貨",
        "產能",
        "法說",
        "目標價",
        "股",
        "台廠",
        "CoWoS",
        "HBM",
        "伺服器",
        "散熱",
        "重電",
    ]
    has_political_noise = any(term in text for term in political_noise)
    has_market_context = any(term in text for term in market_terms)
    return has_political_noise and not has_market_context


__all__ = [
    "dedupe_documents",
    "filter_documents",
    "is_low_quality_market_source",
    "market_sources",
    "matches_target_terms",
    "select_diverse_sources",
    "source_category_counts",
    "source_selection_limit",
    "stale_market_source_count",
]
