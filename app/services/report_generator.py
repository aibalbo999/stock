from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import timedelta

from app.data_sources.company_filing_discovery import REQUIRED_CORE_DOCUMENT_TYPES, filing_quality_score
from app.core.time import format_taipei, now_taipei
from app.db.session import session_scope
from app.models.schemas import (
    FinancialMetric,
    EntityMatch,
    InvestorProfile,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ReportRequest,
    ReportResponse,
    RiskType,
    ValuationMetric,
)
from app.rag.vector_store import VectorStore
from app.services.candidate_audit import render_candidate_audit_markdown
from app.services.entity_mapping import EntityMapper, alias_matches_text, company_filing_owner_ticker
from app.services.followup_actions import FollowUpActionPlanner, render_follow_up_actions_markdown
from app.services.llm_client import LLMClient, LLMResult, summarize_llm_attempts
from app.services.llm_analysis import LLMSupplementValidator
from app.services.leading_signals import LeadingSignal, LeadingSignalAnalyzer
from app.services.persistence import (
    CompanyFilingRepository,
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    NewsRepository,
    ValuationMetricRepository,
)
from app.services.report_financial_narrative import (
    balance_sheet_total_series,
    debt_equity_phrase,
    debt_text,
    fcf_trend_text,
    financial_statement_summary,
    financial_strength_text,
    margin_text,
    metric_series,
    roe_text,
    series_trend_text,
)
from app.services.report_financial_assessment import (
    decline_risk_points,
    financial_valuation_assessment,
    has_negative_profitability,
    peer_valuation_summary,
    series_growth_pct,
    series_period_text,
    valuation_position_label,
)
from app.services.report_integrity import ReportIntegrityError, assert_report_integrity
from app.services.report_models import ReportContext, ReportSection
from app.services.report_prompt_builder import (
    build_report_prompt,
    format_llm_evidence,
    format_market_data,
)
from app.services import (
    report_allocation,
    report_company_narrative,
    report_decision_rules,
    report_formatting,
    report_potential,
    report_scope_sections,
)
from app.services.report_renderer import ReportMarkdownRenderer
from app.services.report_source_references import (
    downside_source_references,
    ordered_source_documents,
    representative_sources,
    source_reference_line,
)
from app.services.risk_analyzer import RiskAnalyzer
from app.services.source_quality import (
    filter_formal_evidence_documents,
    is_formal_evidence_document,
    remove_low_quality_investor_forum_lines,
)
from app.services.whitelist import SupplyChainWhitelist


SOURCE_APPENDIX_LIMIT = 80
REPORT_READING_SORT_NOTE = (
    "排序：先依判斷結果分組（可研究、觀察、待補、避開），"
    "同組再依最新可取得收盤價由高到低；缺股價者排在同組後段。"
)
AI_INFRA_RISK_TERMS = {
    "CoWoS",
    "cowos",
    "HBM",
    "hbm",
    "先進封裝",
    "先進製程",
    "液冷",
    "水冷",
    "缺電",
}
AI_INFRA_CONTEXT_TERMS = {
    "AI 伺服器",
    "AI伺服器",
    "資料中心",
    "data center",
    "datacenter",
    "server",
    "伺服器",
    "晶圓",
    "半導體",
    "封裝",
    "CoWoS",
    "cowos",
    "HBM",
    "hbm",
    "PCB",
    "pcb",
    "載板",
    "ABF",
    "abf",
    "CCL",
    "ccl",
    "矽晶圓",
    "AI 晶片",
    "散熱",
    "液冷",
    "水冷",
    "CSP",
    "GPU",
}


class ReportExecutionError(ValueError):
    pass


def report_execution_summary(generator: object) -> dict:
    evidence_documents = getattr(generator, "last_evidence_documents", None) or []
    excluded_low_quality = getattr(generator, "last_excluded_low_quality_documents", None) or []
    llm_result = getattr(generator, "last_llm_result", None)
    vector_store = getattr(generator, "vector_store", None)
    retrieval_trace = getattr(vector_store, "last_retrieval_trace", None) if vector_store is not None else None
    graph_reasoning_plan = getattr(generator, "last_graph_reasoning_plan", None)
    llm_status = None
    if llm_result is not None:
        llm_status = {
            "fallback": bool(getattr(llm_result, "fallback", False)),
            "model": getattr(llm_result, "model", None),
            "provider": getattr(llm_result, "provider", None),
            "key_index": getattr(llm_result, "key_index", None),
            "observability": getattr(llm_result, "observability", {}) or {},
            "attempt_summary": summarize_llm_attempts(getattr(llm_result, "attempts", ())),
            "attempts": list(getattr(llm_result, "attempts", ())[-10:]),
        }
    return {
        "filtered_tickers": list(getattr(generator, "last_filtered_tickers", None) or []),
        "dropped_tickers": list(getattr(generator, "last_dropped_tickers", None) or []),
        "evidence_count": len(evidence_documents),
        "excluded_low_quality_source_count": len(excluded_low_quality),
        "retrieval_trace": retrieval_trace,
        "graph_reasoning": graph_reasoning_plan,
        "llm": llm_status,
    }


class ReportGenerator:
    def __init__(
        self,
        vector_store: VectorStore | None = None,
        whitelist: SupplyChainWhitelist | None = None,
    ) -> None:
        self.whitelist = whitelist or SupplyChainWhitelist()
        self.vector_store = vector_store or VectorStore()
        self.mapper = EntityMapper(self.whitelist)
        self.risk_analyzer = RiskAnalyzer(self.whitelist, self.mapper, use_llm=False)
        self.llm = LLMClient()
        self.last_evidence_documents: list[NewsDocument] = []
        self.last_excluded_low_quality_documents: list[NewsDocument] = []
        self.last_llm_result: LLMResult | None = None
        self.last_graph_reasoning_plan: dict | None = None
        self.last_filtered_tickers: list[str] = []
        self.last_dropped_tickers: list[str] = []
        self._document_match_cache: dict[tuple[str, str, str, int], list] = {}

    def generate(self, request: ReportRequest, documents: list[NewsDocument] | None = None) -> ReportResponse:
        raw_evidence_docs = documents or self._retrieve_evidence(request)
        evidence_docs = filter_formal_evidence_documents(raw_evidence_docs)
        self.last_excluded_low_quality_documents = [
            document
            for document in raw_evidence_docs
            if not is_formal_evidence_document(document)
        ]
        self.last_evidence_documents = list(evidence_docs)
        findings = self.risk_analyzer.analyze_documents(evidence_docs)
        tickers = self.mapper.filter_allowed_tickers(request.tickers)
        self.last_filtered_tickers = tickers
        self.last_dropped_tickers = [ticker for ticker in request.tickers if ticker not in set(tickers)]
        if self.last_dropped_tickers:
            dropped_tickers = "、".join(self.last_dropped_tickers)
            raise ReportExecutionError(
                f"報告產生中止：以下指定股票未進入目前白名單：{dropped_tickers}。"
                "若這是 AI 主題探索或補強重跑，必須套用候選公司動態白名單，"
                "避免產出缺漏個股分析卻顯示成功的報告。"
            )
        market_snapshots = self._latest_market_snapshots(tickers)
        monthly_revenues = self._latest_monthly_revenues(tickers)
        financial_metrics = self._financial_metrics(tickers)
        valuation_metrics = self._latest_valuations(tickers)
        leading_signals = self._leading_signals(tickers, valuation_metrics)

        graph_reasoning_context = self._graph_reasoning_context(request, tickers)
        prompt = build_report_prompt(
            whitelist_context=self.whitelist.as_prompt_context(),
            graph_context=graph_reasoning_context,
            evidence_documents=evidence_docs,
            market_snapshots=market_snapshots,
            monthly_revenues=monthly_revenues,
            ticker_label_resolver=self._document_company_labels,
        )
        llm_result = self._generate_llm_supplement(prompt)
        self.last_llm_result = llm_result
        markdown = self._render_markdown(
            request,
            evidence_docs,
            findings,
            tickers,
            llm_result,
            market_snapshots,
            monthly_revenues,
            financial_metrics,
            valuation_metrics,
            leading_signals,
        )
        markdown = remove_low_quality_investor_forum_lines(markdown)
        self._assert_report_integrity(markdown, self.whitelist)
        return ReportResponse(
            title=f"{request.topic} 自動分析報告",
            generated_at=now_taipei(),
            markdown=markdown,
            findings=findings,
        )

    @staticmethod
    def _assert_report_integrity(markdown: str, whitelist: SupplyChainWhitelist | None = None) -> None:
        try:
            assert_report_integrity(markdown, whitelist)
        except ReportIntegrityError as exc:
            raise ReportExecutionError(str(exc)) from exc

    def _generate_llm_supplement(self, prompt: str) -> LLMResult:
        structured_generate = getattr(self.llm, "generate_structured_with_metadata", None)
        if callable(structured_generate):
            return structured_generate(
                prompt,
                tool_schema=LLMSupplementValidator.tool_schema(),
                tool_name="submit_report_supplement",
            )
        return self.llm.generate_with_metadata(prompt)

    def _retrieve_evidence(self, request: ReportRequest) -> list[NewsDocument]:
        target_tickers = self.mapper.filter_allowed_tickers(request.tickers)
        target_aliases = self._target_aliases_by_ticker(target_tickers)
        evidence_docs = filter_formal_evidence_documents(
            self._dedupe_documents(
                [
                    document
                    for query in self._graph_rag_search_queries(request)
                    for document in self._vector_search(query, target_tickers, target_aliases)
                ]
            )
        )
        try:
            with session_scope() as session:
                db_documents = NewsRepository(session).latest_documents(
                    limit=max(600, request.evidence_limit * 6)
                )
                filing_tickers = list(dict.fromkeys(request.tickers)) or self.mapper.filter_allowed_tickers(request.tickers)
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
            self._dedupe_documents([*evidence_docs, *db_documents, *company_filing_documents])
        )
        ranked = self._rank_evidence_documents(request, documents)
        if ranked:
            return ranked[: request.evidence_limit]
        if documents:
            return documents[: request.evidence_limit]
        try:
            with session_scope() as session:
                fallback_documents = [
                    document
                    for query in self._graph_rag_search_queries(request, limit=4)
                    for document in NewsRepository(session).search_documents(query, limit=20)
                ]
                return filter_formal_evidence_documents(
                    self._dedupe_documents(fallback_documents)
                )
        except Exception:
            return []

    def _vector_search(
        self,
        query: str,
        target_tickers: list[str],
        target_aliases: dict[str, list[str]] | None = None,
    ) -> list[NewsDocument]:
        try:
            return self.vector_store.search(
                query,
                target_tickers=target_tickers,
                target_aliases=target_aliases,
            )
        except TypeError:
            try:
                return self.vector_store.search(query, target_tickers=target_tickers)
            except TypeError:
                return self.vector_store.search(query)

    def _target_aliases_by_ticker(self, tickers: list[str]) -> dict[str, list[str]]:
        companies = {company.ticker: company for company in self.whitelist.companies()}
        aliases: dict[str, list[str]] = {}
        for ticker in tickers:
            company = companies.get(ticker)
            aliases[ticker] = [ticker]
            if company:
                aliases[ticker].extend([company.name, *company.aliases])
            aliases[ticker] = list(dict.fromkeys(alias for alias in aliases[ticker] if alias))
        return aliases

    def _graph_rag_search_queries(self, request: ReportRequest, limit: int = 12) -> list[str]:
        queries: list[str] = []
        self._append_search_query(queries, request.topic, limit)
        tickers = self.mapper.filter_allowed_tickers(request.tickers)
        if not tickers or len(queries) >= limit:
            return queries

        try:
            graph = self.whitelist.graph()
        except Exception:
            return queries
        if hasattr(graph, "retrieval_plan"):
            plan = graph.retrieval_plan(tickers, topic=request.topic)
            for ticker_queries in (plan.get("queries_by_ticker") or {}).values():
                for graph_query in ticker_queries:
                    self._append_search_query(queries, str(graph_query.get("query") or ""), limit)
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
            neighbor_terms = self._graph_neighbor_search_terms(graph, ticker, node_by_ticker)
            company_terms = self._compact_search_terms(
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
            self._append_search_query(queries, " ".join(company_terms), limit)
            if len(queries) >= limit:
                break
            segment_terms = self._compact_search_terms(
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
            self._append_search_query(queries, " ".join(segment_terms), limit)
        return queries

    def _graph_reasoning_context(self, request: ReportRequest, tickers: list[str]) -> str:
        self.last_graph_reasoning_plan = None
        if not tickers:
            return "沒有可用股票範圍，GraphRAG 未產生路徑推理。"
        try:
            graph = self.whitelist.graph()
            plan = graph.reasoning_plan(
                tickers,
                topic=request.topic,
                max_depth=3,
                max_paths=8,
            )
        except Exception as exc:
            self.last_graph_reasoning_plan = {
                "status": "unavailable",
                "reason": str(exc),
            }
            return "GraphRAG 路徑推理目前不可用。"
        self.last_graph_reasoning_plan = {
            "status": "ready",
            "strategy": plan.get("strategy"),
            "requested_tickers": plan.get("requested_tickers") or tickers,
            "max_depth": plan.get("max_depth"),
            "max_paths": plan.get("max_paths"),
            "evidence_policy": plan.get("evidence_policy"),
            "cypher_templates": plan.get("cypher_templates"),
        }
        context = str(plan.get("context") or "").strip()
        return context or "GraphRAG 沒有找到可用 shortest-path context。"

    @staticmethod
    def _graph_neighbor_search_terms(graph, ticker: str, node_by_ticker: dict, max_neighbors: int = 4) -> list[str]:
        terms: list[str] = []
        if hasattr(graph, "retrieval_hints"):
            for hint in graph.retrieval_hints(ticker, max_neighbors=max_neighbors):
                terms.extend(hint.search_terms())
            return ReportGenerator._compact_search_terms(terms, max_terms=max_neighbors * 7)

        for edge in graph.neighbor_edges(ticker)[:max_neighbors]:
            neighbor_ticker = edge.target_ticker if edge.source_ticker == ticker else edge.source_ticker
            neighbor = node_by_ticker.get(neighbor_ticker)
            if neighbor is None:
                continue
            relation_label = "同業比較" if edge.relation == "same_segment_peer" else "產業鏈相關"
            terms.extend([relation_label, neighbor.ticker, neighbor.name, neighbor.segment_name])
        return ReportGenerator._compact_search_terms(terms, max_terms=max_neighbors * 6)

    @staticmethod
    def _append_search_query(queries: list[str], query: str, limit: int) -> None:
        if len(queries) >= limit:
            return
        normalized = " ".join((query or "").split())
        if not normalized:
            return
        if normalized.lower() in {existing.lower() for existing in queries}:
            return
        queries.append(normalized)

    @staticmethod
    def _compact_search_terms(terms, max_terms: int = 18) -> list[str]:
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

    @staticmethod
    def _dedupe_documents(documents: list[NewsDocument]) -> list[NewsDocument]:
        deduped: dict[str, NewsDocument] = {}
        for document in documents:
            key = document.id or document.source.url or document.title
            deduped.setdefault(key, document)
        return list(deduped.values())

    def _rank_evidence_documents(
        self,
        request: ReportRequest,
        documents: list[NewsDocument],
    ) -> list[NewsDocument]:
        topic_terms = [term for term in request.topic.replace("/", " ").split() if term]
        requested = self.mapper.filter_allowed_tickers(request.tickers)
        requested_set = set(requested)
        companies = {company.ticker: company for company in self.whitelist.companies()}
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
                for company in self.whitelist.companies()
                for term in [company.ticker, company.name, *company.aliases]
                if term
            ]
            evidence_terms = [
                keyword
                for company in self.whitelist.companies()
                for keyword in company.evidence_keywords
                if keyword
            ]

        ranked: list[tuple[int, NewsDocument]] = []
        for document in documents:
            text = f"{document.title}\n{document.text}"
            if not is_formal_evidence_document(document):
                continue
            metadata_tickers = {ticker for ticker in document.entity_tickers if ticker}
            matched_tickers = {match.ticker for match in self._document_matches(document)}
            known_tickers = metadata_tickers or matched_tickers
            if requested_set and known_tickers and known_tickers.isdisjoint(requested_set):
                continue
            lowered_text = text.lower()
            metadata_hits = len(metadata_tickers & requested_set) if requested_set else 0
            entity_hits = sum(1 for term in entity_terms if term and alias_matches_text(lowered_text, term))
            evidence_hits = sum(1 for term in evidence_terms if term and term in text)
            topic_hits = sum(1 for term in topic_terms if term and term in text)
            risk_hits = sum(
                1
                for keywords in self.whitelist.risk_keywords.values()
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

    def _latest_market_snapshots(self, tickers: list[str]) -> list[MarketSnapshot]:
        if not tickers:
            return []
        try:
            with session_scope() as session:
                return MarketRepository(session).latest_by_tickers(tickers)
        except Exception:
            return []

    def _latest_monthly_revenues(self, tickers: list[str]) -> list[MonthlyRevenue]:
        if not tickers:
            return []
        try:
            with session_scope() as session:
                return MonthlyRevenueRepository(session).latest_by_tickers(tickers)
        except Exception:
            return []

    def _financial_metrics(self, tickers: list[str]) -> list[FinancialMetric]:
        if not tickers:
            return []
        try:
            with session_scope() as session:
                return FinancialMetricRepository(session).by_tickers(tickers)
        except Exception:
            return []

    def _latest_valuations(self, tickers: list[str]) -> list[ValuationMetric]:
        if not tickers:
            return []
        try:
            with session_scope() as session:
                return ValuationMetricRepository(session).latest_by_tickers(tickers)
        except Exception:
            return []

    def _leading_signals(
        self,
        tickers: list[str],
        valuation_metrics: list[ValuationMetric],
    ) -> dict[str, LeadingSignal]:
        if not tickers:
            return {}
        try:
            with session_scope() as session:
                price_histories = MarketRepository(session).history_by_tickers(tickers, limit=90)
                revenue_histories = MonthlyRevenueRepository(session).history_by_tickers(tickers, limit=18)
        except Exception:
            price_histories = {}
            revenue_histories = {}
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics}
        peer_summary = self._peer_valuation_summary(valuation_metrics)
        return LeadingSignalAnalyzer().build(tickers, price_histories, revenue_histories, valuations, peer_summary)

    def _render_markdown(
        self,
        request: ReportRequest,
        documents: list[NewsDocument],
        findings,
        tickers: list[str],
        llm_result: LLMResult,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue],
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        leading_signals = leading_signals or {}
        if financial_metrics:
            metrics_by_ticker = self._group_financial_metrics(financial_metrics)
            leading_signals = {
                ticker: self._sanitize_leading_signal_for_profitability(
                    signal,
                    self._has_negative_profitability(metrics_by_ticker.get(ticker, [])),
                )
                for ticker, signal in leading_signals.items()
            }
        ordered_tickers = self._ordered_tickers_for_reading(
            request,
            tickers,
            documents,
            findings,
            market_snapshots,
            monthly_revenues,
            financial_metrics,
            valuation_metrics,
            leading_signals,
        )
        sections = [
            ReportSection(
                title="一頁摘要",
                body=self._render_executive_snapshot(
                    request,
                    ordered_tickers,
                    documents,
                    findings,
                    market_snapshots,
                    monthly_revenues,
                    financial_metrics,
                    valuation_metrics,
                    leading_signals,
                ),
            ),
            ReportSection(
                title="可信度檢查",
                body=self._render_credibility_check(
                    request,
                    ordered_tickers,
                    documents,
                    findings,
                    market_snapshots,
                    monthly_revenues,
                    financial_metrics,
                    valuation_metrics,
                    leading_signals,
                ),
            ),
            ReportSection(
                title="時間口徑說明",
                body=self._render_time_scope_note(
                    request,
                    market_snapshots,
                    monthly_revenues,
                    valuation_metrics,
                ),
            ),
            ReportSection(title="判斷準則說明", body=self._render_decision_criteria_note(request)),
            ReportSection(
                title="下一步行動",
                body=self._render_action_checklist(
                    request,
                    ordered_tickers,
                    documents,
                    findings,
                    market_snapshots,
                    monthly_revenues,
                    financial_metrics,
                    valuation_metrics,
                    leading_signals,
                ),
            ),
            ReportSection(
                title="監控清單",
                body=self._render_monitoring_checklist(
                    request,
                    ordered_tickers,
                    documents,
                    findings,
                    market_snapshots,
                    monthly_revenues,
                    financial_metrics,
                    valuation_metrics,
                    leading_signals,
                ),
            ),
            ReportSection(
                title="自動補強任務",
                body=self._render_follow_up_actions(
                    request,
                    ordered_tickers,
                    documents,
                    findings,
                    market_snapshots,
                    monthly_revenues,
                    financial_metrics,
                    valuation_metrics,
                    leading_signals,
                ),
            ),
            ReportSection(title="先看結論", body=self._summary(findings)),
            ReportSection(title="候選公司審計", body=self._render_candidate_audit(ordered_tickers)),
            ReportSection(
                title="資料完整度",
                body=self._render_data_quality(
                    ordered_tickers,
                    documents,
                    findings,
                    market_snapshots,
                    monthly_revenues,
                    financial_metrics,
                    valuation_metrics,
                    leading_signals,
                    request=request,
                ),
            ),
            ReportSection(title="來源覆蓋", body=self._render_source_coverage(request, ordered_tickers, documents)),
            ReportSection(title="近況訊號檢查", body=self._render_leading_signal_check(ordered_tickers, leading_signals)),
            ReportSection(
                title="早期潛力雷達",
                body=self._render_early_potential_radar(
                    request,
                    ordered_tickers,
                    documents,
                    findings,
                    market_snapshots,
                    monthly_revenues,
                    leading_signals,
                    financial_metrics,
                    valuation_metrics,
                ),
            ),
            ReportSection(
                title="資金控管建議",
                body=self._render_beginner_portfolio_plan(
                    request,
                    ordered_tickers,
                    documents,
                    findings,
                    market_snapshots,
                    monthly_revenues,
                    financial_metrics,
                    valuation_metrics,
                    leading_signals,
                ),
            ),
            ReportSection(
                title="投資建議",
                body=self._render_investment_recommendations(
                    request,
                    ordered_tickers,
                    documents,
                    findings,
                    market_snapshots,
                    monthly_revenues,
                    financial_metrics,
                    valuation_metrics,
                    leading_signals,
                ),
            ),
            ReportSection(
                title="個股比較矩陣",
                body=self._render_company_comparison_matrix(
                    request,
                    ordered_tickers,
                    documents,
                    findings,
                    market_snapshots,
                    monthly_revenues,
                    financial_metrics,
                    valuation_metrics,
                    leading_signals,
                ),
            ),
            ReportSection(
                title="投資理由地圖",
                body=self._render_investment_thesis_map(
                    request,
                    ordered_tickers,
                    documents,
                    findings,
                    market_snapshots,
                    monthly_revenues,
                    financial_metrics,
                    valuation_metrics,
                    leading_signals,
                ),
            ),
            ReportSection(
                title="二次綜合篩選",
                body=self._render_final_potential_screen(
                    ordered_tickers,
                    documents,
                    findings,
                    market_snapshots,
                    monthly_revenues,
                    financial_metrics,
                    valuation_metrics,
                    leading_signals,
                    request=request,
                ),
            ),
            ReportSection(
                title="評分明細",
                body=self._render_score_breakdown(
                    ordered_tickers,
                    documents,
                    findings,
                    market_snapshots,
                    monthly_revenues,
                    financial_metrics,
                    valuation_metrics,
                    leading_signals,
                ),
            ),
            ReportSection(title="基本面月營收檢查", body=self._render_revenue_check(ordered_tickers, monthly_revenues)),
            ReportSection(
                title="個別公司分析",
                body=self._render_company_analysis(
                    ordered_tickers,
                    documents,
                    findings,
                    market_snapshots,
                    monthly_revenues,
                    financial_metrics,
                    valuation_metrics,
                    request=request,
                    leading_signals=leading_signals,
                ),
            ),
            ReportSection(title="主要風險與瓶頸", body=self._render_risk_overview(findings, ordered_tickers)),
            ReportSection(title="分析範圍", body=self._render_scope(ordered_tickers, market_snapshots, monthly_revenues)),
            ReportSection(
                title="附錄：AI 補充與資料來源",
                body=self._render_appendix(llm_result, documents, market_snapshots, tickers=ordered_tickers),
            ),
        ]
        context = ReportContext(
            title=f"{request.topic} 自動分析報告",
            topic=request.topic,
            generated_at=now_taipei(),
            sections=sections,
        )
        return ReportMarkdownRenderer().render(context)

    def _render_credibility_check(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "目前沒有形成可驗證股票範圍；本報告可信度不足，只能作為主題觀察。"

        publishers = {
            document.source.publisher or document.source.url or document.title or "來源不明"
            for document in documents
        }
        dated_documents = [document for document in documents if document.source.published_at is not None]
        cutoff = now_taipei().date() - timedelta(days=request.lookback_days)
        recent_documents = [
            document
            for document in dated_documents
            if document.source.published_at and document.source.published_at >= cutoff
        ]
        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        companies = {company.ticker: company for company in self.whitelist.companies()}

        company_rows = []
        high_count = 0
        medium_count = 0
        low_count = 0
        for ticker in tickers:
            company = companies.get(ticker)
            related_documents = self._related_documents(ticker, documents)
            related_findings = self._related_findings(ticker, findings)
            related_publishers = {
                document.source.publisher or document.source.url or document.title or "來源不明"
                for document in related_documents
            }
            latest_dates = [
                document.source.published_at
                for document in related_documents
                if document.source.published_at is not None
            ]
            latest = max(latest_dates).isoformat() if latest_dates else "日期不明"
            ticker_metrics = metrics_by_ticker.get(ticker, [])
            signal = (leading_signals or {}).get(ticker)
            filing_missing = self._company_filing_missing(ticker, documents)
            quality = self._data_quality_grade(
                related_documents,
                related_findings,
                snapshots.get(ticker),
                revenues.get(ticker),
                ticker_metrics,
                valuations.get(ticker),
                financial_metrics is not None or valuation_metrics is not None,
                signal,
                filing_missing,
                recent_source_days=request.lookback_days,
            )
            limitations = []
            if len(related_documents) < 2:
                limitations.append("公司文本少於 2 筆")
            if len(related_publishers) < 2:
                limitations.append("來源家數少於 2")
            if not related_findings:
                limitations.append("缺少風險/機會歸因")
            if ticker not in snapshots:
                limitations.append("缺股價")
            if ticker not in revenues:
                limitations.append("缺月營收")
            if not ticker_metrics:
                limitations.append("缺已揭露年度財報")
            if ticker not in valuations:
                limitations.append("缺估值")
            if filing_missing:
                limitations.append("缺公司公開文件")

            if quality["grade"] == "supported" and len(related_publishers) >= 2 and related_findings:
                credibility = "高"
                high_count += 1
            elif quality["grade"] in {"supported", "partial"} or (len(related_documents) >= 2 and len(related_publishers) >= 2):
                credibility = "中"
                medium_count += 1
            else:
                credibility = "低"
                low_count += 1
            label = f"{ticker} {company.name if company else ticker}"
            company_rows.append(
                self._table_row(
                    [
                        label,
                        credibility,
                        f"{len(related_documents)} 筆 / {len(related_publishers)} 來源",
                        f"{len(related_findings)} 筆",
                        latest,
                        "、".join(limitations[:5]) if limitations else "未發現重大資料缺口",
                    ]
                )
            )

        date_coverage = f"{len(dated_documents)}/{len(documents)} 筆" if documents else "0/0 筆"
        recent_coverage = f"{len(recent_documents)}/{len(documents)} 筆" if documents else "0/0 筆"
        source_status = "可追溯" if documents else "不足"
        diversity_status = "多來源" if len(publishers) >= 3 else "偏少"
        date_status = "可判讀" if dated_documents else "不足"
        company_status = "可用" if high_count or medium_count else "不足"
        lines = [
            "本段檢查正式報告的分析可信度；這不同於「候選公司審計」的入選支持度。若分析可信度不足，結論會降級為觀察或待補資料。",
            "",
            "| 檢查項目 | 狀態 | 本次證據 | 對投資判斷的影響 |",
            "|---|---|---|---|",
            f"| 可追溯來源 | {source_status} | 共 {len(documents)} 筆文本 | 沒有來源時只保留主題觀察，不產生買進研究。 |",
            f"| 來源多樣性 | {diversity_status} | {len(publishers)} 個發布者 | 來源過少時，避免被單一新聞或單一觀點誤導。 |",
            f"| 全體來源時間戳 | {date_status} | {date_coverage} 有日期；近 {request.lookback_days} 天 {recent_coverage} | 這是全報告證據池覆蓋率；個股仍需看下方最近來源日期。 |",
            f"| 公司層級分析完整度 | {company_status} | 高分析可信度 {high_count} 檔、中分析可信度 {medium_count} 檔、低分析可信度 {low_count} 檔 | 只有題材但缺近期公司證據時，不列入可研究標的。 |",
            f"| 市場與財務資料 | 可檢查 | 股價 {len(snapshots)} 檔、月營收 {len(revenues)} 檔、估值 {len(valuations)} 檔 | 財務或估值缺口會限制投資理由強度。 |",
            f"| 風險/機會歸因 | {'可用' if findings else '不足'} | {len(findings)} 筆系統驗證後歸因 | 風險未歸因時，不把新聞熱度直接當投資理由。 |",
            "",
            "### 個股可信度核對",
            "| 股票 | 分析可信度 | 公司文本 | 歸因證據 | 最近來源日期 | 主要限制 |",
            "|---|---|---:|---:|---|---|",
            *company_rows,
            "",
            "### 分析可信度判讀規則",
            "- 高分析可信度：公司文本、來源家數、風險/機會歸因、股價、月營收、財報、估值、公司文件與近期公司文本大致齊備。",
            "- 中分析可信度：已有公司層級證據，但仍有財務、估值、官方文件或近期資料缺口。",
            "- 低分析可信度：文本、來源家數或公司層級歸因不足；只能觀察，不應形成買進研究。",
        ]
        return "\n".join(lines)

    def _decision_contexts(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> list[dict]:
        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        peer_valuation_summary = self._peer_valuation_summary(list(valuations.values()))
        companies = {company.ticker: company for company in self.whitelist.companies()}
        downside_gate = self._downside_gate(request)
        contexts = []
        for ticker in tickers:
            company = companies.get(ticker)
            related_documents = self._related_documents(ticker, documents)
            related_findings = self._related_findings(ticker, findings)
            snapshot = snapshots.get(ticker)
            revenue = revenues.get(ticker)
            signal = (leading_signals or {}).get(ticker)
            valuation = valuations.get(ticker)
            ticker_metrics = metrics_by_ticker.get(ticker, [])
            estimate = self._estimate_potential(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                signal,
                ticker_metrics,
                valuation,
                peer_valuation_summary,
            )
            quality = self._data_quality_grade(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                ticker_metrics,
                valuation,
                financial_metrics is not None or valuation_metrics is not None,
                signal,
                self._company_filing_missing(ticker, documents),
                recent_source_days=request.lookback_days,
            )
            decision = self._decision_label(estimate, quality, related_findings, downside_gate, signal)
            valuation_label = self._valuation_position_label(
                valuation,
                peer_valuation_summary,
                self._has_negative_profitability(ticker_metrics),
            )
            contexts.append(
                {
                    "ticker": ticker,
                    "name": company.name if company else ticker,
                    "label": f"{ticker} {company.name if company else ticker}",
                    "documents": related_documents,
                    "findings": related_findings,
                    "snapshot": snapshot,
                    "revenue": revenue,
                    "valuation": valuation,
                    "valuation_label": valuation_label,
                    "current_price": self._current_price_text(snapshot),
                    "current_price_label": self._current_price_label(
                        snapshot,
                        estimate,
                        quality,
                        valuation_label,
                        signal,
                        decision,
                        downside_gate,
                    ),
                    "estimate": estimate,
                    "leading_signal": signal,
                    "quality": quality,
                    "decision": decision,
                }
            )
        return contexts

    def _ordered_tickers_for_reading(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> list[str]:
        contexts = self._decision_contexts(
            request,
            tickers,
            documents,
            findings,
            market_snapshots,
            monthly_revenues,
            financial_metrics,
            valuation_metrics,
            leading_signals,
        )
        return [context["ticker"] for context in self._sort_decision_contexts(contexts)]

    @classmethod
    def _sort_decision_contexts(cls, contexts: list[dict]) -> list[dict]:
        return report_decision_rules.sort_decision_contexts(contexts)

    @classmethod
    def _decision_sort_key(cls, context: dict) -> tuple:
        return report_decision_rules.decision_sort_key(context)

    @staticmethod
    def _decision_rank(decision: str | None) -> int:
        return report_decision_rules.decision_rank(decision)

    @staticmethod
    def _context_current_price(context: dict) -> float:
        return report_decision_rules.context_current_price(context)

    def _render_action_checklist(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "1. 先補足新聞與市場資料，再重新執行分析。"

        contexts = self._sort_decision_contexts(
            self._decision_contexts(
                request,
                tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            )
        )
        research = [item for item in contexts if item["decision"] == "可小額分批研究"]
        watch = [
            item
            for item in contexts
            if item["decision"] not in {"可小額分批研究", "避開 / 降低曝險"}
        ]
        avoid = [item for item in contexts if item["decision"] == "避開 / 降低曝險"]

        lines = [
            "1. 先處理資料缺口：若有「缺主題歸因、缺月營收、缺股價、缺公司公開文件」，先補資料再考慮加碼。",
            "2. 只把資料完整且通過目前情境降值門檻的股票放進小額研究清單。",
            "3. 對目前情境降值分高於門檻或近況訊號偏空的股票，先等風險下降或新資料確認。",
            "",
            "### 可立即研究",
        ]
        if research:
            for item in research:
                lines.append(
                    f"- {item['label']}：可看資金控管建議中的首筆配置；"
                    f"目前情境升值分 {item['estimate']['upside_pct']} 分，"
                    f"目前情境降值分 {item['estimate']['downside_pct']} 分。"
                )
        else:
            lines.append("- 目前沒有同時通過資料完整度與風險門檻的標的。")

        lines.extend(["", "### 待補資料 / 觀察"])
        if watch:
            for item in watch:
                missing = "、".join(item["quality"]["missing"]) if item["quality"]["missing"] else "等待新證據"
                lines.append(
                    f"- {item['label']}：{item['decision']}；下一步補查 {missing}。"
                    f"重新評估條件：{self._recheck_trigger_text(item, self._downside_gate(request))}"
                )
        else:
            lines.append("- 目前沒有待補資料名單。")

        lines.extend(["", "### 先避開"])
        if avoid:
            for item in avoid:
                lines.append(
                    f"- {item['label']}：目前情境降值分 {item['estimate']['downside_pct']} 分，"
                    f"暫不列入買進研究。重新評估條件：{self._recheck_trigger_text(item, self._downside_gate(request))}"
                )
        else:
            lines.append("- 目前沒有明確避開名單。")
        return "\n".join(lines)

    @staticmethod
    def _recheck_trigger_text(context: dict, downside_gate: int | None = None) -> str:
        return report_decision_rules.recheck_trigger_text(context, downside_gate)

    @staticmethod
    def _avoid_trigger_text(context: dict, downside_gate: int | None = None) -> str:
        return report_decision_rules.avoid_trigger_text(context, downside_gate)

    @staticmethod
    def _monitor_frequency(context: dict) -> str:
        return report_decision_rules.monitor_frequency(context)

    def _render_monitoring_checklist(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "目前無可監控股票。"
        downside_gate = self._downside_gate(request)
        contexts = self._sort_decision_contexts(
            self._decision_contexts(
                request,
                tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            )
        )
        lines = [
            "這張表把觀察與避開名單轉成可執行監控規則；條件未改善前，不把觀察股升級為買進研究。",
            "",
            "| 股票 | 目前動作 | 重新研究條件 | 繼續避開/觀察條件 | 監控頻率 |",
            "|---|---|---|---|---|",
        ]
        for context in contexts:
            lines.append(
                self._table_row(
                    [
                        context["label"],
                        context["decision"],
                        self._recheck_trigger_text(context, downside_gate),
                        self._avoid_trigger_text(context, downside_gate),
                        self._monitor_frequency(context),
                    ]
                )
            )
        return "\n".join(lines)

    def _render_follow_up_actions(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        contexts = self._sort_decision_contexts(
            self._decision_contexts(
                request,
                tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            )
        )
        downside_gate = self._downside_gate(request)
        for context in contexts:
            context["downside_gate"] = downside_gate
            context["recheck_trigger"] = self._recheck_trigger_text(context, downside_gate)
            context["avoid_trigger"] = self._avoid_trigger_text(context, downside_gate)
        actions = FollowUpActionPlanner().plan(request, contexts=contexts)
        return render_follow_up_actions_markdown(actions)

    @staticmethod
    def _render_time_scope_note(
        request: ReportRequest,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
    ) -> str:
        latest_market = max((snapshot.trade_date for snapshot in market_snapshots), default=None)
        latest_revenue = max((revenue.revenue_date for revenue in monthly_revenues or []), default=None)
        latest_valuation = max((valuation.trade_date for valuation in valuation_metrics or []), default=None)
        market_text = latest_market.isoformat() if latest_market else "尚無股價日期"
        revenue_text = latest_revenue.isoformat() if latest_revenue else "尚無月營收日期"
        valuation_text = latest_valuation.isoformat() if latest_valuation else "尚無估值日期"
        generated_text = now_taipei().isoformat(timespec="seconds")
        return "\n".join(
            [
                f"- 「目前」指本報告生成時間（台灣）{generated_text} 前已取得並通過資料品質檢查的內容，不代表未來一定維持。",
                f"- 「近 {request.lookback_days} 天來源」指新聞/RAG 來源回看區間；公司公開文件、已揭露年度財報與估值仍以各自原始日期判讀。",
                f"- 「目前估值」只比較最新估值日 {valuation_text} 的 P/E、P/B、殖利率與本次同業樣本，不是未來估值預測。",
                "- 「追價風險標籤」會納入最新可取得收盤價、近 20/60 日股價動能、量能、目前相對估值與目前情境降值分；它是追價風險提示，不是即時報價或買賣指令。",
                "- 「目前情境升值分／目前情境降值分」是依目前證據計算的排序分數，不是預期報酬率、目標價或保證幅度。",
                f"- 「近況訊號」使用最新股價日 {market_text}、月營收日 {revenue_text} 與估值日 {valuation_text} 的近 20/60 日或月資料，是追蹤警示，不是未來走勢預測。",
            ]
        )

    @staticmethod
    def _render_decision_criteria_note(request: ReportRequest) -> str:
        downside_gate = ReportGenerator._downside_gate(request)
        return "\n".join(
            [
                f"- 本次投資人設定為「{ReportGenerator._profile_label(request)}」；目前情境降值分超過 {downside_gate} 分時，原則上先列觀察。",
                "- 「可小額分批研究」必須同時符合：資料等級完整、目前情境升值分高於 10 分、目前情境降值分未超過投資人門檻、近況訊號不偏空，且沒有結構性瓶頸、短期波動或財務/估值紅旗。",
                "- 「觀察 / 等風險降低」代表題材與資料可以追蹤，但存在結構性瓶頸或尚未解除的財務/估值疑慮，不列入本次配置。",
                "- 「避開 / 降低曝險」代表目前情境降值分已高於升值分，或財務/估值紅旗偏重；單純超過投資人門檻會先列觀察，不會一票否決。",
                "- 「追價風險標籤」若顯示不適合追價、等止跌、等回檔或等風險下降，代表現在不應只因題材熱度就投入。",
                "- 財務/估值檢查會納入已揭露年度營收、淨利、負債權益比、ROE/淨利率與目前相對估值；若財務紅旗存在，題材分數不能單獨升級成可研究標的。",
            ]
        )

    def _render_executive_snapshot(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "本次沒有形成可驗證個股清單；先補資料，不建議依此報告做個股配置。"

        rows = []
        actionable = 0
        watch = 0
        avoid = 0
        weak = 0
        for item in self._sort_decision_contexts(
            self._decision_contexts(
                request,
                tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            )
        ):
            decision = item["decision"]
            quality = item["quality"]
            estimate = item["estimate"]
            signal = item.get("leading_signal")
            if decision == "可小額分批研究":
                actionable += 1
            elif decision == "避開 / 降低曝險":
                avoid += 1
            elif quality["grade"] == "weak":
                weak += 1
            else:
                watch += 1
            rows.append(
                self._table_row(
                    [
                        item["label"],
                        decision,
                        item["current_price"],
                        item["current_price_label"],
                        self._quality_label(quality["grade"]),
                        f"{estimate['upside_pct']} 分",
                        f"{estimate['downside_pct']} 分",
                        signal.direction if signal else "未評估",
                        "、".join(quality["missing"]) if quality["missing"] else "完整",
                    ]
                )
            )

        deployable = request.investor_capital - int(request.investor_capital * request.cash_reserve_pct)
        if actionable:
            headline = f"本次有 {actionable} 檔可小額研究；仍需依資金控管分批，不建議一次買滿。"
        elif avoid:
            headline = "本次沒有可小額研究標的，且有股票進入避開/降低曝險名單。"
        else:
            headline = "本次沒有可小額研究標的；先補資料或等待新證據。"
        lines = [
            f"**重點提醒：{headline}**",
            "",
            "| 項目 | 結果 |",
            "|---|---|",
            f"| 投資人設定 | {self._profile_label(request)}；總資金 {request.investor_capital:,} 元；"
            f"品質門檻最多允許研究約 {deployable:,} 元，但本次實際配置以投資建議與資金控管為準 |",
            f"| 本次股票範圍 | {len(tickers)} 檔 |",
            f"| 可小額研究 | {actionable} 檔 |",
            f"| 觀察/待補 | {watch + weak} 檔 |",
            f"| 避開/降低曝險 | {avoid} 檔 |",
        ]
        if self._is_low_attention_topic(request.topic):
            lines.append(
                "| 低關注核對 | 可小額研究不等於低關注；是否真的屬於報導較少標的，請以「早期潛力雷達」為準 |"
            )
        lines.extend(
            [
                "",
                "### 決策總覽",
                REPORT_READING_SORT_NOTE,
                "",
                "| 股票 | 判斷 | 最新可取得收盤價 | 追價風險標籤 | 資料等級 | 目前情境升值分 | 目前情境降值分 | 近況訊號 | 主要缺口 |",
                "|---|---|---|---|---|---:|---:|---|---|",
                *rows,
                "",
                "閱讀方式：先看「判斷」與「主要缺口」；升值/降值欄位是目前情境分數，不是未來報酬率。",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _is_low_attention_topic(topic: str) -> bool:
        normalized = str(topic or "").lower()
        return any(term in normalized for term in ["低關注", "冷門", "未被市場", "low attention"])

    def _render_data_quality(
        self,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
        request: ReportRequest | None = None,
    ) -> str:
        if not tickers:
            return "未形成可驗證股票範圍；本次報告只能保留主題觀察，不能產出個股投資判斷。"

        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        companies = {company.ticker: company for company in self.whitelist.companies()}
        strong = 0
        partial = 0
        weak = 0
        lines = [
            "本段檢查每檔股票是否同時具備新聞/RAG、主題歸因、股價、月營收、已揭露年度財報、估值與公司公開文件；資料不足時，系統會降低建議強度。",
            "",
            "| 股票 | 新聞/RAG | 主題歸因 | 股價 | 月營收 | 年度財報 | 估值 | 公司文件 | 近況訊號 | 判讀 |",
            "|---|---:|---:|---|---|---:|---|---|---|---|",
        ]
        for ticker in tickers:
            company = companies.get(ticker)
            related_documents = self._related_documents(ticker, documents)
            related_findings = self._related_findings(ticker, findings)
            has_snapshot = ticker in snapshots
            has_revenue = ticker in revenues
            ticker_metrics = metrics_by_ticker.get(ticker, [])
            valuation = valuations.get(ticker)
            signal = (leading_signals or {}).get(ticker)
            filing_missing = self._company_filing_missing(ticker, documents)
            quality = self._data_quality_grade(
                related_documents,
                related_findings,
                snapshots.get(ticker),
                revenues.get(ticker),
                ticker_metrics,
                valuation,
                financial_metrics is not None or valuation_metrics is not None,
                signal,
                filing_missing,
                recent_source_days=request.lookback_days if request else None,
            )
            missing = quality["missing"]

            if not missing:
                verdict = "完整，可進入二次篩選"
                strong += 1
            elif quality["grade"] == "partial":
                verdict = "部分可用，僅列觀察：" + "、".join(missing)
                partial += 1
            else:
                verdict = "不足：" + "、".join(missing)
                weak += 1

            label = f"{ticker} {company.name if company else ticker}"
            price_label = snapshots[ticker].trade_date.isoformat() if has_snapshot else "缺"
            revenue_label = (
                f"{revenues[ticker].revenue_year}-{revenues[ticker].revenue_month:02d}"
                if has_revenue
                else "缺"
            )
            financial_label = str(len(ticker_metrics)) if ticker_metrics else "缺"
            valuation_label = valuation.trade_date.isoformat() if valuation else "缺"
            filing_label = "足夠" if not filing_missing else "缺"
            signal_label = signal.direction if signal and signal.has_signal_data else "缺"
            lines.append(
                self._table_row(
                    [
                        label,
                        len(related_documents),
                        len(related_findings),
                        price_label,
                        revenue_label,
                        financial_label,
                        valuation_label,
                        filing_label,
                        signal_label,
                        verdict,
                    ]
                )
            )

        lines.extend(
            [
                "",
                f"整體判讀：完整 {strong} 檔、部分可用 {partial} 檔、資料不足 {weak} 檔。",
            ]
        )
        if weak or partial:
            lines.append("投資結論會優先採用資料完整標的；資料不足標的不會只因單一題材或單一財務數字被列為優先買進。")
        return "\n".join(lines)

    def _render_score_breakdown(
        self,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "目前無足夠數據判斷。"

        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        peer_valuation_summary = self._peer_valuation_summary(list(valuations.values()))
        companies = {company.ticker: company for company in self.whitelist.companies()}
        lines = [
            "此段拆解研究分級來源；分數是排序與風險控管用途，不代表預期報酬率。",
            "",
            "| 股票 | 目前情境升值分 | 目前情境降值分 | 主要加分 | 主要風險 | 資料提醒 |",
            "|---|---:|---:|---|---|---|",
        ]
        for ticker in tickers:
            company = companies.get(ticker)
            label = f"{ticker} {company.name if company else ticker}"
            related_documents = self._related_documents(ticker, documents)
            related_findings = self._related_findings(ticker, findings)
            estimate = self._estimate_potential(
                related_documents,
                related_findings,
                snapshots.get(ticker),
                revenues.get(ticker),
                (leading_signals or {}).get(ticker),
                metrics_by_ticker.get(ticker, []),
                valuations.get(ticker),
                peer_valuation_summary,
            )
            lines.append(
                self._table_row(
                    [
                        label,
                        f"{estimate['upside_pct']} 分",
                        f"{estimate['downside_pct']} 分",
                        self._format_factors(estimate["upside_factors"]),
                        self._format_factors(estimate["downside_factors"]),
                        self._score_data_note(
                            estimate["confidence_notes"],
                            metrics_by_ticker.get(ticker, []),
                            valuations.get(ticker),
                        ),
                    ]
                )
            )
        return "\n".join(lines)

    def _render_source_coverage(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
    ) -> str:
        documents = filter_formal_evidence_documents(documents)
        if not documents:
            return "目前無足夠數據判斷。"

        publisher_counts = Counter(document.source.publisher or "來源不明" for document in documents)
        international_count = sum(1 for document in documents if self._is_international_source(document))
        taiwan_count = len(documents) - international_count
        lines = [
            "本段說明本次可追溯證據池的來源覆蓋；來源多不代表一定可買，仍需看公司層級歸因與財務資料是否同時成立。",
            "",
            "| 項目 | 結果 |",
            "|---|---|",
            f"| 摘要使用證據上限 | {request.evidence_limit} 筆 |",
            f"| 可追溯證據池總量 | {len(documents)} 筆 |",
            f"| 台灣來源 | {taiwan_count} 筆 |",
            f"| 國際來源 | {international_count} 筆 |",
            self._table_row(
                [
                    "主要來源",
                    "、".join(f"{publisher}({count})" for publisher, count in publisher_counts.most_common(6)),
                ]
            ),
            "",
            "### 個股來源覆蓋",
            "| 股票 | 公司相關文本 | 國際文本 | 最近來源日期 | 代表來源 |",
            "|---|---:|---:|---|---|",
        ]
        companies = {company.ticker: company for company in self.whitelist.companies()}
        for ticker in tickers:
            related_documents = self._related_documents(ticker, documents)
            related_international = sum(1 for document in related_documents if self._is_international_source(document))
            latest_dates = [
                document.source.published_at
                for document in related_documents
                if document.source.published_at is not None
            ]
            latest = max(latest_dates).isoformat() if latest_dates else "日期不明"
            company = companies.get(ticker)
            label = f"{ticker} {company.name if company else ticker}"
            lines.append(
                self._table_row(
                    [
                        label,
                        len(related_documents),
                        related_international,
                        latest,
                        self._representative_sources(related_documents, limit=4),
                    ]
                )
            )
        if international_count == 0:
            lines.extend(["", "提醒：本次沒有國際來源進入證據池；若要擴大國際覆蓋，請開啟深度分析與國際資料源。"])
        return "\n".join(lines)

    def _render_candidate_audit(self, promoted_tickers: list[str]) -> str:
        return render_candidate_audit_markdown(self.whitelist.candidate_audit(), promoted_tickers)

    @staticmethod
    def _render_leading_signal_check(
        tickers: list[str],
        leading_signals: dict[str, LeadingSignal],
    ) -> str:
        if not tickers:
            return "目前無足夠數據判斷。"
        lines = [
            "本段使用截至最新資料日的股價歷史、成交量、月營收加速與目前同業估值位置，補足新聞較慢的問題；它是近況警示與排序訊號，不是未來走勢預測或單獨買賣依據。",
            "",
            "| 股票 | 近況方向 | 分數 | 近20日股價 | 近60日股價 | 近20日量能 | 最新月營收YoY | 營收加速 | 目前估值 | 核心訊號 |",
            "|---|---|---:|---:|---:|---:|---:|---:|---|---|",
        ]
        for ticker in tickers:
            signal = leading_signals.get(ticker)
            if not signal:
                lines.append(
                    ReportGenerator._table_row(
                        [ticker, "未評估", 0, "-", "-", "-", "-", "-", "未評估", "目前無足夠近況訊號。"]
                    )
                )
                continue
            lines.append(
                ReportGenerator._table_row(
                    [
                        ticker,
                        signal.direction,
                        str(signal.score),
                        ReportGenerator._format_optional_pct(signal.price_20d_pct),
                        ReportGenerator._format_optional_pct(signal.price_60d_pct),
                        ReportGenerator._format_optional_ratio(signal.volume_ratio_20d),
                        ReportGenerator._format_optional_pct(signal.revenue_yoy_pct),
                        ReportGenerator._format_optional_pct(signal.revenue_acceleration_pct),
                        signal.valuation_label,
                        signal.summary,
                    ]
                )
            )
        return "\n".join(lines)

    @staticmethod
    def _format_optional_pct(value: float | None) -> str:
        return "-" if value is None else f"{value:.1f}%"

    @staticmethod
    def _format_optional_ratio(value: float | None) -> str:
        return "-" if value is None else f"{value:.1f}x"

    def _render_early_potential_radar(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
    ) -> str:
        if not tickers:
            return "目前無足夠數據判斷。"
        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        companies = {company.ticker: company for company in self.whitelist.companies()}
        candidate_evidence = self._candidate_audit_evidence_counts()
        contexts = {
            context["ticker"]: context
            for context in self._decision_contexts(
                request,
                tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            )
        }
        rows = []
        for ticker in tickers:
            context = contexts.get(ticker)
            if context and context["decision"] == "避開 / 降低曝險":
                continue
            related_documents = self._related_documents(ticker, documents)
            related_findings = self._related_findings(ticker, findings)
            signal = (leading_signals or {}).get(ticker)
            estimate = dict(context["estimate"]) if context else self._estimate_potential(
                related_documents,
                related_findings,
                snapshots.get(ticker),
                revenues.get(ticker),
                signal,
            )
            audit_counts = candidate_evidence.get(ticker, {})
            estimate.update(
                self._early_potential_profile(
                    related_documents,
                    revenues.get(ticker),
                    signal,
                    estimate["upside_pct"],
                    estimate["downside_pct"],
                    snapshots.get(ticker),
                    document_count_override=max(
                        len(related_documents),
                        int(audit_counts.get("evidence_count") or 0),
                    ),
                    publisher_count_override=max(
                        self._publisher_count(related_documents),
                        int(audit_counts.get("source_count") or 0),
                    ),
                )
            )
            if estimate["early_potential_score"] <= 0:
                continue
            if estimate["attention_label"] not in {"報導較少", "報導偏少"}:
                continue
            company = companies.get(ticker)
            decision_note = f"目前決策：{context['decision']}；" if context else ""
            rows.append(
                {
                    "label": f"{ticker} {company.name if company else ticker}",
                    "score": estimate["early_potential_score"],
                    "attention": estimate["attention_label"],
                    "upside": estimate["upside_pct"],
                    "downside": estimate["downside_pct"],
                    "reason": decision_note + estimate["early_potential_reason"],
                    "source": self._representative_sources(related_documents, limit=2),
                }
            )
        rows.sort(key=lambda row: (-row["score"], row["downside"], -row["upside"]))
        lines = [
            "本段專門找「截至目前報導較少、但近況訊號轉強」的研究線索；已排除避開/降低曝險標的。報導較少不是利多，代表仍需更多來源、成交量與公司文件驗證。",
        ]
        if not rows:
            lines.append("")
            lines.append("目前沒有同時符合「報導較少」與「近況訊號轉強」的標的。")
            return "\n".join(lines)
        lines.extend(
            [
                "",
                "| 股票 | 早期線索分 | 截至目前報導熱度 | 目前情境升值分 | 目前情境降值分 | 為什麼可能還早 | 代表來源 |",
                "|---|---:|---|---:|---:|---|---|",
            ]
        )
        for row in rows[:8]:
            lines.append(
                self._table_row(
                    [
                        row["label"],
                        str(row["score"]),
                        row["attention"],
                        f"{row['upside']} 分",
                        f"{row['downside']} 分",
                        row["reason"],
                        row["source"],
                    ]
                )
            )
        return "\n".join(lines)

    def _render_final_potential_screen(
        self,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
        request: ReportRequest | None = None,
    ) -> str:
        if not tickers:
            return "目前無足夠數據判斷。"

        request = request or ReportRequest(tickers=tickers)
        contexts = self._sort_decision_contexts(
            self._decision_contexts(
                request,
                tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            )
        )
        upside_rows = []
        watch_upside_rows = []
        blocked_upside_rows = []
        downside_rows = []
        insufficient_rows = []

        for context in contexts:
            ticker = context["ticker"]
            snapshot = context.get("snapshot")
            revenue = context.get("revenue")
            estimate = context["estimate"]
            quality = context["quality"]
            decision = context["decision"]
            label = context["label"]
            source = (
                f"{snapshot.trade_date.isoformat()} {snapshot.source} {ticker}"
                if snapshot
                else "目前無足夠數據判斷"
            )
            if revenue:
                source += f"；{revenue.revenue_date.isoformat()} {revenue.source} {ticker}"

            if estimate["upside_pct"] > 10:
                if decision == "避開 / 降低曝險":
                    blocked_upside_rows.append(
                        f"- {label}：升值分約 {estimate['upside_pct']} 分，但最終判斷為「{decision}」；"
                        f"主要原因：{self._risk_warning_reason(estimate)}來源：{source}。"
                    )
                elif quality["grade"] != "supported":
                    insufficient_rows.append(
                        f"- {label}：目前證據的情境升值分約 {estimate['upside_pct']} 分，但資料品質不足；"
                        f"{'；'.join(quality['missing'])}。"
                    )
                elif decision == "可小額分批研究":
                    upside_rows.append(
                        f"- {label}：目前證據的情境升值分約 {estimate['upside_pct']} 分。"
                        f"理由：{estimate['upside_reason']} 來源：{source}。"
                    )
                else:
                    watch_upside_rows.append(
                        f"- {label}：升值分約 {estimate['upside_pct']} 分，但最終判斷為「{decision}」；"
                        "需等降值分、近況訊號或風險證據改善後再研究配置。"
                    )
            if estimate["downside_pct"] > 5:
                downside_rows.append(
                    f"- {label}：目前證據的情境降值分約 {estimate['downside_pct']} 分。"
                    f"理由：{estimate['downside_reason']} 來源：{source}。"
                )
            if estimate["upside_pct"] <= 10 and estimate["downside_pct"] <= 5:
                insufficient_rows.append(f"- {label}：未達目前情境升值/降值門檻或資料不足。")

        lines = [
            "本段為非個人化情境篩選；分數是依新聞、財務、估值與市場資料的研究分級，不是保證報酬或停損幅度。最終是否可研究以「判斷」為準，不只看升值分。",
            "",
            "### 升值分較高且通過風險門檻",
        ]
        lines.extend(upside_rows or ["目前無足夠數據判斷。"])
        if watch_upside_rows:
            lines.extend(["", "### 升值分高但仍需觀察", *watch_upside_rows])
        if blocked_upside_rows:
            lines.extend(["", "### 升值分高但風險壓過", *blocked_upside_rows])
        lines.extend(["", "### 目前情境降值分較高（目前證據 >5）"])
        lines.extend(downside_rows or ["目前無足夠數據判斷。"])
        if insufficient_rows:
            lines.extend(["", "### 未通過研究門檻 / 資料不足", *insufficient_rows])
        return "\n".join(lines)

    def _render_company_comparison_matrix(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "目前無足夠數據判斷。"

        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        peer_valuation_summary = self._peer_valuation_summary(list(valuations.values()))
        companies = {company.ticker: company for company in self.whitelist.companies()}
        downside_gate = self._downside_gate(request)
        rows = []
        for ticker in tickers:
            company = companies.get(ticker)
            related_documents = self._related_documents(ticker, documents)
            related_findings = self._related_findings(ticker, findings)
            snapshot = snapshots.get(ticker)
            revenue = revenues.get(ticker)
            ticker_metrics = metrics_by_ticker.get(ticker, [])
            valuation = valuations.get(ticker)
            signal = (leading_signals or {}).get(ticker)
            valuation_label = self._valuation_position_label(
                valuation,
                peer_valuation_summary,
                self._has_negative_profitability(ticker_metrics),
            )
            estimate = self._estimate_potential(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                signal,
                ticker_metrics,
                valuation,
                peer_valuation_summary,
            )
            quality = self._data_quality_grade(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                ticker_metrics,
                valuation,
                financial_metrics is not None or valuation_metrics is not None,
                signal,
                self._company_filing_missing(ticker, documents),
                recent_source_days=request.lookback_days,
            )
            decision = self._decision_label(estimate, quality, related_findings, downside_gate, signal)
            rows.append(
                {
                    "ticker": ticker,
                    "label": f"{ticker} {company.name if company else ticker}",
                    "decision": decision,
                    "snapshot": snapshot,
                    "estimate": estimate,
                    "current_price": self._current_price_text(snapshot),
                    "current_price_label": self._current_price_label(
                        snapshot,
                        estimate,
                        quality,
                        valuation_label,
                        signal,
                        decision,
                        downside_gate,
                    ),
                    "upside": estimate["upside_pct"],
                    "downside": estimate["downside_pct"],
                    "valuation": valuation_label,
                    "confidence": self._financial_confidence_label(ticker_metrics, valuation, revenue),
                    "reminder": self._company_matrix_reminder(
                        estimate,
                        quality,
                        related_findings,
                        valuation,
                        peer_valuation_summary,
                        ticker_metrics,
                        signal,
                    ),
                }
            )
        rows.sort(key=self._decision_sort_key)
        lines = [
            "這張表用來比較正式分析股票的相對位置；它是研究排序工具，不是買賣指令。",
            REPORT_READING_SORT_NOTE,
            "",
            "| 股票 | 判斷 | 最新可取得收盤價 | 追價風險標籤 | 目前情境升值分 | 目前情境降值分 | 目前估值位置 | 財務信心 | 核心提醒 |",
            "|---|---|---|---|---:|---:|---|---|---|",
        ]
        for row in rows:
            lines.append(
                self._table_row(
                    [
                        row["label"],
                        row["decision"],
                        row["current_price"],
                        row["current_price_label"],
                        f"{row['upside']} 分",
                        f"{row['downside']} 分",
                        row["valuation"],
                        row["confidence"],
                        row["reminder"],
                    ]
                )
            )
        return "\n".join(lines)

    def _render_investment_thesis_map(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "目前沒有通過證據門檻的正式分析股票；先補候選公司證據，再建立投資理由。"

        contexts = self._sort_decision_contexts(
            self._decision_contexts(
                request,
                tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            )
        )
        lines = [
            "本段把每檔股票拆成「為什麼值得研究」與「為什麼可能不成立」。這是研究假設，不是報酬保證或買賣指令。",
            REPORT_READING_SORT_NOTE,
        ]
        for context in contexts:
            estimate = context["estimate"]
            quality = context["quality"]
            documents_for_company = context["documents"]
            findings_for_company = context["findings"]
            signal: LeadingSignal | None = context.get("leading_signal")
            downside_sources = self._downside_source_references(
                documents_for_company,
                findings_for_company,
            )
            lines.extend(
                [
                    "",
                    f"### {context['label']}",
                    f"- 目前判斷：{context['decision']}；資料等級：{self._quality_label(quality['grade'])}。",
                    f"- 成長假設：{estimate['upside_reason']}",
                    f"- 主要風險：{estimate['downside_reason']}",
                    f"- 具體投資理由：{self._thesis_reason(context, request)}",
                    *(
                        [f"- 營收口徑提醒：{estimate['mom_revenue_caveat']}"]
                        if estimate.get("mom_revenue_caveat")
                        else []
                    ),
                    f"- 近況訊號：{signal.summary if signal and signal.has_signal_data else '目前缺股價歷史、月營收或估值序列，無法形成完整近況訊號。'}",
                    f"- 需要再確認：{self._thesis_verification_items(quality, findings_for_company, documents_for_company)}",
                    f"- 代表性來源：{self._representative_sources(documents_for_company)}",
                ]
            )
            if downside_sources:
                lines.append(f"- 風險來源：{downside_sources}")
        return "\n".join(lines)

    @staticmethod
    def _thesis_reason(context: dict, request: ReportRequest) -> str:
        estimate = context.get("estimate") or {}
        quality = context.get("quality") or {}
        decision = context.get("decision") or "觀察"
        downside_gate = ReportGenerator._downside_gate(request)
        if decision == "避開 / 降低曝險":
            positive = (
                f"雖然目前情境升值分有 {estimate.get('upside_pct', 0)} 分，"
                if estimate.get("upside_pct", 0) > 10
                else ""
            )
            return (
                f"{positive}但{ReportGenerator._risk_warning_reason(estimate)}"
                "因此本段不是買進理由，而是說明為何暫不投入或降低曝險。"
            )
        if decision == "觀察 / 等風險降低":
            return (
                f"目前情境升值分 {estimate.get('upside_pct', 0)} 分，"
                f"目前情境降值分 {estimate.get('downside_pct', 0)} 分，"
                f"高於或接近投資人設定門檻 {downside_gate} 分；"
                "即使有題材或近況動能，也需等風險證據、財務紅旗或近況訊號改善後再研究配置。"
            )
        if decision == "觀察 / 資料待補":
            missing = "、".join(quality.get("missing") or [])
            return (
                f"目前情境升值分 {estimate.get('upside_pct', 0)} 分，"
                f"但資料層仍待補足（{missing or '公司層級證據不足'}），暫不視為可配置理由。"
            )
        reasons = []
        if estimate.get("upside_pct", 0) > 10:
            reasons.append(f"目前情境升值分 {estimate['upside_pct']} 高於 10 分的研究門檻")
        if estimate.get("downside_pct", 0) <= downside_gate:
            reasons.append(f"目前情境降值分 {estimate['downside_pct']} 未超過投資人設定門檻")
        if quality.get("grade") == "supported":
            reasons.append("新聞/主題歸因、股價、營收、財務/估值與公司文件的資料層較完整")
        if decision == "可小額分批研究":
            reasons.append("可先放入小額研究清單，用資金上限控管，而不是一次性建立大部位")
        if not reasons:
            missing = "、".join(quality.get("missing") or [])
            return f"目前投資理由尚未完整，主要卡在 {missing or '目前情境升值分與降值分差距不夠明確'}。"
        return "；".join(reasons) + "。"

    @staticmethod
    def _thesis_verification_items(
        quality: dict,
        findings,
        related_documents: list[NewsDocument],
    ) -> str:
        items = []
        items.extend(quality.get("missing") or [])
        if any(finding.risk_type == RiskType.structural_bottleneck for finding in findings):
            items.append("結構性瓶頸是否緩解")
        if len(related_documents) < 3:
            items.append("公司層級來源是否能增加到至少 3 筆")
        if not items:
            items.append("下一期月營收、法說或官方文件是否延續目前假設")
        return "、".join(list(dict.fromkeys(items))[:5])

    @staticmethod
    def _representative_sources(documents: list[NewsDocument], limit: int = 3) -> str:
        return representative_sources(documents, limit=limit)

    @staticmethod
    def _downside_source_references(
        documents: list[NewsDocument],
        findings,
        limit: int = 3,
    ) -> str:
        return downside_source_references(
            documents,
            findings,
            limit=limit,
            scoring_text_for_document=ReportGenerator._scoring_text_for_document,
        )

    @staticmethod
    def _ordered_source_documents(documents: list[NewsDocument]) -> list[NewsDocument]:
        return ordered_source_documents(documents)

    def _appendix_documents_for_tickers(
        self,
        documents: list[NewsDocument],
        tickers: list[str] | None,
    ) -> list[NewsDocument]:
        target_tickers = {str(ticker) for ticker in tickers or [] if ticker}
        if not target_tickers:
            return documents
        matched_documents = []
        for document in documents:
            metadata_tickers = {ticker for ticker in document.entity_tickers if ticker}
            mapped_tickers = {match.ticker for match in self._document_matches(document)}
            known_tickers = metadata_tickers or mapped_tickers
            if known_tickers and not known_tickers.isdisjoint(target_tickers):
                matched_documents.append(document)
        return matched_documents or documents

    @staticmethod
    def _source_reference_line(document: NewsDocument) -> str:
        return source_reference_line(document)

    def _render_company_analysis(
        self,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        request: ReportRequest | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "未指定白名單個股，無法產出個別公司分析。"
        request = request or ReportRequest(tickers=tickers)

        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        peer_valuation_summary = self._peer_valuation_summary(list(valuations.values()))
        companies = {company.ticker: company for company in self.whitelist.companies()}
        ordered_tickers = self._ordered_tickers_for_reading(
            request,
            tickers,
            documents,
            findings,
            market_snapshots,
            monthly_revenues,
            financial_metrics,
            valuation_metrics,
            leading_signals,
        )
        overview_rows: list[str] = []
        detail_blocks: list[str] = []
        for ticker in ordered_tickers:
            company = companies.get(ticker)
            segment = self.whitelist.segment_for_ticker(ticker)
            snapshot = snapshots.get(ticker)
            revenue = revenues.get(ticker)
            ticker_metrics = metrics_by_ticker.get(ticker, [])
            valuation = valuations.get(ticker)
            related_findings = self._related_findings(ticker, findings)
            related_documents = self._related_documents(ticker, documents)
            signal = (leading_signals or {}).get(ticker)
            estimate = self._estimate_potential(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                signal,
                ticker_metrics,
                valuation,
                peer_valuation_summary,
            )
            quality = self._data_quality_grade(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                ticker_metrics,
                valuation,
                financial_metrics is not None or valuation_metrics is not None,
                signal,
                self._company_filing_missing(ticker, documents),
                recent_source_days=request.lookback_days,
            )
            downside_gate = self._downside_gate(request)
            decision = self._decision_label(estimate, quality, related_findings, downside_gate, signal)
            decision_reason = self._decision_reason(
                decision,
                estimate,
                quality,
                related_findings,
                related_documents,
                downside_gate,
                request,
                signal,
            )

            name = company.name if company else ticker
            segment_name = segment.name if segment else "白名單未分類"
            price_label = (
                f"{snapshot.trade_date.isoformat()} 收盤 {snapshot.close if snapshot.close is not None else 'NA'}"
                if snapshot
                else "缺"
            )
            revenue_label = (
                f"{revenue.revenue_year}-{revenue.revenue_month:02d} YoY "
                f"{revenue.yoy_pct:.2f}%"
                if revenue and revenue.yoy_pct is not None
                else "缺" if not revenue else f"{revenue.revenue_year}-{revenue.revenue_month:02d} YoY NA"
            )
            evidence_label = (
                f"{len(related_documents)} 文本 / {len(related_findings)} 歸因"
            )
            valuation_position = self._valuation_position_label(
                valuation,
                peer_valuation_summary,
                self._has_negative_profitability(ticker_metrics),
            )
            financial_confidence = self._financial_confidence_label(ticker_metrics, valuation, revenue)
            current_price_label = self._current_price_label(
                snapshot,
                estimate,
                quality,
                valuation_position,
                signal,
                decision,
                downside_gate,
            )
            overview_rows.append(
                self._table_row(
                    [
                        f"{ticker} {name}",
                        segment_name,
                        price_label,
                        current_price_label,
                        revenue_label,
                        valuation_position,
                        financial_confidence,
                        evidence_label,
                    ]
                )
            )

            detail_blocks.append(f"### {ticker} {name}")
            detail_blocks.append(
                "- 個股結論摘要："
                + self._company_quick_take(
                    snapshot,
                    revenue,
                    ticker_metrics,
                    valuation,
                    related_documents,
                    related_findings,
                )
            )
            detail_blocks.append(
                f"- 資料信心：{financial_confidence}；目前估值位置：{valuation_position}。"
            )
            detail_blocks.append(f"- 追價風險標籤：{current_price_label}；最新可取得收盤價：{price_label}。")
            detail_blocks.append(f"- 產業鏈位置：{segment_name}")
            detail_blocks.extend(
                self._company_basic_intro(
                    ticker,
                    name,
                    segment_name,
                    company,
                    related_documents,
                )
            )
            if snapshot:
                detail_blocks.append(
                    "- 市場資料："
                    f"{snapshot.trade_date.isoformat()} 收盤 {snapshot.close if snapshot.close is not None else 'NA'}，"
                    f"漲跌 {snapshot.spread if snapshot.spread is not None else 'NA'}，"
                    f"成交量 {snapshot.trading_volume if snapshot.trading_volume is not None else 'NA'}；"
                    f"來源：{snapshot.source}，擷取時間（台灣）{format_taipei(snapshot.fetched_at)}"
                )
            else:
                detail_blocks.append("- 市場資料：目前無足夠數據判斷。")

            if revenue:
                yoy = f"{revenue.yoy_pct:.2f}%" if revenue.yoy_pct is not None else "無去年同期可比資料"
                detail_blocks.append(
                    "- 月營收："
                    f"{revenue.revenue_year}-{revenue.revenue_month:02d} 營收 {revenue.revenue:,}，"
                    f"年增率 {yoy}；來源：{revenue.source}，"
                    f"擷取時間（台灣）{format_taipei(revenue.fetched_at)}"
                )
            else:
                detail_blocks.append("- 月營收：目前無足夠數據判斷。")

            if related_findings:
                for finding in related_findings[:3]:
                    source_date = finding.source.published_at.isoformat() if finding.source.published_at else "日期不明"
                    detail_blocks.append(
                        f"- 風險/機會證據：{finding.risk_type.value}；{finding.evidence}；"
                        f"來源：{source_date} {finding.source.publisher or ''} {finding.source.title}"
                    )
                if len(related_findings) > 3:
                    detail_blocks.append(f"- 其餘 {len(related_findings) - 3} 筆證據已收斂於風險摘要與資料來源附錄。")
            elif related_documents:
                detail_blocks.append(f"- 新聞/研究證據：找到 {len(related_documents)} 筆相關文本，但未形成可歸因風險。")
            else:
                detail_blocks.append("- 新聞/研究證據：目前無足夠數據判斷。")
            detail_blocks.extend(
                self._render_wall_street_company_sections(
                    ticker,
                    name,
                    segment_name,
                    snapshot,
                    revenue,
                    ticker_metrics,
                    valuation,
                    peer_valuation_summary,
                    related_documents,
                    related_findings,
                    decision,
                    decision_reason,
                )
            )
            detail_blocks.append("")

        lines = [
            "### 個股速覽",
            REPORT_READING_SORT_NOTE,
            "",
            "| 股票 | 產業位置 | 最新可取得收盤價 | 追價風險標籤 | 月營收 | 目前估值位置 | 財務信心 | 證據狀態 |",
            "|---|---|---|---|---|---|---|---|",
            *overview_rows,
            "",
            "### 個股細節",
            *detail_blocks,
        ]
        return "\n".join(lines).strip()

    def _company_basic_intro(
        self,
        ticker: str,
        name: str,
        segment_name: str,
        company,
        related_documents: list[NewsDocument],
    ) -> list[str]:
        candidate = self._candidate_audit_by_ticker().get(ticker, {})
        aliases = [
            alias
            for alias in (getattr(company, "aliases", []) or [])
            if alias and alias not in {ticker, name}
        ]
        keywords = (
            list(getattr(company, "evidence_keywords", []) or [])
            or list(candidate.get("evidence_keywords") or [])
        )
        rationale = self._compact_text(candidate.get("rationale") or "", 120)
        if rationale:
            role_text = f"{rationale}。"
        else:
            role_text = "本報告只把它視為此主題中的可驗證研究對象，不直接推論為受惠股。"
        alias_text = "、".join(aliases[:4]) if aliases else "本次主要使用股票代號與公司名稱比對。"
        keyword_text = "、".join(str(keyword) for keyword in keywords[:6]) if keywords else "尚未設定固定關鍵字，主要依公司名稱、代號與來源文本比對。"
        filing_documents = [document for document in related_documents if self._is_company_filing_document(ticker, document)]
        filing_types = sorted(
            {
                self._news_document_filing_type(document) or "company_disclosure"
                for document in filing_documents
            }
        )
        publisher_count = len({document.source.publisher or "未知來源" for document in related_documents})
        filing_text = (
            f"已納入 {len(filing_documents)} 份公司公開文件（{', '.join(filing_types[:3])}）。"
            if filing_documents
            else "尚未取得可用公司公開文件。"
        )
        return [
            "#### 公司基本介紹",
            f"- 基本定位：{ticker} {name}，本報告歸類在「{segment_name}」。{role_text}",
            f"- 常見名稱/代號：{alias_text}",
            f"- 本主題關聯關鍵字：{keyword_text}",
            f"- 本次資料基礎：{filing_text}另有 {len(related_documents)} 筆公司相關文本、{publisher_count} 個來源供交叉檢查。",
        ]

    def _candidate_audit_by_ticker(self) -> dict[str, dict]:
        return {
            str(candidate.get("ticker")): candidate
            for candidate in self.whitelist.candidate_audit()
            if candidate.get("ticker")
        }

    def _render_wall_street_company_sections(
        self,
        ticker: str,
        name: str,
        segment_name: str,
        snapshot: MarketSnapshot | None,
        revenue: MonthlyRevenue | None,
        financial_metrics: list[FinancialMetric],
        valuation: ValuationMetric | None,
        peer_valuation_summary: dict[str, float | None],
        related_documents: list[NewsDocument],
        related_findings,
        decision: str,
        decision_reason: str,
    ) -> list[str]:
        financial_summary = self._financial_statement_summary(financial_metrics)
        valuation_summary = self._valuation_summary(valuation, peer_valuation_summary)
        evidence_summary = self._company_evidence_summary(related_documents, related_findings)
        filing_summary = self._company_filing_evidence_summary(related_documents)
        revenue_summary = self._company_revenue_summary(revenue)
        moat_score = self._moat_score(related_documents, related_findings, revenue, financial_summary)
        return [
            "",
            "#### 華爾街式完整分析框架",
            f"- 商業模式與收入來源：{name} 本次被歸類在「{segment_name}」。"
            f"{filing_summary}本系統會交叉使用主題文本、月營收、已揭露年度財報與估值資料判斷需求是否落到公司層級。{evidence_summary}",
            f"- 競爭優勢（護城河）：護城河初評 {moat_score}/10。"
            f"依據：{self._moat_reason(moat_score, related_documents, related_findings, revenue, financial_summary)}",
            f"- 產業趨勢：{self._trend_summary(related_documents, related_findings)}",
            f"- 財務健康狀況：{financial_summary['health']} {revenue_summary}",
            "- 關鍵風險：" + self._company_risk_summary(related_findings),
            f"- 與競爭對手的估值比較：{valuation_summary} 同業 EV/EBITDA、毛利率與成長率比較仍需補資料。",
            "- 未來多頭情境：若需求證據延續、月營收成長改善且風險訊號未升高，股價具備重新評價機會。",
            "- 未來空頭情境：若風險訊號增加、月營收轉弱或產業瓶頸影響出貨，應降低曝險或等待資料修復。",
            "- 目前基本情境：維持觀察，除非資料完整度與目前情境降值門檻同時通過，才進入小額分批研究。",
            f"- 未來 12-24 個月展望：{self._near_term_outlook(revenue, related_documents, related_findings)}",
            "",
            "#### 已揭露年度財務檢查",
            f"- 營收成長：{financial_summary['revenue_trend']}",
            f"- 淨利趨勢：{financial_summary['net_income_trend']}",
            f"- 自由現金流：{financial_summary['fcf_trend']}",
            f"- 利潤率：{financial_summary['margin_trend']}",
            f"- 負債水準：{financial_summary['debt_trend']}",
            f"- ROE：{financial_summary['roe_trend']}",
            f"- 財務體質判斷：{financial_summary['strength']}",
            "",
            "#### 競爭護城河",
            f"- 品牌影響力：{self._moat_factor_text('brand', related_documents, related_findings, revenue, financial_summary)}",
            f"- 網路效應：{self._moat_factor_text('network', related_documents, related_findings, revenue, financial_summary)}",
            f"- 轉換成本：{self._moat_factor_text('switching_cost', related_documents, related_findings, revenue, financial_summary)}",
            f"- 成本優勢：{self._moat_factor_text('cost', related_documents, related_findings, revenue, financial_summary)}",
            f"- 專利或獨家技術：{self._moat_factor_text('technology', related_documents, related_findings, revenue, financial_summary)}",
            f"- 護城河強度：{moat_score}/10。此分數只根據目前來源與月營收訊號，非完整同業研究。",
            "",
            "#### 估值分析",
            f"- P/E 與同業比較：{valuation_summary}",
            f"- DCF 估值：{self._dcf_proxy_text(financial_summary, valuation)}",
            f"- 產業平均估值：{self._industry_average_text(peer_valuation_summary)}",
            f"- 目前是否低估或高估：{self._valuation_conclusion(snapshot, valuation, peer_valuation_summary)}",
            "",
            "#### 未來成長假設",
            f"- 市場規模與產業成長率：{self._trend_summary(related_documents, related_findings)}",
            f"- 擴張機會與新產品：{self._growth_opportunity_text(related_documents, related_findings, revenue)}",
            "- AI 或技術優勢：若文本明確指向 AI 供應鏈受惠，可列為觀察點，但仍需訂單與財務驗證。",
            f"- 5-10 年潛在成長空間：{self._long_term_growth_text(financial_summary, revenue, related_documents)}",
            "",
            "#### 多空辯論",
            f"- 多頭分析師：{self._bull_case(revenue, related_documents)}",
            f"- 空頭分析師：{self._bear_case(related_findings)}",
            "- 中性結論：目前以資料完整度與風險門檻為準；缺少完整財報/估值時，不應只靠題材做重倉決策。",
            "",
            "#### 是否應該投資",
            f"- 短期展望（1 年內）：{self._near_term_outlook(revenue, related_documents, related_findings)}",
            f"- 長期展望（5 年以上）：{self._long_term_growth_text(financial_summary, revenue, related_documents)}",
            "- 關鍵催化因素：月營收加速、客戶/訂單驗證、產能瓶頸緩解、毛利率改善。",
            "- 主要風險：" + self._company_risk_summary(related_findings),
            f"- 本次操作結論：{decision}。理由：{decision_reason}；此結論沿用投資建議總表，不等於個人化買賣建議。",
        ]

    def _render_investment_recommendations(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "目前無足夠數據判斷。"

        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        peer_valuation_summary = self._peer_valuation_summary(list(valuations.values()))
        companies = {company.ticker: company for company in self.whitelist.companies()}
        ordered_tickers = self._ordered_tickers_for_reading(
            request,
            tickers,
            documents,
            findings,
            market_snapshots,
            monthly_revenues,
            financial_metrics,
            valuation_metrics,
            leading_signals,
        )
        lines = [
            "以下為非個人化研究建議；未納入投資人風險承受度、持股成本與資金配置，不構成個別買賣指令。",
            REPORT_READING_SORT_NOTE,
            "",
            "| 股票 | 最新可取得收盤價 | 追價風險標籤 | 建議 | 理由 | 單檔上限 | 來源 |",
            "|---|---|---|---|---|---:|---|",
        ]
        for ticker in ordered_tickers:
            company = companies.get(ticker)
            snapshot = snapshots.get(ticker)
            revenue = revenues.get(ticker)
            related_findings = self._related_findings(ticker, findings)
            related_documents = self._related_documents(ticker, documents)
            signal = (leading_signals or {}).get(ticker)
            estimate = self._estimate_potential(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                signal,
                metrics_by_ticker.get(ticker, []),
                valuations.get(ticker),
                peer_valuation_summary,
            )
            quality = self._data_quality_grade(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                metrics_by_ticker.get(ticker, []),
                valuations.get(ticker),
                financial_metrics is not None or valuation_metrics is not None,
                signal,
                self._company_filing_missing(ticker, documents),
                recent_source_days=request.lookback_days,
            )
            downside_gate = self._downside_gate(request)
            name = company.name if company else ticker
            rating = self._decision_label(estimate, quality, related_findings, downside_gate, signal)
            valuation_label = self._valuation_position_label(
                valuations.get(ticker),
                peer_valuation_summary,
                self._has_negative_profitability(metrics_by_ticker.get(ticker, [])),
            )
            current_price = self._current_price_text(snapshot)
            current_price_label = self._current_price_label(
                snapshot,
                estimate,
                quality,
                valuation_label,
                signal,
                rating,
                downside_gate,
            )
            rationale = self._decision_reason(
                rating,
                estimate,
                quality,
                related_findings,
                related_documents,
                downside_gate,
                request,
                signal,
            )

            max_position = self._max_position_amount(request)
            position_limit = f"約 {max_position:,} 元" if rating == "可小額分批研究" else "不適用 / 0 元"
            source = (
                f"{snapshot.trade_date.isoformat()} {snapshot.source} {ticker}"
                if snapshot
                else "目前無足夠數據判斷"
            )
            if revenue:
                source += f"；{revenue.revenue_date.isoformat()} {revenue.source} {ticker}"
            if related_documents:
                source += f"；代表性文本：{self._representative_sources(related_documents, limit=2)}"
            lines.append(
                self._table_row(
                    [f"{ticker} {name}", current_price, current_price_label, rating, rationale, position_limit, source]
                )
            )
        return "\n".join(lines)

    @staticmethod
    def _company_evidence_summary(related_documents: list[NewsDocument], related_findings) -> str:
        return report_company_narrative.company_evidence_summary(related_documents, related_findings)

    @staticmethod
    def _company_filing_evidence_summary(related_documents: list[NewsDocument]) -> str:
        return report_company_narrative.company_filing_evidence_summary(related_documents)

    @staticmethod
    def _company_revenue_summary(revenue: MonthlyRevenue | None) -> str:
        return report_company_narrative.company_revenue_summary(revenue)

    @staticmethod
    def _company_quick_take(
        snapshot: MarketSnapshot | None,
        revenue: MonthlyRevenue | None,
        financial_metrics: list[FinancialMetric],
        valuation: ValuationMetric | None,
        related_documents: list[NewsDocument],
        related_findings,
    ) -> str:
        return report_company_narrative.company_quick_take(
            snapshot,
            revenue,
            financial_metrics,
            valuation,
            related_documents,
            related_findings,
        )

    @staticmethod
    def _group_financial_metrics(metrics: list[FinancialMetric]) -> dict[str, list[FinancialMetric]]:
        return report_company_narrative.group_financial_metrics(metrics)

    @staticmethod
    def _financial_statement_summary(metrics: list[FinancialMetric]) -> dict[str, str]:
        return financial_statement_summary(metrics)

    @staticmethod
    def _metric_series(
        metrics: list[FinancialMetric],
        keywords: list[str],
        statement_types: set[str] | None = None,
        exclude_keywords: list[str] | None = None,
        annual_only: bool = False,
    ) -> dict[int, float]:
        return metric_series(
            metrics,
            keywords,
            statement_types=statement_types,
            exclude_keywords=exclude_keywords,
            annual_only=annual_only,
        )

    @staticmethod
    def _balance_sheet_total_series(
        metrics: list[FinancialMetric],
        metric_names: set[str],
        origin_names: set[str],
    ) -> dict[int, float]:
        return balance_sheet_total_series(metrics, metric_names, origin_names)

    @staticmethod
    def _series_trend_text(series: dict[int, float], label: str) -> str:
        return series_trend_text(series, label)

    @staticmethod
    def _fcf_trend_text(operating_cash: dict[int, float], capex: dict[int, float]) -> str:
        return fcf_trend_text(operating_cash, capex)

    @staticmethod
    def _margin_text(gross_profit: dict[int, float], net_income: dict[int, float], revenue: dict[int, float]) -> str:
        return margin_text(gross_profit, net_income, revenue)

    @staticmethod
    def _debt_text(liabilities: dict[int, float], equity: dict[int, float]) -> str:
        return debt_text(liabilities, equity)

    @staticmethod
    def _debt_equity_phrase(ratio: float) -> str:
        return debt_equity_phrase(ratio)

    @staticmethod
    def _roe_text(net_income: dict[int, float], equity: dict[int, float]) -> str:
        return roe_text(net_income, equity)

    @staticmethod
    def _financial_strength_text(
        revenue: dict[int, float],
        net_income: dict[int, float],
        liabilities: dict[int, float],
        equity: dict[int, float],
    ) -> str:
        return financial_strength_text(revenue, net_income, liabilities, equity)

    @staticmethod
    def _series_growth_pct(series: dict[int, float]) -> float | None:
        return series_growth_pct(series)

    @staticmethod
    def _series_period_text(series: dict[int, float]) -> str:
        return series_period_text(series)

    @staticmethod
    def _decline_risk_points(growth_pct: float, *, metric: str) -> int:
        return decline_risk_points(growth_pct, metric=metric)

    @staticmethod
    def _financial_valuation_assessment(
        financial_metrics: list[FinancialMetric] | None = None,
        valuation: ValuationMetric | None = None,
        peer_summary: dict[str, float | None] | None = None,
    ) -> dict:
        return financial_valuation_assessment(financial_metrics, valuation, peer_summary)

    @staticmethod
    def _peer_valuation_summary(valuations: list[ValuationMetric]) -> dict[str, float | None]:
        return peer_valuation_summary(valuations)

    @staticmethod
    def _valuation_summary(
        valuation: ValuationMetric | None,
        peer_summary: dict[str, float | None] | None = None,
    ) -> str:
        return report_company_narrative.valuation_summary(valuation, peer_summary)

    @staticmethod
    def _valuation_peer_comparison(
        valuation: ValuationMetric,
        peer_summary: dict[str, float | None],
    ) -> str:
        return report_company_narrative.valuation_peer_comparison(valuation, peer_summary)

    @staticmethod
    def _valuation_position_label(
        valuation: ValuationMetric | None,
        peer_summary: dict[str, float | None] | None = None,
        has_negative_profitability: bool = False,
    ) -> str:
        return valuation_position_label(valuation, peer_summary, has_negative_profitability)

    @staticmethod
    def _has_negative_profitability(metrics: list[FinancialMetric]) -> bool:
        return has_negative_profitability(metrics)

    @staticmethod
    def _sanitize_leading_signal_for_profitability(
        signal: LeadingSignal,
        has_negative_profitability: bool,
    ) -> LeadingSignal:
        return report_company_narrative.sanitize_leading_signal_for_profitability(
            signal,
            has_negative_profitability,
        )

    @staticmethod
    def _current_price_text(snapshot: MarketSnapshot | None) -> str:
        return report_decision_rules.current_price_text(snapshot)

    @staticmethod
    def _current_price_label(
        snapshot: MarketSnapshot | None,
        estimate: dict,
        quality: dict,
        valuation_label: str,
        leading_signal: LeadingSignal | None,
        decision: str,
        downside_gate: int,
    ) -> str:
        return report_decision_rules.current_price_label(
            snapshot,
            estimate,
            quality,
            valuation_label,
            leading_signal,
            decision,
            downside_gate,
        )

    @staticmethod
    def _financial_confidence_label(
        financial_metrics: list[FinancialMetric],
        valuation: ValuationMetric | None,
        revenue: MonthlyRevenue | None,
    ) -> str:
        return report_company_narrative.financial_confidence_label(
            financial_metrics,
            valuation,
            revenue,
        )

    @staticmethod
    def _company_matrix_reminder(
        estimate: dict,
        quality: dict,
        related_findings,
        valuation: ValuationMetric | None,
        peer_summary: dict[str, float | None] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        leading_signal: LeadingSignal | None = None,
    ) -> str:
        if quality.get("grade") != "supported":
            return "先補資料：" + "、".join(quality.get("missing", [])[:2])
        if leading_signal and leading_signal.direction == "偏空":
            return "等近況訊號修復"
        valuation_label = ReportGenerator._valuation_position_label(
            valuation,
            peer_summary,
            ReportGenerator._has_negative_profitability(financial_metrics or []),
        )
        if estimate["downside_pct"] > 5:
            return f"先追蹤目前情境降值分 {estimate['downside_pct']} 分"
        if "偏高" in valuation_label or "略高" in valuation_label:
            return f"{valuation_label}，分批觀察"
        if related_findings:
            return f"追蹤 {len(related_findings)} 筆歸因是否延續"
        if estimate["upside_pct"] > 10:
            return "題材與基本面可再深入"
        return "暫列觀察"

    @staticmethod
    def _valuation_conclusion(
        snapshot: MarketSnapshot | None,
        valuation: ValuationMetric | None,
        peer_summary: dict[str, float | None] | None = None,
    ) -> str:
        return report_company_narrative.valuation_conclusion(snapshot, valuation, peer_summary)

    @staticmethod
    def _company_market_summary(snapshot: MarketSnapshot | None) -> str:
        return report_company_narrative.company_market_summary(snapshot)

    def _company_risk_summary(self, related_findings) -> str:
        if not related_findings:
            return "未偵測到可歸因的重大風險；仍需持續追蹤新聞、月營收與官方文件。"
        topics = []
        for finding in related_findings[:3]:
            topics.append(self._sanitized_risk_topic_for_finding(finding))
        return "、".join(topics)

    @staticmethod
    def _trend_summary(related_documents: list[NewsDocument], related_findings) -> str:
        return report_company_narrative.trend_summary(related_documents, related_findings)

    @staticmethod
    def _near_term_outlook(revenue: MonthlyRevenue | None, related_documents: list[NewsDocument], related_findings) -> str:
        return report_company_narrative.near_term_outlook(
            revenue,
            related_documents,
            related_findings,
        )

    @staticmethod
    def _growth_opportunity_text(
        related_documents: list[NewsDocument],
        related_findings,
        revenue: MonthlyRevenue | None,
    ) -> str:
        return report_company_narrative.growth_opportunity_text(
            related_documents,
            related_findings,
            revenue,
        )

    @staticmethod
    def _long_term_growth_text(
        financial_summary: dict[str, str],
        revenue: MonthlyRevenue | None,
        related_documents: list[NewsDocument],
    ) -> str:
        return report_company_narrative.long_term_growth_text(
            financial_summary,
            revenue,
            related_documents,
        )

    @staticmethod
    def _dcf_proxy_text(financial_summary: dict[str, str], valuation: ValuationMetric | None) -> str:
        return report_company_narrative.dcf_proxy_text(financial_summary, valuation)

    @staticmethod
    def _industry_average_text(peer_summary: dict[str, float | None]) -> str:
        return report_company_narrative.industry_average_text(peer_summary)

    @staticmethod
    def _bull_case(revenue: MonthlyRevenue | None, related_documents: list[NewsDocument]) -> str:
        return report_company_narrative.bull_case(revenue, related_documents)

    @staticmethod
    def _bear_case(related_findings) -> str:
        return report_company_narrative.bear_case(related_findings)

    @staticmethod
    def _moat_score(
        related_documents: list[NewsDocument],
        related_findings,
        revenue: MonthlyRevenue | None,
        financial_summary: dict[str, str] | None = None,
    ) -> int:
        return report_company_narrative.moat_score(
            related_documents,
            related_findings,
            revenue,
            financial_summary,
        )

    @staticmethod
    def _moat_reason(
        score: int,
        related_documents: list[NewsDocument],
        related_findings,
        revenue: MonthlyRevenue | None,
        financial_summary: dict[str, str] | None = None,
    ) -> str:
        return report_company_narrative.moat_reason(
            score,
            related_documents,
            related_findings,
            revenue,
            financial_summary,
        )

    @staticmethod
    def _moat_factor_text(
        factor: str,
        related_documents: list[NewsDocument],
        related_findings,
        revenue: MonthlyRevenue | None,
        financial_summary: dict[str, str],
    ) -> str:
        return report_company_narrative.moat_factor_text(
            factor,
            related_documents,
            related_findings,
            revenue,
            financial_summary,
        )

    @staticmethod
    def _company_rating(
        snapshot: MarketSnapshot | None,
        revenue: MonthlyRevenue | None,
        related_documents: list[NewsDocument],
        related_findings,
    ) -> str:
        return report_company_narrative.company_rating(
            snapshot,
            revenue,
            related_documents,
            related_findings,
        )

    def _sanitized_risk_topic_for_finding(self, finding) -> str:
        return self._sanitize_risk_topic(
            finding.topic,
            [company.ticker for company in finding.related_companies],
        )

    def _sanitize_risk_topic(self, topic: str, tickers: list[str] | None = None) -> str:
        raw_parts = (
            str(topic or "")
            .replace("，", ",")
            .replace("、", ",")
            .replace("/", ",")
            .split(",")
        )
        parts = [part.strip() for part in raw_parts if part.strip()]
        if not parts:
            return "營運與供應鏈風險"
        allows_ai_infra = self._companies_allow_ai_infra_risk(tickers or [])
        sanitized = [
            part
            for part in parts
            if allows_ai_infra or not self._is_ai_infra_specific_risk_term(part)
        ]
        if sanitized:
            return ", ".join(dict.fromkeys(sanitized))
        return "營運與供應鏈風險"

    def _companies_allow_ai_infra_risk(self, tickers: list[str]) -> bool:
        if not tickers:
            return True
        return any(self._company_allows_ai_infra_risk(ticker) for ticker in tickers)

    def _company_allows_ai_infra_risk(self, ticker: str) -> bool:
        companies = {company.ticker: company for company in self.whitelist.companies()}
        company = companies.get(ticker)
        segment = self.whitelist.segment_for_ticker(ticker)
        context = " ".join(
            [
                company.name if company else "",
                " ".join(company.evidence_keywords) if company else "",
                segment.name if segment else "",
                segment.notes or "" if segment else "",
            ]
        ).lower()
        return any(term.lower() in context for term in AI_INFRA_CONTEXT_TERMS)

    @staticmethod
    def _is_ai_infra_specific_risk_term(term: str) -> bool:
        lowered = term.lower()
        return any(marker.lower() == lowered or marker.lower() in lowered for marker in AI_INFRA_RISK_TERMS)

    @staticmethod
    def _finding_scope_companies(finding, scope_tickers: set[str] | None = None) -> list:
        companies = list(finding.related_companies)
        if not scope_tickers:
            return companies
        return [company for company in companies if company.ticker in scope_tickers]

    def _risk_findings_for_scope(self, findings, tickers: list[str] | None = None) -> list:
        scope_tickers = set(tickers or [])
        if not scope_tickers:
            return list(findings)
        scoped = []
        for finding in findings:
            if self._finding_scope_companies(finding, scope_tickers):
                scoped.append(finding)
        return scoped

    def _render_risk_overview(self, findings, tickers: list[str] | None = None) -> str:
        scoped_findings = self._risk_findings_for_scope(findings, tickers)
        if not scoped_findings:
            return "目前無足夠數據判斷。"

        scope_tickers = set(tickers or [])
        topic_counts = Counter(self._sanitized_risk_topic_for_finding(finding) for finding in scoped_findings)
        company_counts: Counter[str] = Counter()
        for finding in scoped_findings:
            for company in self._finding_scope_companies(finding, scope_tickers):
                company_counts[f"{company.ticker} {company.name}"] += 1

        lines = [
            f"- 結構性瓶頸：{sum(1 for finding in scoped_findings if finding.risk_type == RiskType.structural_bottleneck)} 筆",
            f"- 短期波動：{sum(1 for finding in scoped_findings if finding.risk_type == RiskType.short_term_volatility)} 筆",
            f"- 機會/成長：{sum(1 for finding in scoped_findings if finding.risk_type == RiskType.opportunity_or_growth)} 筆",
            "- 主要歸因主題："
            + ("、".join(f"{topic}({count})" for topic, count in topic_counts.most_common(5)) or "目前無足夠數據判斷"),
            "- 受影響公司："
            + ("、".join(f"{company}({count})" for company, count in company_counts.most_common(5)) or "未明確對應公司"),
            "",
            "### 代表性證據",
        ]
        for finding in scoped_findings[:8]:
            source_date = finding.source.published_at.isoformat() if finding.source.published_at else "日期不明"
            companies = (
                ", ".join(f"{c.ticker} {c.name}" for c in self._finding_scope_companies(finding, scope_tickers))
                or "未明確對應公司"
            )
            topic = self._sanitized_risk_topic_for_finding(finding)
            lines.append(
                f"- {topic}：{companies}；來源：{source_date} "
                f"{finding.source.publisher or ''} {finding.source.title}"
            )
        if len(scoped_findings) > 8:
            lines.append(f"- 其餘 {len(scoped_findings) - 8} 筆歸因證據已保留於系統資料庫，不在主報告逐條展開。")
        return "\n".join(lines)

    def _render_scope(
        self,
        tickers: list[str],
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
    ) -> str:
        return report_scope_sections.render_scope(
            tickers,
            market_snapshots,
            monthly_revenues,
            whitelist_context=self.whitelist.as_prompt_context(),
        )

    @staticmethod
    def _render_revenue_check(tickers: list[str], monthly_revenues: list[MonthlyRevenue]) -> str:
        return report_scope_sections.render_revenue_check(tickers, monthly_revenues)

    def _render_appendix(
        self,
        llm_result: LLMResult,
        documents: list[NewsDocument],
        market_snapshots: list[MarketSnapshot],
        tickers: list[str] | None = None,
    ) -> str:
        lines = ["### AI 補充分析"]
        if llm_result.fallback:
            lines.append("模型補充分析未啟用；本報告目前改用可追溯來源與資料規則生成，需人工覆核。")
        else:
            lines.append(
                LLMSupplementValidator.render_markdown(
                    llm_result.text,
                    documents,
                    market_snapshots,
                    news_ticker_resolver=lambda document: [
                        match.ticker for match in self._document_matches(document)
                    ],
                    claim_ticker_resolver=lambda claim: [
                        match.ticker for match in self.mapper.match_text(claim)
                    ],
                )
            )

        lines.extend(["", "### 資料來源與時間戳記"])
        if documents:
            ordered_documents = self._ordered_source_documents(
                self._appendix_documents_for_tickers(documents, tickers)
            )
            for document in ordered_documents[:SOURCE_APPENDIX_LIMIT]:
                lines.append(self._source_reference_line(document))
            if len(ordered_documents) > SOURCE_APPENDIX_LIMIT:
                lines.append(
                    f"- 其餘 {len(ordered_documents) - SOURCE_APPENDIX_LIMIT} 筆來源已存入資料庫，"
                    f"本報告僅列前 {SOURCE_APPENDIX_LIMIT} 筆。"
                )
        else:
            lines.append("- 目前無足夠數據判斷。")

        lines.extend(["", "### 模型狀態", self._model_status(llm_result)])
        return "\n".join(lines)

    @staticmethod
    def _is_international_source(document: NewsDocument) -> bool:
        publisher = (document.source.publisher or "").lower()
        title = document.title.lower()
        url = (document.source.url or "").lower()
        international_markers = [
            "nvidia",
            "amd",
            "samsung",
            "arm newsroom",
            "cloudflare",
            "venturebeat",
            "the decoder",
            "siliconangle",
            "microsoft azure",
            "trendforce",
            "semiconductor today",
            "electronics weekly",
            "embedded",
            "eejournal",
            "electronic design",
            "robotics tomorrow",
            "manufacturing tomorrow",
            "power & beyond",
            "reuters",
            "bloomberg",
            "cnbc",
            "the information",
            "semianalysis",
            "center for a new american",
            "bessemer",
            "astute",
            "designnews",
            "wsj",
            "financial times",
            "ft.com",
        ]
        haystack = f"{publisher} {title} {url}"
        if any(marker in haystack for marker in international_markers):
            return True
        return "hl=en" in url or "ceid=us:en" in url

    def _document_matches(self, document: NewsDocument) -> list:
        cache = getattr(self, "_document_match_cache", None)
        if cache is None:
            cache = {}
            self._document_match_cache = cache
        key = (
            document.id or "",
            document.source.url or "",
            document.title,
            len(document.text or ""),
        )
        if key not in cache:
            metadata_matches = self._document_metadata_matches(document)
            cache[key] = metadata_matches or self.mapper.match_document(document)
        return cache[key]

    def _document_metadata_matches(self, document: NewsDocument) -> list[EntityMatch]:
        tickers = set(document.entity_tickers)
        if not tickers:
            return []
        matches = []
        for segment in self.whitelist.segments:
            for company in segment.companies:
                if company.ticker not in tickers:
                    continue
                matches.append(
                    EntityMatch(
                        ticker=company.ticker,
                        name=company.name,
                        segment_id=segment.id,
                        segment_name=segment.name,
                        matched_alias="metadata",
                    )
                )
        return matches

    def _related_documents(self, ticker: str, documents: list[NewsDocument]) -> list[NewsDocument]:
        documents = filter_formal_evidence_documents(documents)
        return [
            document
            for document in documents
            if any(match.ticker == ticker for match in self._document_matches(document))
        ]

    def _document_company_labels(self, document: NewsDocument) -> list[str]:
        try:
            return [f"{match.ticker} {match.name}" for match in self._document_matches(document)]
        except Exception:
            return []

    def _candidate_audit_evidence_counts(self) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {}
        for candidate in self.whitelist.candidate_audit():
            ticker = str(candidate.get("ticker") or "")
            if not ticker:
                continue
            counts[ticker] = {
                "evidence_count": int(candidate.get("evidence_count") or 0),
                "source_count": int(candidate.get("evidence_source_count") or 0),
            }
        return counts

    @staticmethod
    def _publisher_count(documents: list[NewsDocument]) -> int:
        return len(
            {
                document.source.publisher or document.source.url or document.title
                for document in documents
            }
        )

    def _render_beginner_portfolio_plan(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "目前無足夠數據判斷。"

        capital = request.investor_capital
        reserve = int(capital * request.cash_reserve_pct)
        deployable = capital - reserve
        max_position = self._max_position_amount(request)
        first_tranche = int(max_position * self._first_tranche_ratio(request))
        downside_gate = self._downside_gate(request)
        contexts = self._sort_decision_contexts(
            self._decision_contexts(
                request,
                tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            )
        )

        candidate_contexts = []
        allocation_candidates = []
        avoid_rows = []
        watch_rows = []
        for context in contexts:
            label = context["label"]
            snapshot = context.get("snapshot")
            revenue = context.get("revenue")
            related_documents = context.get("documents") or []
            related_findings = context.get("findings") or []
            signal = context.get("leading_signal")
            estimate = context["estimate"]
            decision = context["decision"]
            source = (
                f"{snapshot.trade_date.isoformat()} {snapshot.source}"
                if snapshot
                else "目前無足夠數據判斷"
            )
            if revenue:
                source += f"；{revenue.revenue_date.isoformat()} {revenue.source}"
            reason = self._decision_reason(
                decision,
                estimate,
                context["quality"],
                related_findings,
                related_documents,
                downside_gate,
                request,
                signal,
            )

            if decision == "可小額分批研究":
                allocation_candidates.append(
                    {
                        "label": label,
                        "upside_pct": estimate["upside_pct"],
                        "downside_pct": estimate["downside_pct"],
                        "source": source,
                    }
                )
                candidate_contexts.append(
                    {
                        "label": label,
                        "estimate": estimate,
                        "reason": reason,
                        "source": source,
                    }
                )
            elif decision == "避開 / 降低曝險":
                avoid_rows.append(
                    f"- {label}：避開或降低曝險。原因：目前情境降值分 {estimate['downside_pct']} 分，"
                    f"目前情境升值分 {estimate['upside_pct']} 分；{reason}來源：{source}。"
                )
            else:
                watch_rows.append(
                    f"- {label}：{decision}。原因：{reason}來源：{source}。"
                )

        allocation_amounts = self._allocation_amounts(allocation_candidates, deployable, first_tranche)
        allocation_amount_by_label = {
            candidate["label"]: amount
            for candidate, amount in zip(allocation_candidates, allocation_amounts)
        }
        candidate_rows = []
        for context in candidate_contexts:
            estimate = context["estimate"]
            allocation_amount = allocation_amount_by_label.get(context["label"], first_tranche)
            candidate_rows.append(
                f"- {context['label']}：可列小額分批研究。首筆約 {allocation_amount:,} 元（配置草案），"
                f"單檔上限約 {max_position:,} 元；目前情境升值分 {estimate['upside_pct']} 分，"
                f"目前情境降值分 {estimate['downside_pct']} 分。原因：{context['reason']}"
                f"來源：{context['source']}。"
            )

        lines = [
            f"資金設定：總資金 {capital:,} 元以內；建議保留現金約 {reserve:,} 元，"
            f"本輪可投入資金上限約 {deployable:,} 元。",
            f"投資人設定：{self._profile_label(request)}；單檔部位上限 {request.max_position_pct:.0%}，"
            f"首筆試單約單檔上限的 {self._first_tranche_ratio(request):.0%}，"
            f"目前情境降值觀察門檻 {downside_gate} 分。",
            "原則：先控風險再追報酬；同一題材不宜一次滿倉，且資料不足時不進入可研究名單。",
        ]
        lines.extend(["", "### 首筆配置草案"])
        lines.extend(
            self._render_allocation_plan(
                allocation_candidates,
                deployable,
                first_tranche,
            )
        )
        lines.extend(["", "### 可小額分批研究"])
        lines.extend(candidate_rows or ["目前沒有同時通過資料完整度、風險門檻與投資理由一致性檢查的標的。"])
        lines.extend(["", "### 避開 / 降低曝險"])
        lines.extend(avoid_rows or ["目前無明確高風險名單。"])
        lines.extend(["", "### 觀察名單"])
        lines.extend(watch_rows or ["目前無觀察名單。"])
        return "\n".join(lines)

    @staticmethod
    def _render_allocation_plan(
        candidates: list[dict],
        deployable: int,
        first_tranche: int,
    ) -> list[str]:
        return report_allocation.render_allocation_plan(candidates, deployable, first_tranche)

    @staticmethod
    def _allocation_amounts(
        candidates: list[dict],
        deployable: int,
        first_tranche: int,
    ) -> list[int]:
        return report_allocation.allocation_amounts(candidates, deployable, first_tranche)

    @staticmethod
    def _round_lot_amount(amount: int) -> int:
        return report_allocation.round_lot_amount(amount)

    @staticmethod
    def _round_down_lot_amount(amount: int) -> int:
        return report_allocation.round_down_lot_amount(amount)

    @staticmethod
    def _max_position_amount(request: ReportRequest) -> int:
        return report_allocation.max_position_amount(request)

    @staticmethod
    def _profile(request: ReportRequest) -> InvestorProfile:
        return report_allocation.profile(request)

    @staticmethod
    def _profile_label(request: ReportRequest) -> str:
        return report_allocation.profile_label(request)

    @staticmethod
    def _downside_gate(request: ReportRequest) -> int:
        return report_allocation.downside_gate(request)

    @staticmethod
    def _first_tranche_ratio(request: ReportRequest) -> float:
        return report_allocation.first_tranche_ratio(request)

    @staticmethod
    def _risk_warning_reason(estimate: dict) -> str:
        return report_decision_rules.risk_warning_reason(estimate)

    @staticmethod
    def _related_findings(ticker: str, findings) -> list:
        related = []
        seen: set[tuple[str, str, str, str]] = set()
        for finding in findings:
            if not any(match.ticker == ticker for match in finding.related_companies):
                continue
            key = (
                str(finding.risk_type),
                finding.topic,
                finding.source.title,
                finding.source.publisher or "",
            )
            if key in seen:
                continue
            seen.add(key)
            related.append(finding)
        return related

    def _company_filing_missing(self, ticker: str, documents: list[NewsDocument]) -> list[str]:
        companies = {company.ticker: company for company in self.whitelist.companies()}
        company = companies.get(ticker)
        company_name = company.name if company else ""
        high_quality_types: set[str] = set()

        for document in self._company_filing_documents_from_db(ticker):
            if filing_quality_score(document, ticker, company_name) >= 70:
                high_quality_types.add(document.document_type)

        for document in documents:
            if not self._is_company_filing_document(ticker, document):
                continue
            document_type = self._news_document_filing_type(document)
            if document_type and filing_quality_score(document, ticker, company_name) >= 70:
                high_quality_types.add(document_type)

        missing_required = [
            document_type for document_type in REQUIRED_CORE_DOCUMENT_TYPES if document_type not in high_quality_types
        ]
        if not missing_required:
            return []
        return ["缺公司公開文件（" + "、".join(self._filing_type_label(item) for item in missing_required) + "）"]

    @staticmethod
    def _filing_type_label(document_type: str) -> str:
        return report_company_narrative.filing_type_label(document_type)

    @staticmethod
    def _company_filing_documents_from_db(ticker: str):
        try:
            with session_scope() as session:
                return CompanyFilingRepository(session).latest_by_tickers([ticker], limit_per_ticker=8)
        except Exception:
            return []

    @staticmethod
    def _is_company_filing_document(ticker: str, document: NewsDocument) -> bool:
        return company_filing_owner_ticker(document) == ticker

    @staticmethod
    def _news_document_filing_type(document: NewsDocument) -> str | None:
        return report_company_narrative.news_document_filing_type(document)

    @staticmethod
    def _data_quality_grade(
        related_documents: list[NewsDocument],
        related_findings,
        snapshot: MarketSnapshot | None,
        monthly_revenue: MonthlyRevenue | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation: ValuationMetric | None = None,
        include_fundamentals: bool = False,
        leading_signal: LeadingSignal | None = None,
        company_filing_missing: list[str] | None = None,
        recent_source_days: int | None = None,
    ) -> dict:
        return report_potential.data_quality_grade(
            related_documents,
            related_findings,
            snapshot,
            monthly_revenue=monthly_revenue,
            financial_metrics=financial_metrics,
            valuation=valuation,
            include_fundamentals=include_fundamentals,
            leading_signal=leading_signal,
            company_filing_missing=company_filing_missing,
            recent_source_days=recent_source_days,
        )

    @staticmethod
    def _score_data_note(
        confidence_notes: list[str],
        financial_metrics: list[FinancialMetric],
        valuation: ValuationMetric | None,
    ) -> str:
        return report_potential.score_data_note(confidence_notes, financial_metrics, valuation)

    @staticmethod
    def _quality_label(grade: str) -> str:
        return report_potential.quality_label(grade)

    @staticmethod
    def _decision_label(
        estimate: dict,
        quality: dict,
        related_findings,
        downside_gate: int,
        leading_signal: LeadingSignal | None = None,
    ) -> str:
        return report_potential.decision_label(
            estimate,
            quality,
            related_findings,
            downside_gate,
            leading_signal,
        )

    @staticmethod
    def _decision_reason(
        rating: str,
        estimate: dict,
        quality: dict,
        related_findings,
        related_documents: list[NewsDocument],
        downside_gate: int,
        request: ReportRequest,
        leading_signal: LeadingSignal | None = None,
    ) -> str:
        if rating == "資料不足":
            return "缺少可驗證市場資料。"
        if rating == "避開 / 降低曝險":
            return ReportGenerator._risk_warning_reason(estimate)
        if rating == "觀察 / 等風險降低":
            financial = estimate.get("financial_assessment") or {}
            if financial.get("red_flag"):
                return (
                    "財務/估值紅旗尚未解除："
                    f"{financial.get('risk_summary', '需補財務與估值覆核')}；即使題材分數較高，也先列觀察。"
                )
            if leading_signal and leading_signal.direction == "偏空":
                return (
                    f"近況訊號偏空（{leading_signal.summary}），"
                    "先等量價、營收或估值訊號修復。"
                )
            if estimate.get("downside_pct", 0) > downside_gate:
                return (
                    f"目前情境降值分 {estimate['downside_pct']} 分已超過 {downside_gate} 分，"
                    f"依{ReportGenerator._profile_label(request)}設定先列觀察。"
                )
            if any(finding.risk_type == RiskType.structural_bottleneck for finding in related_findings):
                return ReportGenerator._structural_bottleneck_reason(related_findings)
            return "目前仍有風險條件未完全通過，先等新資料確認。"
        if rating == "觀察":
            if any(finding.risk_type == RiskType.short_term_volatility for finding in related_findings):
                return "主要證據偏短期波動，需追蹤後續訂單、庫存與出貨變化。"
            if related_documents:
                return "已有公司相關文本證據，但尚未形成足夠的目前情境升值/降值差距。"
            return "目前情境升值/降值差距不足，先觀察。"
        if rating == "觀察 / 資料待補":
            if any(finding.risk_type == RiskType.insufficient_data for finding in related_findings):
                return "模型或來源判定資料仍不足；補齊公司層級來源、財報與估值後再重新評估。"
            return "目前情境升值分高於 10，但資料層尚未完整；" + "、".join(quality["missing"]) + "。"
        if rating == "可小額分批研究":
            return (
                f"目前情境升值分高於 10 分，情境降值分未超過 {downside_gate} 分設定門檻，"
                "資料層完整，且未偵測到財務/估值紅旗。"
            )
        return "目前只有單日價量資料，缺少新聞、財報或法說證據支撐投資結論。"

    @staticmethod
    def _structural_bottleneck_reason(related_findings) -> str:
        bottlenecks = [
            finding for finding in related_findings if finding.risk_type == RiskType.structural_bottleneck
        ]
        if not bottlenecks:
            return "瓶頸或限制證據尚未釐清，先等待風險緩解，不列入本次配置。"

        evidence_labels = []
        seen: set[str] = set()
        for finding in bottlenecks:
            evidence = ReportGenerator._compact_text(
                finding.evidence or finding.topic or finding.source.title,
                max_chars=64,
            )
            if not evidence or evidence in seen:
                continue
            seen.add(evidence)
            source_parts = []
            if finding.source.published_at:
                source_parts.append(finding.source.published_at.isoformat())
            if finding.source.publisher:
                source_parts.append(finding.source.publisher)
            source_label = " ".join(source_parts)
            evidence_labels.append(f"{evidence}（{source_label}）" if source_label else evidence)
            if len(evidence_labels) >= 2:
                break

        if not evidence_labels:
            evidence_labels.append("來源指出供給、產能、技術轉換或成本限制仍需追蹤")
        return "瓶頸/限制證據：" + "；".join(evidence_labels) + "。先等待公司文件、月營收或法說確認風險緩解，不列入本次配置。"

    @staticmethod
    def _compact_text(value: object, max_chars: int = 80) -> str:
        return report_formatting.compact_text(value, max_chars=max_chars)

    @staticmethod
    def _table_cell(value: object) -> str:
        return report_formatting.table_cell(value)

    @staticmethod
    def _table_row(cells: list[object]) -> str:
        return report_formatting.table_row(cells)

    @staticmethod
    def _estimate_potential(
        related_documents: list[NewsDocument],
        related_findings,
        snapshot: MarketSnapshot | None,
        monthly_revenue: MonthlyRevenue | None = None,
        leading_signal: LeadingSignal | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation: ValuationMetric | None = None,
        peer_valuation_summary: dict[str, float | None] | None = None,
    ) -> dict:
        return report_potential.estimate_potential(
            related_documents,
            related_findings,
            snapshot,
            monthly_revenue=monthly_revenue,
            leading_signal=leading_signal,
            financial_metrics=financial_metrics,
            valuation=valuation,
            peer_valuation_summary=peer_valuation_summary,
        )

    @staticmethod
    def _early_potential_profile(
        related_documents: list[NewsDocument],
        monthly_revenue: MonthlyRevenue | None,
        leading_signal: LeadingSignal | None,
        upside_pct: int,
        downside_pct: int,
        snapshot: MarketSnapshot | None = None,
        document_count_override: int | None = None,
        publisher_count_override: int | None = None,
    ) -> dict:
        return report_potential.early_potential_profile(
            related_documents,
            monthly_revenue,
            leading_signal,
            upside_pct,
            downside_pct,
            snapshot=snapshot,
            document_count_override=document_count_override,
            publisher_count_override=publisher_count_override,
        )

    @staticmethod
    def _has_month_over_month_revenue_decline_text(documents: list[NewsDocument]) -> bool:
        return report_potential.has_month_over_month_revenue_decline_text(documents)

    @staticmethod
    def _month_over_month_revenue_caveat(
        documents: list[NewsDocument],
        monthly_revenue: MonthlyRevenue | None,
    ) -> str:
        return report_potential.month_over_month_revenue_caveat(documents, monthly_revenue)

    @staticmethod
    def _format_factors(factors: list[tuple[str, int]]) -> str:
        return report_potential.format_potential_factors(factors)

    @staticmethod
    def _upside_evidence_reason_prefix(
        document_count: int,
        positive_hits: int,
        opportunity_findings: int,
        evidence_score: int,
    ) -> str:
        return report_potential.upside_evidence_reason_prefix(
            document_count,
            positive_hits,
            opportunity_findings,
            evidence_score,
        )

    @staticmethod
    def _downside_evidence_reason_prefix(
        negative_hits: int,
        structural_findings: int,
        volatility_findings: int,
        news_risk_score: int,
    ) -> str:
        return report_potential.downside_evidence_reason_prefix(
            negative_hits,
            structural_findings,
            volatility_findings,
            news_risk_score,
        )

    @staticmethod
    def _revenue_reason(
        monthly_revenue: MonthlyRevenue | None,
        score_delta: int,
        positive: bool,
    ) -> str:
        return report_potential.revenue_reason(monthly_revenue, score_delta, positive)

    @staticmethod
    def _leading_signal_reason(leading_signal: LeadingSignal | None, positive: bool) -> str:
        return report_potential.leading_signal_reason(leading_signal, positive)

    @staticmethod
    def _leading_signal_factor_label(leading_signal: LeadingSignal, positive: bool) -> str:
        return report_potential.leading_signal_factor_label(leading_signal, positive)

    @staticmethod
    def _financial_assessment_reason(assessment: dict, positive: bool) -> str:
        return report_potential.financial_assessment_reason(assessment, positive)

    @staticmethod
    def _scoring_text_for_document(document: NewsDocument) -> str:
        return report_potential.scoring_text_for_document(document)

    @staticmethod
    def _summary(findings) -> str:
        if not findings:
            return "目前檢索證據不足，無法判斷 AI 產業鏈主要瓶頸。"
        structural_count = sum(1 for finding in findings if finding.risk_type == RiskType.structural_bottleneck)
        volatility_count = sum(1 for finding in findings if finding.risk_type == RiskType.short_term_volatility)
        opportunity_count = sum(1 for finding in findings if finding.risk_type == RiskType.opportunity_or_growth)
        return f"本次檢出 {structural_count} 項結構性瓶頸、{volatility_count} 項短期波動、{opportunity_count} 項機會/成長歸因。"

    @staticmethod
    def _format_evidence(documents: list[NewsDocument]) -> str:
        documents = filter_formal_evidence_documents(documents)
        if not documents:
            return "目前無足夠數據判斷。"
        return "\n".join(
            f"- {doc.source.published_at or '日期不明'} {doc.source.publisher or ''} {doc.title}: {doc.text[:500]}"
            for doc in documents
        )

    @staticmethod
    def _format_llm_evidence(
        documents: list[NewsDocument],
        ticker_label_resolver: Callable[[NewsDocument], list[str]] | None = None,
    ) -> str:
        return format_llm_evidence(documents, ticker_label_resolver)

    @staticmethod
    def _format_market_data(
        snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
    ) -> str:
        return format_market_data(snapshots, monthly_revenues)

    @staticmethod
    def _model_status(result: LLMResult) -> str:
        if result.fallback:
            return result.text
        return f"Gemini 已啟用；model={result.model}；key_pool_index={result.key_index}"
