from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, ValidationError

from app.models.schemas import MarketSnapshot, NewsDocument


class LLMSupplementItem(BaseModel):
    claim: str = Field(min_length=1)
    source_type: str = Field(pattern=r"^(news|market)$")
    source_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    source_publisher: str = ""
    source_title: str = ""
    source_id: str = ""


class LLMSupplement(BaseModel):
    items: list[LLMSupplementItem] = Field(default_factory=list, max_length=3)


class LLMSupplementValidator:
    insufficient = "目前無足夠數據判斷。"
    failed = "LLM 補充分析未通過來源檢查；目前無足夠數據判斷。"

    @classmethod
    def render_markdown(
        cls,
        raw_text: str,
        documents: list[NewsDocument],
        market_snapshots: list[MarketSnapshot] | None = None,
    ) -> str:
        stripped = raw_text.strip()
        if not stripped:
            return cls.insufficient
        if stripped == cls.insufficient.rstrip("。") or stripped == cls.insufficient:
            return cls.insufficient

        try:
            supplement = cls.parse(stripped)
        except ValueError:
            return cls.failed

        valid_items = [
            item
            for item in supplement.items
            if cls._source_exists(item, documents, market_snapshots or [])
        ]
        if not valid_items:
            return cls.failed

        return "\n".join(
            "- "
            f"{item.claim} "
            f"來源：{cls._source_label(item)}".strip()
            for item in valid_items
        )

    @classmethod
    def parse(cls, raw_text: str) -> LLMSupplement:
        json_text = cls._extract_json(raw_text)
        try:
            return LLMSupplement.model_validate_json(json_text)
        except (ValidationError, ValueError) as exc:
            raise ValueError("invalid llm supplement json") from exc

    @staticmethod
    def _extract_json(raw_text: str) -> str:
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
        if fenced:
            return fenced.group(1)
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("json object not found")
        candidate = raw_text[start : end + 1]
        json.loads(candidate)
        return candidate

    @staticmethod
    def _source_exists(
        item: LLMSupplementItem,
        documents: list[NewsDocument],
        market_snapshots: list[MarketSnapshot],
    ) -> bool:
        if item.source_type == "market":
            return LLMSupplementValidator._market_source_exists(item, market_snapshots)
        return LLMSupplementValidator._news_source_exists(item, documents)

    @staticmethod
    def _news_source_exists(item: LLMSupplementItem, documents: list[NewsDocument]) -> bool:
        for document in documents:
            if not document.source.published_at:
                continue
            if document.source.published_at.isoformat() != item.source_date:
                continue
            if document.source.title != item.source_title:
                continue
            publisher = document.source.publisher or ""
            if publisher != item.source_publisher:
                continue
            return True
        return False

    @staticmethod
    def _market_source_exists(
        item: LLMSupplementItem,
        market_snapshots: list[MarketSnapshot],
    ) -> bool:
        for snapshot in market_snapshots:
            if snapshot.trade_date.isoformat() != item.source_date:
                continue
            if snapshot.ticker != item.source_id:
                continue
            if snapshot.source != item.source_publisher:
                continue
            return True
        return False

    @staticmethod
    def _source_label(item: LLMSupplementItem) -> str:
        if item.source_type == "market":
            return f"{item.source_date} {item.source_publisher} {item.source_id}"
        return f"{item.source_date} {item.source_publisher} {item.source_title}"
