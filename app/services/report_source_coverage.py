from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from typing import Any

from app.models.schemas import NewsDocument
from app.services import report_formatting
from app.services.report_source_references import representative_sources
from app.services.source_quality import filter_formal_evidence_documents


def render_source_coverage(
    *,
    evidence_limit: int,
    tickers: list[str],
    documents: list[NewsDocument],
    companies: Iterable[Any],
    related_documents_resolver: Callable[[str, list[NewsDocument]], list[NewsDocument]],
) -> str:
    documents = filter_formal_evidence_documents(documents)
    if not documents:
        return "目前無足夠數據判斷。"

    publisher_counts = Counter(document.source.publisher or "來源不明" for document in documents)
    international_count = sum(1 for document in documents if is_international_source(document))
    taiwan_count = len(documents) - international_count
    lines = [
        "本段說明本次可追溯證據池的來源覆蓋；來源多不代表一定可買，仍需看公司層級歸因與財務資料是否同時成立。",
        "",
        "| 項目 | 結果 |",
        "|---|---|",
        f"| 摘要使用證據上限 | {evidence_limit} 筆 |",
        f"| 可追溯證據池總量 | {len(documents)} 筆 |",
        f"| 台灣來源 | {taiwan_count} 筆 |",
        f"| 國際來源 | {international_count} 筆 |",
        report_formatting.table_row(
            [
                "主要來源",
                "、".join(f"{publisher}({count})" for publisher, count in publisher_counts.most_common(6)),
            ]
        ),
        "",
        "### 個股來源覆蓋",
        "| 股票 | 公司相關文本 | 國際文本 | 最近來源日期 | 代表來源 |",
        "|---|---:|---:|---|---|",
    ]
    companies_by_ticker = {company.ticker: company for company in companies}
    for ticker in tickers:
        related_documents = related_documents_resolver(ticker, documents)
        related_international = sum(1 for document in related_documents if is_international_source(document))
        company = companies_by_ticker.get(ticker)
        label = f"{ticker} {company.name if company else ticker}"
        lines.append(
            report_formatting.table_row(
                [
                    label,
                    len(related_documents),
                    related_international,
                    latest_source_date_label(related_documents),
                    representative_sources(related_documents, limit=4),
                ]
            )
        )
    if international_count == 0:
        lines.extend(["", "提醒：本次沒有國際來源進入證據池；若要擴大國際覆蓋，請開啟深度分析與國際資料源。"])
    return "\n".join(lines)


def latest_source_date_label(documents: list[NewsDocument]) -> str:
    latest_dates = [
        document.source.published_at
        for document in documents
        if document.source.published_at is not None
    ]
    return max(latest_dates).isoformat() if latest_dates else "日期不明"


def is_international_source(document: NewsDocument) -> bool:
    publisher = (document.source.publisher or "").lower()
    title = document.title.lower()
    url = (document.source.url or "").lower()
    international_markers = [
        "nvidia",
        "amd",
        "samsung",
        "arm newsroom",
        "cloudflare",
        "venturebeat",
        "the decoder",
        "siliconangle",
        "microsoft azure",
        "trendforce",
        "semiconductor today",
        "electronics weekly",
        "embedded",
        "eejournal",
        "electronic design",
        "robotics tomorrow",
        "manufacturing tomorrow",
        "power & beyond",
        "reuters",
        "bloomberg",
        "cnbc",
        "the information",
        "semianalysis",
        "center for a new american",
        "bessemer",
        "astute",
        "designnews",
        "wsj",
        "financial times",
        "ft.com",
    ]
    haystack = f"{publisher} {title} {url}"
    if any(marker in haystack for marker in international_markers):
        return True
    return "hl=en" in url or "ceid=us:en" in url
