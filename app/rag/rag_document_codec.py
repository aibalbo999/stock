from __future__ import annotations

from datetime import date

from app.models.schemas import NewsDocument

EMBEDDING_BODY_MARKER = "\n\n內文："


def document_from_metadata(document_id: str, text: str, metadata: dict) -> NewsDocument:
    published_at = metadata.get("published_at") or None
    return NewsDocument(
        id=document_id,
        title=metadata.get("title", ""),
        text=stored_document_body(text),
        source={
            "title": metadata.get("title", ""),
            "url": metadata.get("url") or None,
            "publisher": metadata.get("publisher") or None,
            "published_at": date.fromisoformat(published_at) if published_at else None,
        },
        entity_tickers=metadata_list(metadata.get("entity_tickers")),
        entity_names=metadata_list(metadata.get("entity_names")),
    )


def metadata_for_document(document: NewsDocument) -> dict:
    entity_tickers = list(document.entity_tickers)
    entity_names = list(document.entity_names)
    if not entity_tickers:
        try:
            from app.services.entity_mapping import EntityMapper

            matches = EntityMapper().match_document(document)
        except Exception:
            matches = []
        entity_tickers = [match.ticker for match in matches]
        entity_names = [match.name for match in matches]
    return {
        "title": document.title,
        "publisher": document.source.publisher or "",
        "url": document.source.url or "",
        "published_at": document.source.published_at.isoformat()
        if document.source.published_at
        else "",
        "entity_tickers": ",".join(dict.fromkeys(entity_tickers)),
        "entity_names": ",".join(dict.fromkeys(entity_names)),
    }


def metadata_list(value: object) -> list[str]:
    if value is None:
        return []
    raw_values = value if isinstance(value, list) else str(value).split(",")
    return list(dict.fromkeys(str(item).strip() for item in raw_values if str(item).strip()))


def embedding_document_text(document: NewsDocument, metadata: dict | None = None) -> str:
    metadata = metadata or metadata_for_document(document)
    entity_tickers = metadata_list(metadata.get("entity_tickers"))
    entity_names = metadata_list(metadata.get("entity_names"))
    entity_labels = [
        " ".join(part for part in (ticker, name) if part).strip()
        for ticker, name in zip(entity_tickers, entity_names)
    ]
    if len(entity_tickers) > len(entity_names):
        entity_labels.extend(entity_tickers[len(entity_names) :])
    elif len(entity_names) > len(entity_tickers):
        entity_labels.extend(entity_names[len(entity_tickers) :])
    parts = [
        f"標題：{document.title}" if document.title else "",
        f"來源：{document.source.publisher}" if document.source.publisher else "",
        (
            f"日期：{document.source.published_at.isoformat()}"
            if document.source.published_at
            else ""
        ),
        f"公司對應：{'、'.join(entity_labels)}" if entity_labels else "",
    ]
    header = "\n".join(part for part in parts if part)
    if not header:
        return document.text
    return f"{header}{EMBEDDING_BODY_MARKER}{document.text}"


def stored_document_body(text: str) -> str:
    if EMBEDDING_BODY_MARKER not in text:
        return text
    return text.split(EMBEDDING_BODY_MARKER, 1)[1]
