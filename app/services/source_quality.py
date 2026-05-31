from __future__ import annotations

from app.models.schemas import NewsDocument


LOW_QUALITY_INVESTOR_FORUM_MARKERS = (
    "股市爆料同學會",
    "爆料同學會",
    "散戶閒聊",
    "討論區",
    "forum",
    "stock forum",
    "ptt",
    "dcard",
    "mobile01",
)


def is_low_quality_investor_forum_text(text: str) -> bool:
    normalized = (text or "").lower()
    return any(marker.lower() in normalized for marker in LOW_QUALITY_INVESTOR_FORUM_MARKERS)


def is_low_quality_investor_forum_source(
    *,
    title: object = "",
    publisher: object = "",
    url: object = "",
    source_title: object = "",
) -> bool:
    haystack = " ".join(str(part or "") for part in (title, publisher, url, source_title))
    return is_low_quality_investor_forum_text(haystack)


def is_low_quality_investor_forum_document(document: NewsDocument) -> bool:
    return is_low_quality_investor_forum_source(
        title=document.title,
        publisher=document.source.publisher,
        url=document.source.url,
        source_title=document.source.title,
    )


def filter_formal_evidence_documents(documents: list[NewsDocument]) -> list[NewsDocument]:
    return [
        document
        for document in documents
        if not is_low_quality_investor_forum_document(document)
    ]
