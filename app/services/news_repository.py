from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import NewsArticle
from app.models.schemas import NewsDocument, Source


class NewsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_document(self, document: NewsDocument, entity_matches: list[dict]) -> NewsArticle:
        values = {
            "title": document.title,
            "text": document.text,
            "publisher": document.source.publisher,
            "url": document.source.url,
            "published_at": document.source.published_at,
            "fetched_at": document.source.fetched_at,
            "entity_matches_json": json.dumps(entity_matches, ensure_ascii=False),
        }
        return self.session.merge(NewsArticle(id=document.id, **values))

    def upsert_document_merging_matches(
        self, document: NewsDocument, entity_matches: list[dict]
    ) -> NewsArticle:
        existing = self.session.get(NewsArticle, document.id)
        merged_matches = self._merge_entity_matches(
            json.loads(existing.entity_matches_json) if existing else [],
            entity_matches,
        )
        return self.upsert_document(document, merged_matches)

    @staticmethod
    def _merge_entity_matches(existing: list[dict], incoming: list[dict]) -> list[dict]:
        merged: dict[tuple[str, str], dict] = {}
        for item in [*existing, *incoming]:
            ticker = str(item.get("ticker") or "")
            segment_id = str(item.get("segment_id") or "")
            if not ticker:
                continue
            merged[(ticker, segment_id)] = item
        return list(merged.values())

    def latest_documents(self, limit: int = 20) -> list[NewsDocument]:
        statement = select(NewsArticle).order_by(NewsArticle.created_at.desc()).limit(limit)
        return [self._to_document(article) for article in self.session.scalars(statement)]

    def search_documents(self, query: str, limit: int = 20) -> list[NewsDocument]:
        terms = [term for term in query.split() if term]
        statement = select(NewsArticle).order_by(NewsArticle.created_at.desc()).limit(limit * 3)
        documents = [self._to_document(article) for article in self.session.scalars(statement)]
        if not terms:
            return documents[:limit]
        ranked = [
            document
            for document in documents
            if any(term in document.title or term in document.text for term in terms)
        ]
        return ranked[:limit]

    @staticmethod
    def _to_document(article: NewsArticle) -> NewsDocument:
        entity_matches = _parse_entity_matches(article.entity_matches_json)
        return NewsDocument(
            id=article.id,
            title=article.title,
            text=article.text,
            source=Source(
                title=article.title,
                url=article.url,
                publisher=article.publisher,
                published_at=article.published_at,
                fetched_at=article.fetched_at,
            ),
            entity_tickers=_entity_match_values(entity_matches, "ticker"),
            entity_names=_entity_match_values(entity_matches, "name"),
        )


def _parse_entity_matches(value: str | None) -> list[dict]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _entity_match_values(matches: list[dict], key: str) -> list[str]:
    values = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        value = str(match.get(key) or "").strip()
        if value:
            values.append(value)
    return list(dict.fromkeys(values))


__all__ = ["NewsRepository"]
