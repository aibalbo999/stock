from __future__ import annotations

from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, NewsDocument, ValuationMetric
from app.services import report_potential
from app.services.leading_signals import LeadingSignal


class ReportGeneratorPotentialMixin:
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
