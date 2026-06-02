from __future__ import annotations

import json
import re
from collections.abc import Callable
from difflib import SequenceMatcher
from string import punctuation
from typing import Any

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
    items: list[LLMSupplementItem] = Field(default_factory=list, max_length=8)


class LLMSupplementValidator:
    insufficient = "目前無足夠數據判斷。"
    failed = "LLM 補充分析未通過來源檢查；目前無足夠數據判斷。"

    @classmethod
    def render_markdown(
        cls,
        raw_text: str,
        documents: list[NewsDocument],
        market_snapshots: list[MarketSnapshot] | None = None,
        news_ticker_resolver: Callable[[NewsDocument], list[str] | set[str] | tuple[str, ...]] | None = None,
        claim_ticker_resolver: Callable[[str], list[str] | set[str] | tuple[str, ...]] | None = None,
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
            if cls._source_exists(
                item,
                documents,
                market_snapshots or [],
                news_ticker_resolver,
                claim_ticker_resolver,
            )
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
    def tool_schema() -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "submit_report_supplement",
                "description": "Submit source-grounded supplemental investment analysis items.",
                "parameters": LLMSupplement.model_json_schema(),
            },
        }

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
        news_ticker_resolver: Callable[[NewsDocument], list[str] | set[str] | tuple[str, ...]] | None = None,
        claim_ticker_resolver: Callable[[str], list[str] | set[str] | tuple[str, ...]] | None = None,
    ) -> bool:
        if item.source_type == "market":
            return LLMSupplementValidator._market_source_exists(item, market_snapshots)
        return LLMSupplementValidator._news_source_exists(
            item,
            documents,
            news_ticker_resolver,
            claim_ticker_resolver,
        )

    @staticmethod
    def _news_source_exists(
        item: LLMSupplementItem,
        documents: list[NewsDocument],
        news_ticker_resolver: Callable[[NewsDocument], list[str] | set[str] | tuple[str, ...]] | None = None,
        claim_ticker_resolver: Callable[[str], list[str] | set[str] | tuple[str, ...]] | None = None,
    ) -> bool:
        source_ids = LLMSupplementValidator._ticker_ids(item.source_id)
        claim_tickers = LLMSupplementValidator._safe_resolve_claim_tickers(
            item.claim,
            claim_ticker_resolver,
        )
        for document in documents:
            if not document.source.published_at:
                continue
            if document.source.published_at.isoformat() != item.source_date:
                continue
            if not LLMSupplementValidator._fuzzy_source_text_matches(
                item.source_title,
                document.source.title,
                threshold=0.72,
                allow_empty=False,
            ):
                continue
            publisher = document.source.publisher or ""
            if not LLMSupplementValidator._fuzzy_source_text_matches(
                item.source_publisher,
                publisher,
                threshold=0.75,
                allow_empty=not bool(publisher),
            ):
                continue
            document_tickers = LLMSupplementValidator._safe_resolve_document_tickers(
                document,
                news_ticker_resolver,
            )
            if not LLMSupplementValidator._news_attribution_matches(
                source_ids,
                claim_tickers,
                document_tickers,
                resolver_provided=news_ticker_resolver is not None,
            ):
                continue
            return True
        return False

    @staticmethod
    def _news_attribution_matches(
        source_ids: set[str],
        claim_tickers: set[str],
        document_tickers: set[str],
        *,
        resolver_provided: bool,
    ) -> bool:
        if resolver_provided and (source_ids or claim_tickers) and not document_tickers:
            return False
        if source_ids and document_tickers and not source_ids.intersection(document_tickers):
            return False
        if source_ids and claim_tickers and not source_ids.intersection(claim_tickers):
            return False
        if claim_tickers and document_tickers and not claim_tickers.intersection(document_tickers):
            return False
        return True

    @staticmethod
    def _ticker_ids(value: str) -> set[str]:
        return set(re.findall(r"\b\d{4,6}\b", value or ""))

    @staticmethod
    def _fuzzy_source_text_matches(
        generated: str,
        expected: str,
        *,
        threshold: float,
        allow_empty: bool,
    ) -> bool:
        generated_norm = LLMSupplementValidator._normalize_source_text(generated)
        expected_norm = LLMSupplementValidator._normalize_source_text(expected)
        if not generated_norm or not expected_norm:
            return allow_empty and generated_norm == expected_norm
        if generated_norm in expected_norm or expected_norm in generated_norm:
            return True
        return SequenceMatcher(None, generated_norm, expected_norm).ratio() >= threshold

    @staticmethod
    def _normalize_source_text(value: str) -> str:
        text = str(value or "").lower()
        remove_chars = set(punctuation + "，。；：！？、（）《》「」『』【】〔〕〈〉—－…")
        return "".join(char for char in text if char not in remove_chars and not char.isspace())

    @staticmethod
    def _safe_resolve_document_tickers(
        document: NewsDocument,
        resolver: Callable[[NewsDocument], list[str] | set[str] | tuple[str, ...]] | None,
    ) -> set[str]:
        if resolver is None:
            return set()
        try:
            return {str(ticker) for ticker in resolver(document) if str(ticker)}
        except Exception:
            return set()

    @staticmethod
    def _safe_resolve_claim_tickers(
        claim: str,
        resolver: Callable[[str], list[str] | set[str] | tuple[str, ...]] | None,
    ) -> set[str]:
        if resolver is None:
            return set()
        try:
            return {str(ticker) for ticker in resolver(claim) if str(ticker)}
        except Exception:
            return set()

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
