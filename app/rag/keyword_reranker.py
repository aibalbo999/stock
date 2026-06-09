from __future__ import annotations

import re
from collections import Counter
from datetime import date

from app.models.schemas import NewsDocument
from app.services.entity_mapping import CONFUSING_ENTITY_PREFIXES, alias_matches_text
from app.services.source_quality import is_low_quality_investor_forum_document

TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_+.-]*|[\u4e00-\u9fff]+")
OFFICIAL_SOURCE_HINTS = (
    "公開資訊觀測站",
    "mops",
    "twse",
    "tpex",
    "investor",
    "ir.",
    "/ir",
    "annual report",
    "法說",
    "法人說明",
)


def keyword_rerank(
    query: str,
    documents: list[NewsDocument],
    n_results: int,
    *,
    text_limit: int,
) -> list[NewsDocument]:
    query_terms = tokenize(query)
    exact_terms = exact_query_terms(query)
    if not query_terms and not exact_terms:
        return documents[:n_results]
    query_counter = Counter(query_terms)
    ranked = []
    for index, document in enumerate(documents):
        text = document_text(document, text_limit)
        title = document.title or ""
        score = keyword_score(
            query_counter,
            exact_terms,
            title=title,
            text=text,
        )
        score += source_quality_adjustment(document)
        recency = document.source.published_at if score > 0 and document.source.published_at else date.min
        ranked.append((score, recency, -index, document))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [document for _score, _recency, _index, document in ranked[:n_results]]


def keyword_score(
    query_counter: Counter[str],
    exact_terms: list[str],
    *,
    title: str,
    text: str,
) -> float:
    title_lower = title.lower()
    text_lower = text.lower()
    document_terms = Counter(tokenize(f"{title}\n{text}"))
    score = 0.0
    for term, query_count in query_counter.items():
        frequency = document_terms.get(term, 0)
        if frequency <= 0:
            continue
        score += min(3, frequency) * query_count

    for term in exact_terms:
        term_lower = term.lower()
        if alias_matches_text(title_lower, term_lower):
            score += 4.0 if term_lower.isdigit() else 2.5
        if alias_matches_text(text_lower, term_lower):
            score += 2.0 if term_lower.isdigit() else 1.0
    return score


def source_quality_adjustment(document: NewsDocument) -> float:
    if is_low_quality_investor_forum_document(document):
        return -100.0
    haystack = " ".join(
        str(part or "")
        for part in (
            document.title,
            document.source.title,
            document.source.publisher,
            document.source.url,
        )
    ).lower()
    return 1.5 if any(hint.lower() in haystack for hint in OFFICIAL_SOURCE_HINTS) else 0.0


def document_text(document: NewsDocument, text_limit: int) -> str:
    text = f"{document.title}\n{document.text}"
    if text_limit <= 0:
        return text
    return text[:text_limit]


def exact_query_terms(query: str) -> list[str]:
    terms = []
    seen = set()
    for raw_term in str(query or "").split():
        term = raw_term.strip()
        if len(term) < 2:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append(term)
    return terms


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in TOKEN_RE.findall(str(text or "").lower()):
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
