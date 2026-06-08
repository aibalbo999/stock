from __future__ import annotations

from app.models.schemas import (
    FinancialMetric,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ReportRequest,
    ValuationMetric,
)
from app.services import report_data_quality, report_notes, report_score_breakdown, report_source_coverage
from app.services.leading_signals import LeadingSignal


class ReportGeneratorReportSectionsMixin:
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
