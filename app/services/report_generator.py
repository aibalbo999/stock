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
from app.services.llm_client import LLMClient, LLMResult
from app.services.llm_analysis import LLMSupplementValidator
from app.services.leading_signals import LeadingSignal
from app.services.report_execution import report_execution_summary as report_execution_summary
from app.services.report_generator_allocation import ReportGeneratorAllocationMixin
from app.services.report_generator_company import ReportGeneratorCompanyNarrativeMixin
from app.services.report_generator_decision_risk import ReportGeneratorDecisionRiskMixin
from app.services.report_generator_decision_views import ReportGeneratorDecisionViewsMixin
from app.services.report_generator_document import ReportGeneratorDocumentMixin
from app.services.report_generator_financial import ReportGeneratorFinancialMixin
from app.services.report_generator_formatting import ReportGeneratorFormattingMixin
from app.services.report_generator_market_scope import ReportGeneratorMarketScopeMixin
from app.services.report_generator_potential import ReportGeneratorPotentialMixin
from app.services.report_generator_prompt_appendix import ReportGeneratorPromptAppendixMixin
from app.services.report_generator_report_sections import ReportGeneratorReportSectionsMixin
from app.services.report_integrity import ReportIntegrityError, assert_report_integrity
from app.services import (
    report_beginner_portfolio,
    report_company_analysis,
    report_credibility_check,
    report_decision_contexts,
    report_early_potential,
    report_evidence_retrieval,
    report_final_potential,
    report_generation_flow,
    report_leading_signal,
    report_investment_thesis,
    report_markdown_sections,
)
from app.services.report_reading import REPORT_READING_SORT_NOTE
from app.services.report_source_references import (
    downside_source_references,
    ordered_source_documents,
    representative_sources,
    source_reference_line,
)
from app.services.risk_analyzer import RiskAnalyzer
from app.services.whitelist import SupplyChainWhitelist


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
    ReportGeneratorMarketScopeMixin,
    ReportGeneratorDecisionViewsMixin,
    ReportGeneratorReportSectionsMixin,
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
