from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.core.time import utc_now_naive
from app.db.models import RiskClassificationCache


class RiskClassificationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, document_id: str, topic_hash: str) -> dict | None:
        row = self.session.get(
            RiskClassificationCache, {"document_id": document_id, "topic_hash": topic_hash}
        )
        if row is None:
            return None
        return {
            "document_id": row.document_id,
            "topic_hash": row.topic_hash,
            "classification": row.classification,
            "topic": row.topic,
            "evidence": row.evidence,
            "confidence": row.confidence,
            "keywords": json.loads(row.keywords_json),
            "model": row.model,
        }

    def upsert(
        self,
        document_id: str,
        topic_hash: str,
        classification: str,
        topic: str,
        evidence: str,
        confidence: float,
        keywords: list[str],
        model: str | None,
    ) -> RiskClassificationCache:
        row = self.session.get(
            RiskClassificationCache, {"document_id": document_id, "topic_hash": topic_hash}
        )
        values = {
            "classification": classification,
            "topic": topic,
            "evidence": evidence,
            "confidence": confidence,
            "keywords_json": json.dumps(keywords, ensure_ascii=False),
            "model": model,
            "updated_at": utc_now_naive(),
        }
        if row is None:
            row = RiskClassificationCache(document_id=document_id, topic_hash=topic_hash, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        self.session.flush()
        return row


__all__ = ["RiskClassificationRepository"]
