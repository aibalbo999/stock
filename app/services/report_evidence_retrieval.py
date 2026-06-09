from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.models.schemas import NewsDocument, ReportRequest
from app.services.company_filing_repository import CompanyFilingRepository
from app.services.entity_mapping import EntityMapper, alias_matches_text
from app.services.news_repository import NewsRepository
from app.services.source_quality import (
    filter_formal_evidence_documents,
    is_formal_evidence_document,
)
from app.services.whitelist import SupplyChainWhitelist


def retrieve_evidence(
    request: ReportRequest,
    *,
    mapper: EntityMapper,
    whitelist: SupplyChainWhitelist,
    vector_store: Any,
    document_matcher: Callable[[NewsDocument], list],
    session_scope_func: Callable,
) -> list[NewsDocument]:
    target_tickers = mapper.filter_allowed_tickers(request.tickers)
    target_aliases = target_aliases_by_ticker(target_tickers, whitelist)
    evidence_docs = filter_formal_evidence_documents(
        dedupe_documents(
            [
                document
                for query in graph_rag_search_queries(request, mapper=mapper, whitelist=whitelist)
                for document in vector_search(query, vector_store, target_tickers, target_aliases)
            ]
        )
    )
    try:
        with session_scope_func() as session:
            db_documents = NewsRepository(session).latest_documents(
                limit=max(600, request.evidence_limit * 6)
            )
            filing_tickers = list(dict.fromkeys(request.tickers)) or mapper.filter_allowed_tickers(
                request.tickers
            )
            company_filing_documents = [
                CompanyFilingRepository.to_news_document(document)
                for document in CompanyFilingRepository(session).latest_by_tickers(
                    filing_tickers,
                    limit_per_ticker=6,
                )
            ]
    except Exception:
        db_documents = []
        company_filing_documents = []
    documents = filter_formal_evidence_documents(
        dedupe_documents([*evidence_docs, *db_documents, *company_filing_documents])
    )
    ranked = rank_evidence_documents(
        request,
        documents,
        mapper=mapper,
        whitelist=whitelist,
        document_matcher=document_matcher,
    )
    if ranked:
        return ranked[: request.evidence_limit]
    if documents:
        return documents[: request.evidence_limit]
    try:
        with session_scope_func() as session:
            fallback_documents = [
                document
                for query in graph_rag_search_queries(
                    request,
                    mapper=mapper,
                    whitelist=whitelist,
                    limit=4,
                )
                for document in NewsRepository(session).search_documents(query, limit=20)
            ]
            return filter_formal_evidence_documents(dedupe_documents(fallback_documents))
    except Exception:
        return []


def vector_search(
    query: str,
    vector_store: Any,
    target_tickers: list[str],
    target_aliases: dict[str, list[str]] | None = None,
) -> list[NewsDocument]:
    try:
        return vector_store.search(
            query,
            target_tickers=target_tickers,
            target_aliases=target_aliases,
        )
    except TypeError:
        try:
            return vector_store.search(query, target_tickers=target_tickers)
        except TypeError:
            return vector_store.search(query)


def target_aliases_by_ticker(
    tickers: list[str],
    whitelist: SupplyChainWhitelist,
) -> dict[str, list[str]]:
    companies = {company.ticker: company for company in whitelist.companies()}
    aliases: dict[str, list[str]] = {}
    for ticker in tickers:
        company = companies.get(ticker)
        aliases[ticker] = [ticker]
        if company:
            aliases[ticker].extend([company.name, *company.aliases])
        aliases[ticker] = list(dict.fromkeys(alias for alias in aliases[ticker] if alias))
    return aliases


def graph_rag_search_queries(
    request: ReportRequest,
    *,
    mapper: EntityMapper,
    whitelist: SupplyChainWhitelist,
    limit: int = 12,
) -> list[str]:
    queries: list[str] = []
    append_search_query(queries, request.topic, limit)
    tickers = mapper.filter_allowed_tickers(request.tickers)
    if not tickers or len(queries) >= limit:
        return queries

    try:
        graph = whitelist.graph()
    except Exception:
        return queries
    if hasattr(graph, "retrieval_plan"):
        plan = graph.retrieval_plan(tickers, topic=request.topic)
        for ticker_queries in (plan.get("queries_by_ticker") or {}).values():
            for graph_query in ticker_queries:
                append_search_query(queries, str(graph_query.get("query") or ""), limit)
                if len(queries) >= limit:
                    return queries
        return queries
    node_by_ticker = {node.ticker: node for node in graph.nodes}
    for ticker in tickers:
        if len(queries) >= limit:
            break
        node = node_by_ticker.get(ticker)
        if node is None:
            continue
        neighbor_terms = graph_neighbor_search_terms(graph, ticker, node_by_ticker)
        company_terms = compact_search_terms(
            [
                request.topic,
                ticker,
                node.name,
                node.segment_name,
                *node.evidence_keywords,
                "供應鏈",
                "上下游",
                *neighbor_terms,
            ],
            max_terms=22,
        )
        append_search_query(queries, " ".join(company_terms), limit)
        if len(queries) >= limit:
            break
        segment_terms = compact_search_terms(
            [
                request.topic,
                node.segment_name,
                *node.evidence_keywords[:4],
                "同業",
                "財報",
                "月營收",
            ],
            max_terms=12,
        )
        append_search_query(queries, " ".join(segment_terms), limit)
    return queries


def graph_reasoning_context(
    request: ReportRequest,
    tickers: list[str],
    *,
    whitelist: SupplyChainWhitelist,
) -> tuple[str, dict | None]:
    if not tickers:
        return "沒有可用股票範圍，GraphRAG 未產生路徑推理。", None
    try:
        graph = whitelist.graph()
        plan = graph.reasoning_plan(
            tickers,
            topic=request.topic,
            max_depth=3,
            max_paths=8,
        )
    except Exception as exc:
        return (
            "GraphRAG 路徑推理目前不可用。",
            {
                "status": "unavailable",
                "reason": str(exc),
            },
        )
    requested_tickers = [
        str(ticker)
        for ticker in (plan.get("tickers") or plan.get("requested_tickers") or tickers)
        if str(ticker or "").strip()
    ]
    paths_by_ticker = (
        plan.get("paths_by_ticker") if isinstance(plan.get("paths_by_ticker"), dict) else {}
    )
    path_count_by_ticker = {
        str(ticker): len(paths) if isinstance(paths, list) else 0
        for ticker, paths in paths_by_ticker.items()
    }
    covered_tickers = [
        ticker for ticker in requested_tickers if int(path_count_by_ticker.get(ticker) or 0) > 0
    ]
    missing_tickers = [
        ticker for ticker in requested_tickers if int(path_count_by_ticker.get(ticker) or 0) <= 0
    ]
    requested_count = len(requested_tickers)
    covered_count = len(covered_tickers)
    reasoning_plan = {
        "status": "ready",
        "strategy": plan.get("strategy"),
        "requested_tickers": requested_tickers,
        "requested_ticker_count": requested_count,
        "covered_ticker_count": covered_count,
        "missing_ticker_count": len(missing_tickers),
        "missing_tickers": missing_tickers[:10],
        "path_count": sum(path_count_by_ticker.values()),
        "path_count_by_ticker": path_count_by_ticker,
        "coverage_ratio": round(covered_count / requested_count, 4) if requested_count else 0.0,
        "max_depth": plan.get("max_depth"),
        "max_paths": plan.get("max_paths"),
        "target_ticker": plan.get("target_ticker"),
        "evidence_policy": plan.get("evidence_policy"),
        "cypher_templates": plan.get("cypher_templates"),
    }
    context = str(plan.get("context") or "").strip()
    return context or "GraphRAG 沒有找到可用 shortest-path context。", reasoning_plan


def graph_neighbor_search_terms(
    graph,
    ticker: str,
    node_by_ticker: dict,
    max_neighbors: int = 4,
) -> list[str]:
    terms: list[str] = []
    if hasattr(graph, "retrieval_hints"):
        for hint in graph.retrieval_hints(ticker, max_neighbors=max_neighbors):
            terms.extend(hint.search_terms())
        return compact_search_terms(terms, max_terms=max_neighbors * 7)

    for edge in graph.neighbor_edges(ticker)[:max_neighbors]:
        neighbor_ticker = edge.target_ticker if edge.source_ticker == ticker else edge.source_ticker
        neighbor = node_by_ticker.get(neighbor_ticker)
        if neighbor is None:
            continue
        relation_label = "同業比較" if edge.relation == "same_segment_peer" else "產業鏈相關"
        terms.extend([relation_label, neighbor.ticker, neighbor.name, neighbor.segment_name])
    return compact_search_terms(terms, max_terms=max_neighbors * 6)


def append_search_query(queries: list[str], query: str, limit: int) -> None:
    if len(queries) >= limit:
        return
    normalized = " ".join((query or "").split())
    if not normalized:
        return
    if normalized.lower() in {existing.lower() for existing in queries}:
        return
    queries.append(normalized)


def compact_search_terms(terms, max_terms: int = 18) -> list[str]:
    compacted: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = " ".join(str(term or "").split())
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        compacted.append(normalized)
        if len(compacted) >= max_terms:
            break
    return compacted


def dedupe_documents(documents: list[NewsDocument]) -> list[NewsDocument]:
    deduped: dict[str, NewsDocument] = {}
    for document in documents:
        key = document.id or document.source.url or document.title
        deduped.setdefault(key, document)
    return list(deduped.values())


def rank_evidence_documents(
    request: ReportRequest,
    documents: list[NewsDocument],
    *,
    mapper: EntityMapper,
    whitelist: SupplyChainWhitelist,
    document_matcher: Callable[[NewsDocument], list],
) -> list[NewsDocument]:
    topic_terms = [term for term in request.topic.replace("/", " ").split() if term]
    requested = mapper.filter_allowed_tickers(request.tickers)
    requested_set = set(requested)
    companies = {company.ticker: company for company in whitelist.companies()}
    entity_terms: list[str] = []
    evidence_terms: list[str] = []
    for ticker in requested:
        company = companies.get(ticker)
        if not company:
            continue
        entity_terms.extend([ticker, company.name, *company.aliases])
        evidence_terms.extend(company.evidence_keywords)
    if not entity_terms:
        entity_terms = [
            term
            for company in whitelist.companies()
            for term in [company.ticker, company.name, *company.aliases]
            if term
        ]
        evidence_terms = [
            keyword
            for company in whitelist.companies()
            for keyword in company.evidence_keywords
            if keyword
        ]

    ranked: list[tuple[int, NewsDocument]] = []
    for document in documents:
        text = f"{document.title}\n{document.text}"
        if not is_formal_evidence_document(document):
            continue
        metadata_tickers = {ticker for ticker in document.entity_tickers if ticker}
        matched_tickers = {match.ticker for match in document_matcher(document)}
        known_tickers = metadata_tickers or matched_tickers
        if requested_set and known_tickers and known_tickers.isdisjoint(requested_set):
            continue
        lowered_text = text.lower()
        metadata_hits = len(metadata_tickers & requested_set) if requested_set else 0
        entity_hits = sum(
            1 for term in entity_terms if term and alias_matches_text(lowered_text, term)
        )
        evidence_hits = sum(1 for term in evidence_terms if term and term in text)
        topic_hits = sum(1 for term in topic_terms if term and term in text)
        risk_hits = sum(
            1
            for keywords in whitelist.risk_keywords.values()
            for keyword in keywords
            if keyword and keyword in text
        )
        if not entity_hits and not evidence_hits and not topic_hits and not risk_hits:
            continue
        score = metadata_hits * 7 + entity_hits * 5 + evidence_hits * 3 + topic_hits * 2 + risk_hits
        ranked.append((score, document))
    ranked.sort(
        key=lambda item: (
            item[0],
            item[1].source.published_at.isoformat() if item[1].source.published_at else "",
        ),
        reverse=True,
    )
    return [document for _score, document in ranked]
