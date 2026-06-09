from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date
from time import monotonic
from typing import Any

from app.models.schemas import NewsDocument
from app.services.entity_mapping import CONFUSING_ENTITY_PREFIXES, alias_matches_text
from app.services.source_quality import (
    SOURCE_CREDIBILITY_WEIGHTS,
    source_credibility_tier_for_document,
    source_credibility_weight_for_document,
)

TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_+.-]*|[\u4e00-\u9fff]+")


class HybridRetrievalRanker:
    def __init__(self, settings: Any, reranker: Any) -> None:
        self.settings = settings
        self.reranker = reranker

    def rank(
        self,
        query: str,
        vector_hits: list[tuple[NewsDocument, float]],
        keyword_corpus: list[NewsDocument],
        n_results: int,
        target_tickers: list[str] | None = None,
        target_aliases: dict[str, list[str]] | None = None,
        *,
        started_at: float | None = None,
    ) -> tuple[list[NewsDocument], dict]:
        started_at = started_at if started_at is not None else monotonic()
        vector_weight = max(0.0, float(self.settings.rag_vector_weight))
        keyword_weight = max(0.0, float(self.settings.rag_keyword_weight))
        original_vector_hit_count = len(vector_hits)
        original_keyword_corpus_count = len(keyword_corpus)
        vector_hits = [
            (document, score)
            for document, score in vector_hits
            if document_matches_target_tickers(document, target_tickers, target_aliases)
        ]
        keyword_corpus = filter_by_target_tickers(
            keyword_corpus,
            target_tickers,
            target_aliases,
        )
        vector_scores = {document_key(document): score for document, score in vector_hits}
        keyword_scores = bm25_scores(query, keyword_corpus)
        max_keyword = max(keyword_scores.values(), default=0.0)
        ranked: dict[str, dict] = {}

        for document, score in vector_hits:
            key = document_key(document)
            ranked[key] = {
                "document": document,
                "vector_score": score,
                "keyword_raw_score": 0.0,
                "keyword_score": 0.0,
                "score": vector_weight * score,
            }

        for document in keyword_corpus:
            key = document_key(document)
            raw_keyword_score = keyword_scores.get(key, 0.0)
            if raw_keyword_score <= 0 and key not in vector_scores:
                continue
            keyword_score = raw_keyword_score / max_keyword if max_keyword > 0 else 0.0
            current = ranked.setdefault(
                key,
                {
                    "document": document,
                    "vector_score": 0.0,
                    "keyword_raw_score": 0.0,
                    "keyword_score": 0.0,
                    "score": 0.0,
                },
            )
            current["keyword_raw_score"] = raw_keyword_score
            current["keyword_score"] = keyword_score
            current["score"] += keyword_weight * keyword_score

        for item in ranked.values():
            item["pre_source_score"] = item["score"]
            item["source_quality_multiplier"] = source_quality_multiplier_for_document(
                item["document"]
            )
            item["source_quality_tier"] = source_quality_tier_for_document(item["document"])
            item["score"] *= item["source_quality_multiplier"]

        ranked_items = sorted(
            ranked.values(),
            key=lambda item: (
                item["score"],
                item["document"].source.published_at or date.min,
                item["document"].title,
            ),
            reverse=True,
        )
        results = self.reranker.rerank(
            query,
            [item["document"] for item in ranked_items],
            n_results,
        )
        trace = {
            "query": query,
            "strategy": "hybrid-vector-bm25-rerank",
            "duration_ms": elapsed_ms(started_at),
            "target_tickers": list(target_tickers or []),
            "vector_weight": vector_weight,
            "keyword_weight": keyword_weight,
            "vector_hit_count": original_vector_hit_count,
            "keyword_corpus_count": original_keyword_corpus_count,
            "target_filtered_vector_hit_count": len(vector_hits),
            "target_filtered_keyword_corpus_count": len(keyword_corpus),
            "candidate_count": len(ranked_items),
            "returned_count": len(results),
            "candidates": [
                trace_row(
                    item["document"],
                    rank=index + 1,
                    vector_score=float(item.get("vector_score") or 0.0),
                    keyword_raw_score=float(item.get("keyword_raw_score") or 0.0),
                    keyword_score=float(item.get("keyword_score") or 0.0),
                    pre_source_score=float(item.get("pre_source_score") or 0.0),
                    source_quality_multiplier=float(item.get("source_quality_multiplier") or 0.0),
                    source_quality_tier=str(item.get("source_quality_tier") or "unknown"),
                    final_score=float(item.get("score") or 0.0),
                )
                for index, item in enumerate(ranked_items[:20])
            ],
            "result_ids": [document_key(document) for document in results],
            "reranker_status": getattr(self.reranker, "last_status", {}),
        }
        return results, trace


def elapsed_ms(started_at: float) -> float:
    return round(max(0.0, monotonic() - started_at) * 1000, 3)


def trace_row(
    document: NewsDocument,
    *,
    rank: int,
    vector_score: float = 0.0,
    keyword_raw_score: float = 0.0,
    keyword_score: float = 0.0,
    pre_source_score: float | None = None,
    final_score: float | None = None,
    source_quality_multiplier: float | None = None,
    source_quality_tier: str | None = None,
) -> dict:
    multiplier = (
        float(source_quality_multiplier)
        if source_quality_multiplier is not None
        else source_quality_multiplier_for_document(document)
    )
    tier = source_quality_tier or source_quality_tier_for_document(document)
    pre_source = (
        float(pre_source_score)
        if pre_source_score is not None
        else float(vector_score) + float(keyword_score)
    )
    return {
        "rank": rank,
        "id": document_key(document),
        "title": document.title,
        "publisher": document.source.publisher,
        "published_at": (
            document.source.published_at.isoformat()
            if document.source.published_at
            else None
        ),
        "entity_tickers": list(document.entity_tickers),
        "entity_names": list(document.entity_names),
        "vector_score": float(vector_score),
        "keyword_raw_score": float(keyword_raw_score),
        "keyword_score": float(keyword_score),
        "pre_source_score": pre_source,
        "source_quality_multiplier": multiplier,
        "source_quality_tier": tier,
        "final_score": float(final_score) if final_score is not None else pre_source * multiplier,
    }


def source_quality_multiplier_for_document(document: NewsDocument) -> float:
    try:
        return max(0.0, float(source_credibility_weight_for_document(document)))
    except Exception:
        return SOURCE_CREDIBILITY_WEIGHTS["unknown"]


def source_quality_tier_for_document(document: NewsDocument) -> str:
    try:
        return source_credibility_tier_for_document(document)
    except Exception:
        return "unknown"


def filter_by_target_tickers(
    documents: list[NewsDocument],
    target_tickers: list[str] | None,
    target_aliases: dict[str, list[str]] | None = None,
) -> list[NewsDocument]:
    return [
        document
        for document in documents
        if document_matches_target_tickers(document, target_tickers, target_aliases)
    ]


def document_matches_target_tickers(
    document: NewsDocument,
    target_tickers: list[str] | None,
    target_aliases: dict[str, list[str]] | None = None,
) -> bool:
    target = {str(ticker) for ticker in target_tickers or [] if str(ticker)}
    if not target:
        return True
    entity_tickers = {str(ticker) for ticker in document.entity_tickers if str(ticker)}
    if entity_tickers:
        return bool(entity_tickers & target)
    aliases_by_ticker = target_aliases_by_ticker(sorted(target), target_aliases)
    haystack = f"{document.title}\n{document.text}".lower()
    return any(
        alias_matches_text(haystack, alias)
        for ticker in target
        for alias in aliases_by_ticker.get(ticker, [ticker])
        if alias
    )


def target_aliases_by_ticker(
    target_tickers: list[str],
    target_aliases: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    aliases_by_ticker = {ticker: [ticker] for ticker in target_tickers if ticker}
    for ticker, aliases in (target_aliases or {}).items():
        if ticker not in aliases_by_ticker:
            continue
        aliases_by_ticker[ticker].extend(str(alias) for alias in aliases if str(alias))
    try:
        from app.services.whitelist import SupplyChainWhitelist

        companies = {company.ticker: company for company in SupplyChainWhitelist().companies()}
    except Exception:
        companies = {}
    for ticker in target_tickers:
        company = companies.get(ticker)
        if company is None:
            continue
        aliases_by_ticker.setdefault(ticker, [ticker]).extend([company.name, *company.aliases])
    return {
        ticker: list(dict.fromkeys(alias for alias in aliases if alias))
        for ticker, aliases in aliases_by_ticker.items()
    }


def bm25_scores(query: str, documents: list[NewsDocument]) -> dict[str, float]:
    query_terms = tokenize(query)
    if not query_terms or not documents:
        return {}
    doc_terms = [tokenize(keyword_document_text(document)) for document in documents]
    doc_lengths = [len(terms) or 1 for terms in doc_terms]
    avg_doc_length = sum(doc_lengths) / len(doc_lengths)
    document_frequency: Counter[str] = Counter()
    for terms in doc_terms:
        document_frequency.update(set(terms))

    scores: dict[str, float] = {}
    query_counter = Counter(query_terms)
    for document, terms, doc_length in zip(documents, doc_terms, doc_lengths):
        term_counts = Counter(terms)
        score = 0.0
        for term, query_count in query_counter.items():
            frequency = term_counts.get(term, 0)
            if frequency <= 0:
                continue
            idf = math.log(
                1
                + (len(documents) - document_frequency[term] + 0.5)
                / (document_frequency[term] + 0.5)
            )
            denominator = frequency + 1.2 * (1 - 0.75 + 0.75 * doc_length / avg_doc_length)
            score += query_count * idf * (frequency * 2.2 / denominator)
        score += exact_phrase_boost(query, document)
        if score > 0:
            scores[document_key(document)] = score
    return scores


def keyword_document_text(document: NewsDocument) -> str:
    identity = " ".join([*document.entity_tickers, *document.entity_names])
    return "\n".join(
        part
        for part in (
            document.title,
            document.source.publisher or "",
            identity,
            document.text,
        )
        if part
    )


def exact_phrase_boost(query: str, document: NewsDocument) -> float:
    haystack = keyword_document_text(document).lower()
    boost = 0.0
    for raw_term in query.split():
        term = raw_term.strip().lower()
        if len(term) >= 2 and alias_matches_text(haystack, term):
            boost += 0.6 if term.isdigit() else 0.3
    return boost


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in TOKEN_RE.findall(text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", match):
            if len(match) <= 4:
                tokens.append(match)
            for size in (2, 3, 4):
                if len(match) >= size:
                    for index in range(len(match) - size + 1):
                        token = match[index : index + size]
                        if is_confusing_entity_prefix_token(match, token, index):
                            continue
                        tokens.append(token)
        elif len(match) >= 2:
            tokens.append(match)
    return tokens


def is_confusing_entity_prefix_token(text: str, token: str, index: int) -> bool:
    confusing_prefixes = CONFUSING_ENTITY_PREFIXES.get(token, ())
    return any(text.startswith(prefix.lower(), index) for prefix in confusing_prefixes)


def document_key(document: NewsDocument) -> str:
    return document.id or document.source.url or f"{document.title}:{document.source.published_at or ''}"
