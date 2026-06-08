from __future__ import annotations

import re
from urllib.parse import quote_plus


def google_news_url(query: str) -> str:
    return (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    )


def query_item(
    query: str,
    source_type: str,
    hypothesis: str,
    evidence_type: str,
    source_intent: str,
) -> dict:
    return {
        "query": query,
        "source_type": source_type,
        "hypothesis": hypothesis,
        "evidence_type": evidence_type,
        "source_intent": source_intent,
    }


def query_language(query: str) -> str:
    has_cjk = any("\u4e00" <= char <= "\u9fff" for char in query)
    has_ascii = any(char.isascii() and char.isalpha() for char in query)
    if has_cjk and has_ascii:
        return "mixed"
    if has_cjk:
        return "zh"
    return "en"


def dedupe_query_items(items: list[dict]) -> list[dict]:
    deduped = []
    seen = set()
    for item in items:
        normalized = re.sub(r"\s+", " ", str(item.get("query") or "")).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append({**item, "query": normalized})
    return deduped


def dedupe_query_metadata(
    items: list[dict],
    max_urls: int | None = None,
    existing_urls: list[str] | None = None,
) -> list[dict]:
    seen_urls = set(existing_urls or [])
    seen_queries = set()
    metadata = []
    for item in items:
        normalized = re.sub(r"\s+", " ", str(item.get("query") or "")).strip()
        url = item.get("url") or google_news_url(normalized)
        if not normalized or normalized in seen_queries or url in seen_urls:
            continue
        seen_queries.add(normalized)
        seen_urls.add(url)
        metadata.append(
            {
                **item,
                "url": url,
                "query": normalized,
                "language": query_language(normalized),
            }
        )
        if max_urls and len(metadata) >= max_urls:
            break
    return metadata


def google_news_urls_from_queries(
    queries: list[str],
    max_urls: int | None = None,
    existing_urls: list[str] | None = None,
) -> list[str]:
    return [
        item["url"]
        for item in google_news_metadata_from_queries(
            queries,
            source_type="supplemental",
            hypothesis="補強資料來源。",
            evidence_type="補抓資料源",
            source_intent="industry_news",
            max_urls=max_urls,
            existing_urls=existing_urls,
        )
    ]


def google_news_metadata_from_queries(
    queries: list[str],
    source_type: str,
    hypothesis: str,
    evidence_type: str,
    source_intent: str = "industry_news",
    max_urls: int | None = None,
    existing_urls: list[str] | None = None,
) -> list[dict]:
    seen = set(existing_urls or [])
    metadata = []
    normalized_queries = set()
    for query in queries:
        normalized = query.strip()
        if not normalized or normalized in normalized_queries:
            continue
        normalized_queries.add(normalized)
        url = google_news_url(normalized)
        if url in seen:
            continue
        seen.add(url)
        metadata.append(
            {
                "url": url,
                "query": normalized,
                "source_type": source_type,
                "hypothesis": hypothesis,
                "evidence_type": evidence_type,
                "source_intent": source_intent,
                "language": query_language(normalized),
            }
        )
        if max_urls and len(metadata) >= max_urls:
            break
    return metadata
