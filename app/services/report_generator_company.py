from __future__ import annotations

from app.models.schemas import (
    FinancialMetric,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ValuationMetric,
)
from app.services import report_company_narrative
from app.services.leading_signals import LeadingSignal


class ReportGeneratorCompanyNarrativeMixin:
    @staticmethod
    def _company_evidence_summary(related_documents: list[NewsDocument], related_findings) -> str:
        return report_company_narrative.company_evidence_summary(
            related_documents, related_findings
        )

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
    def _group_financial_metrics(
        metrics: list[FinancialMetric],
    ) -> dict[str, list[FinancialMetric]]:
        return report_company_narrative.group_financial_metrics(metrics)

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
    def _sanitize_leading_signal_for_profitability(
        signal: LeadingSignal,
        has_negative_profitability: bool,
    ) -> LeadingSignal:
        return report_company_narrative.sanitize_leading_signal_for_profitability(
            signal,
            has_negative_profitability,
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
    def _valuation_conclusion(
        snapshot: MarketSnapshot | None,
        valuation: ValuationMetric | None,
        peer_summary: dict[str, float | None] | None = None,
    ) -> str:
        return report_company_narrative.valuation_conclusion(snapshot, valuation, peer_summary)

    @staticmethod
    def _company_market_summary(snapshot: MarketSnapshot | None) -> str:
        return report_company_narrative.company_market_summary(snapshot)

    @staticmethod
    def _trend_summary(related_documents: list[NewsDocument], related_findings) -> str:
        return report_company_narrative.trend_summary(related_documents, related_findings)

    @staticmethod
    def _near_term_outlook(
        revenue: MonthlyRevenue | None, related_documents: list[NewsDocument], related_findings
    ) -> str:
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
    def _dcf_proxy_text(
        financial_summary: dict[str, str], valuation: ValuationMetric | None
    ) -> str:
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
