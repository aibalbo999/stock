from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date
from typing import Any

from app.models.schemas import NewsDocument, RiskType
from app.services.source_quality import (
    filter_formal_evidence_documents,
    source_credibility_weight_for_document,
)


def representative_sources(documents: list[NewsDocument], limit: int = 3) -> str:
    documents = filter_formal_evidence_documents(documents)
    if not documents:
        return "目前無足夠公司層級來源。"
    labels = []
    seen: set[tuple[str, str, str]] = set()
    for document in _sort_source_documents(documents):
        key = _source_identity(document)
        if key in seen:
            continue
        seen.add(key)
        labels.append(_source_label(document))
        if len(labels) >= limit:
            break
    return "；".join(labels)


def downside_source_references(
    documents: list[NewsDocument],
    findings: Iterable[Any],
    *,
    limit: int = 3,
    scoring_text_for_document: Callable[[NewsDocument], str] | None = None,
) -> str:
    risk_types = {
        RiskType.structural_bottleneck,
        RiskType.short_term_volatility,
        RiskType.insufficient_data,
    }
    labels = []
    seen: set[tuple[str, str, str]] = set()

    def append_source(source: Any) -> None:
        key = (
            source.title,
            source.publisher or "",
            source.published_at.isoformat() if source.published_at else "",
        )
        if key in seen:
            return
        seen.add(key)
        date_label = source.published_at.isoformat() if source.published_at else "日期不明"
        publisher = source.publisher or "來源不明"
        labels.append(f"{date_label} {publisher}《{source.title}》")

    for finding in findings:
        if finding.risk_type in risk_types:
            append_source(finding.source)
        if len(labels) >= limit:
            return "；".join(labels)

    text_for_document = scoring_text_for_document or _default_scoring_text_for_document
    negative_keywords = ["下滑", "重摔", "毛利", "禁令", "制裁", "缺電", "產能不足", "吃緊", "延遲", "鬆動"]
    for document in _sort_source_documents(documents):
        text = text_for_document(document)
        if any(keyword in text for keyword in negative_keywords):
            append_source(document.source)
        if len(labels) >= limit:
            break
    return "；".join(labels)


def ordered_source_documents(documents: list[NewsDocument]) -> list[NewsDocument]:
    documents = filter_formal_evidence_documents(documents)
    deduped = []
    seen: set[tuple[str, str, str]] = set()
    for document in _sort_source_documents(documents):
        key = _source_identity(document)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(document)
    return deduped


def source_reference_line(document: NewsDocument) -> str:
    source_date = document.source.published_at.isoformat() if document.source.published_at else "日期不明"
    publisher = document.source.publisher or "來源不明"
    url = f"（{document.source.url}）" if document.source.url else ""
    return f"- {source_date} {publisher}《{document.title}》{url}"


def _sort_source_documents(documents: list[NewsDocument]) -> list[NewsDocument]:
    return sorted(
        documents,
        key=lambda document: (
            source_credibility_weight_for_document(document),
            document.source.published_at or date.min,
            document.source.publisher or "",
            document.title,
        ),
        reverse=True,
    )


def _source_identity(document: NewsDocument) -> tuple[str, str, str]:
    return (
        document.title,
        document.source.publisher or "",
        document.source.published_at.isoformat() if document.source.published_at else "",
    )


def _source_label(document: NewsDocument) -> str:
    date_label = document.source.published_at.isoformat() if document.source.published_at else "日期不明"
    publisher = document.source.publisher or "來源不明"
    return f"{date_label} {publisher}《{document.title}》"


def _default_scoring_text_for_document(document: NewsDocument) -> str:
    if document.id.startswith("filing-"):
        return document.title
    return f"{document.title}\n{document.text[:1200]}"
