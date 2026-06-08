from __future__ import annotations

from app.db.session import session_scope
from app.models.schemas import (
    FinancialMetric,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ReportRequest,
    ReportResponse,
    ValuationMetric,
)
from app.rag.vector_store import VectorStore
from app.services.candidate_audit import render_candidate_audit_markdown
from app.services.entity_mapping import EntityMapper
from app.services.followup_actions import FollowUpActionPlanner, render_follow_up_actions_markdown
from app.services.llm_client import LLMClient, LLMResult
from app.services.llm_analysis import LLMSupplementValidator
from app.services.leading_signals import LeadingSignal
from app.services.report_execution import report_execution_summary as report_execution_summary
from app.services.report_generator_allocation import ReportGeneratorAllocationMixin
from app.services.report_generator_company import ReportGeneratorCompanyNarrativeMixin
from app.services.report_generator_decision_risk import ReportGeneratorDecisionRiskMixin
from app.services.report_generator_document import ReportGeneratorDocumentMixin
from app.services.report_generator_financial import ReportGeneratorFinancialMixin
from app.services.report_generator_formatting import ReportGeneratorFormattingMixin
from app.services.report_generator_potential import ReportGeneratorPotentialMixin
from app.services.report_generator_prompt_appendix import ReportGeneratorPromptAppendixMixin
from app.services.report_integrity import ReportIntegrityError, assert_report_integrity
from app.services import (
    report_action_checklist,
    report_beginner_portfolio,
    report_company_analysis,
    report_company_matrix,
    report_data_quality,
    report_credibility_check,
    report_decision_contexts,
    report_early_potential,
    report_evidence_retrieval,
    report_executive_snapshot,
    report_final_potential,
    report_generation_flow,
    report_leading_signal,
    report_investment_thesis,
    report_investment_recommendations,
    report_markdown_sections,
    report_market_snapshots,
    report_monitoring_checklist,
    report_notes,
    report_scope_sections,
    report_score_breakdown,
    report_source_coverage,
)
from app.services.report_source_references import (
    downside_source_references,
    ordered_source_documents,
    representative_sources,
    source_reference_line,
)
from app.services.risk_analyzer import RiskAnalyzer
from app.services.whitelist import SupplyChainWhitelist


REPORT_READING_SORT_NOTE = (
    "排序：先依判斷結果分組（可研究、觀察、待補、避開），"
    "同組再依最新可取得收盤價由高到低；缺股價者排在同組後段。"
)


class ReportExecutionError(ValueError):
    pass


class ReportGenerator(
    ReportGeneratorAllocationMixin,
    ReportGeneratorDocumentMixin,
    ReportGeneratorCompanyNarrativeMixin,
    ReportGeneratorFinancialMixin,
    ReportGeneratorFormattingMixin,
    ReportGeneratorPotentialMixin,
    ReportGeneratorDecisionRiskMixin,
    ReportGeneratorPromptAppendixMixin,
):
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

    def generate(
        self, request: ReportRequest, documents: list[NewsDocument] | None = None
    ) -> ReportResponse:
        return report_generation_flow.generate_report(
            self,
            request,
            documents,
            execution_error_cls=ReportExecutionError,
        )

    @staticmethod
    def _assert_report_integrity(
        markdown: str, whitelist: SupplyChainWhitelist | None = None
    ) -> None:
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
        return report_evidence_retrieval.retrieve_evidence(
            request,
            mapper=self.mapper,
            whitelist=self.whitelist,
            vector_store=self.vector_store,
            document_matcher=self._document_matches,
            session_scope_func=session_scope,
        )

    def _vector_search(
        self,
        query: str,
        target_tickers: list[str],
        target_aliases: dict[str, list[str]] | None = None,
    ) -> list[NewsDocument]:
        return report_evidence_retrieval.vector_search(
            query,
            self.vector_store,
            target_tickers,
            target_aliases,
        )

    def _target_aliases_by_ticker(self, tickers: list[str]) -> dict[str, list[str]]:
        return report_evidence_retrieval.target_aliases_by_ticker(tickers, self.whitelist)

    def _graph_rag_search_queries(self, request: ReportRequest, limit: int = 12) -> list[str]:
        return report_evidence_retrieval.graph_rag_search_queries(
            request,
            mapper=self.mapper,
            whitelist=self.whitelist,
            limit=limit,
        )

    def _graph_reasoning_context(self, request: ReportRequest, tickers: list[str]) -> str:
        self.last_graph_reasoning_plan = None
        context, plan = report_evidence_retrieval.graph_reasoning_context(
            request,
            tickers,
            whitelist=self.whitelist,
        )
        self.last_graph_reasoning_plan = plan
        return context

    @staticmethod
    def _graph_neighbor_search_terms(
        graph, ticker: str, node_by_ticker: dict, max_neighbors: int = 4
    ) -> list[str]:
        return report_evidence_retrieval.graph_neighbor_search_terms(
            graph,
            ticker,
            node_by_ticker,
            max_neighbors=max_neighbors,
        )

    @staticmethod
    def _append_search_query(queries: list[str], query: str, limit: int) -> None:
        report_evidence_retrieval.append_search_query(queries, query, limit)

    @staticmethod
    def _compact_search_terms(terms, max_terms: int = 18) -> list[str]:
        return report_evidence_retrieval.compact_search_terms(terms, max_terms=max_terms)

    @staticmethod
    def _dedupe_documents(documents: list[NewsDocument]) -> list[NewsDocument]:
        return report_evidence_retrieval.dedupe_documents(documents)

    def _rank_evidence_documents(
        self,
        request: ReportRequest,
        documents: list[NewsDocument],
    ) -> list[NewsDocument]:
        return report_evidence_retrieval.rank_evidence_documents(
            request,
            documents,
            mapper=self.mapper,
            whitelist=self.whitelist,
            document_matcher=self._document_matches,
        )

    def _latest_market_snapshots(self, tickers: list[str]) -> list[MarketSnapshot]:
        return report_market_snapshots.latest_market_snapshots(
            tickers,
            session_scope_func=session_scope,
        )

    def _latest_monthly_revenues(self, tickers: list[str]) -> list[MonthlyRevenue]:
        return report_market_snapshots.latest_monthly_revenues(
            tickers,
            session_scope_func=session_scope,
        )

    def _financial_metrics(self, tickers: list[str]) -> list[FinancialMetric]:
        return report_market_snapshots.financial_metrics(
            tickers,
            session_scope_func=session_scope,
        )

    def _latest_valuations(self, tickers: list[str]) -> list[ValuationMetric]:
        return report_market_snapshots.latest_valuations(
            tickers,
            session_scope_func=session_scope,
        )

    def _leading_signals(
        self,
        tickers: list[str],
        valuation_metrics: list[ValuationMetric],
    ) -> dict[str, LeadingSignal]:
        return report_market_snapshots.leading_signals(
            tickers,
            valuation_metrics,
            session_scope_func=session_scope,
        )

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
        return report_markdown_sections.render_markdown(
            self,
            request,
            documents,
            findings,
            tickers,
            llm_result,
            market_snapshots,
            monthly_revenues,
            financial_metrics,
            valuation_metrics,
            leading_signals,
        )

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
        return report_credibility_check.render_credibility_check(
            request=request,
            tickers=tickers,
            documents=documents,
            findings=findings,
            market_snapshots=market_snapshots,
            monthly_revenues=monthly_revenues,
            financial_metrics=financial_metrics,
            valuation_metrics=valuation_metrics,
            leading_signals=leading_signals,
            companies=self.whitelist.companies(),
            related_documents_resolver=self._related_documents,
            related_findings_resolver=self._related_findings,
            company_filing_missing_resolver=self._company_filing_missing,
        )

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
        return report_decision_contexts.build_decision_contexts(
            self,
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
        return report_decision_contexts.ordered_tickers_for_reading(
            self,
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
            return report_action_checklist.render_action_checklist([], self._downside_gate(request))

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
        return report_action_checklist.render_action_checklist(
            contexts, self._downside_gate(request)
        )

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
            return report_monitoring_checklist.render_monitoring_checklist(
                [], self._downside_gate(request)
            )
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
        return report_monitoring_checklist.render_monitoring_checklist(contexts, downside_gate)

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
        return report_notes.render_time_scope_note(
            request,
            market_snapshots,
            monthly_revenues,
            valuation_metrics,
        )

    @staticmethod
    def _render_decision_criteria_note(request: ReportRequest) -> str:
        return report_notes.render_decision_criteria_note(request)

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
        return report_executive_snapshot.render_executive_snapshot(
            contexts,
            request,
            REPORT_READING_SORT_NOTE,
        )

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
        return report_data_quality.render_data_quality(
            tickers=tickers,
            documents=documents,
            findings=findings,
            market_snapshots=market_snapshots,
            monthly_revenues=monthly_revenues,
            financial_metrics=financial_metrics,
            valuation_metrics=valuation_metrics,
            leading_signals=leading_signals,
            companies=self.whitelist.companies(),
            related_documents_resolver=self._related_documents,
            related_findings_resolver=self._related_findings,
            company_filing_missing_resolver=self._company_filing_missing,
            recent_source_days=request.lookback_days if request else None,
        )

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
        return report_score_breakdown.render_score_breakdown(
            tickers=tickers,
            documents=documents,
            findings=findings,
            market_snapshots=market_snapshots,
            monthly_revenues=monthly_revenues,
            financial_metrics=financial_metrics,
            valuation_metrics=valuation_metrics,
            leading_signals=leading_signals,
            companies=self.whitelist.companies(),
            related_documents_resolver=self._related_documents,
            related_findings_resolver=self._related_findings,
        )

    def _render_source_coverage(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
    ) -> str:
        return report_source_coverage.render_source_coverage(
            evidence_limit=request.evidence_limit,
            tickers=tickers,
            documents=documents,
            companies=self.whitelist.companies(),
            related_documents_resolver=self._related_documents,
        )

    def _render_candidate_audit(self, promoted_tickers: list[str]) -> str:
        return render_candidate_audit_markdown(self.whitelist.candidate_audit(), promoted_tickers)

    @staticmethod
    def _render_leading_signal_check(
        tickers: list[str],
        leading_signals: dict[str, LeadingSignal],
    ) -> str:
        return report_leading_signal.render_leading_signal_check(tickers, leading_signals)

    @staticmethod
    def _format_optional_pct(value: float | None) -> str:
        return report_leading_signal.format_optional_pct(value)

    @staticmethod
    def _format_optional_ratio(value: float | None) -> str:
        return report_leading_signal.format_optional_ratio(value)

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
        return report_early_potential.render_early_potential_radar(
            request=request,
            tickers=tickers,
            documents=documents,
            findings=findings,
            market_snapshots=market_snapshots,
            monthly_revenues=monthly_revenues,
            leading_signals=leading_signals,
            financial_metrics=financial_metrics,
            valuation_metrics=valuation_metrics,
            companies=self.whitelist.companies(),
            candidate_audit=self.whitelist.candidate_audit(),
            decision_contexts_resolver=self._decision_contexts,
            related_documents_resolver=self._related_documents,
            related_findings_resolver=self._related_findings,
        )

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
            return report_final_potential.render_final_potential_screen([])

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
        return report_final_potential.render_final_potential_screen(contexts)

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
            return report_company_matrix.render_company_comparison_matrix(
                [], {}, {}, REPORT_READING_SORT_NOTE
            )

        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        peer_valuation_summary = self._peer_valuation_summary(list(valuations.values()))
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
        return report_company_matrix.render_company_comparison_matrix(
            contexts,
            metrics_by_ticker,
            peer_valuation_summary,
            REPORT_READING_SORT_NOTE,
        )

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
            return report_investment_thesis.render_investment_thesis_map(
                [],
                request,
                REPORT_READING_SORT_NOTE,
                self._representative_sources,
                self._downside_source_references,
            )

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
        return report_investment_thesis.render_investment_thesis_map(
            contexts,
            request,
            REPORT_READING_SORT_NOTE,
            self._representative_sources,
            self._downside_source_references,
        )

    @staticmethod
    def _thesis_reason(context: dict, request: ReportRequest) -> str:
        return report_investment_thesis.thesis_reason(context, request)

    @staticmethod
    def _thesis_verification_items(
        quality: dict,
        findings,
        related_documents: list[NewsDocument],
    ) -> str:
        return report_investment_thesis.thesis_verification_items(
            quality, findings, related_documents
        )

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
        return report_company_analysis.render_company_analysis_section(
            self,
            tickers,
            documents,
            findings,
            market_snapshots,
            monthly_revenues,
            financial_metrics,
            valuation_metrics,
            request,
            leading_signals,
            reading_sort_note=REPORT_READING_SORT_NOTE,
        )

    def _candidate_audit_by_ticker(self) -> dict[str, dict]:
        return {
            str(candidate.get("ticker")): candidate
            for candidate in self.whitelist.candidate_audit()
            if candidate.get("ticker")
        }

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
        downside_gate = self._downside_gate(request)
        contexts = []
        for context in self._sort_decision_contexts(
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
            context = dict(context)
            context["rationale"] = self._decision_reason(
                context["decision"],
                context["estimate"],
                context["quality"],
                context.get("findings") or [],
                context.get("documents") or [],
                downside_gate,
                request,
                context.get("leading_signal"),
            )
            contexts.append(context)
        return report_investment_recommendations.render_investment_recommendations(
            contexts,
            request,
            REPORT_READING_SORT_NOTE,
            lambda related_documents: self._representative_sources(related_documents, limit=2),
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
        return report_company_matrix.company_matrix_reminder(
            estimate,
            quality,
            related_findings,
            valuation,
            peer_summary,
            financial_metrics,
            leading_signal,
        )

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
            return report_beginner_portfolio.render_beginner_portfolio_plan(
                [],
                request,
                self._decision_reason,
            )

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
        return report_beginner_portfolio.render_beginner_portfolio_plan(
            contexts,
            request,
            self._decision_reason,
        )
