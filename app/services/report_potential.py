from __future__ import annotations

from app.models.schemas import (
    FinancialMetric,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ValuationMetric,
)
from app.services.leading_signals import LeadingSignal
from app.services.report_potential_decisions import decision_label_for as decision_label_for
from app.services.report_potential_estimation import (
    early_potential_profile as early_potential_profile,
    estimate_potential_for as estimate_potential_for,
)
from app.services.report_potential_quality import data_quality_grade_for as data_quality_grade_for
from app.services.report_potential_reasons import (
    downside_evidence_reason_prefix as downside_evidence_reason_prefix,
    financial_assessment_reason as financial_assessment_reason,
    format_potential_factors as format_potential_factors,
    has_month_over_month_revenue_decline_text as has_month_over_month_revenue_decline_text,
    leading_signal_factor_label as leading_signal_factor_label,
    leading_signal_reason as leading_signal_reason,
    month_over_month_revenue_caveat as month_over_month_revenue_caveat,
    revenue_reason as revenue_reason,
    scoring_text_for_document as scoring_text_for_document,
    upside_evidence_reason_prefix as upside_evidence_reason_prefix,
)


def data_quality_grade(
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
    return data_quality_grade_for(
        related_documents,
        related_findings,
        snapshot,
        monthly_revenue,
        financial_metrics,
        valuation,
        include_fundamentals,
        leading_signal,
        company_filing_missing,
        recent_source_days,
    )


def score_data_note(
    confidence_notes: list[str],
    financial_metrics: list[FinancialMetric],
    valuation: ValuationMetric | None,
) -> str:
    notes = list(confidence_notes)
    if financial_metrics:
        notes.append(f"財報 {len(financial_metrics)} 筆")
    else:
        notes.append("缺財報")
    if valuation:
        notes.append(f"估值 {valuation.trade_date.isoformat()}")
    else:
        notes.append("缺估值")
    return "；".join(notes) if notes else "完整"


def quality_label(grade: str) -> str:
    labels = {
        "supported": "完整",
        "partial": "待補",
        "weak": "不足",
    }
    return labels.get(grade, grade)


def decision_label(
    estimate: dict,
    quality: dict,
    related_findings,
    downside_gate: int,
    leading_signal: LeadingSignal | None = None,
) -> str:
    return decision_label_for(
        estimate,
        quality,
        related_findings,
        downside_gate,
        leading_signal,
    )


def estimate_potential(
    related_documents: list[NewsDocument],
    related_findings,
    snapshot: MarketSnapshot | None,
    monthly_revenue: MonthlyRevenue | None = None,
    leading_signal: LeadingSignal | None = None,
    financial_metrics: list[FinancialMetric] | None = None,
    valuation: ValuationMetric | None = None,
    peer_valuation_summary: dict[str, float | None] | None = None,
) -> dict:
    return estimate_potential_for(
        related_documents,
        related_findings,
        snapshot,
        monthly_revenue,
        leading_signal,
        financial_metrics,
        valuation,
        peer_valuation_summary,
    )


__all__ = [
    "data_quality_grade",
    "data_quality_grade_for",
    "decision_label",
    "decision_label_for",
    "downside_evidence_reason_prefix",
    "early_potential_profile",
    "estimate_potential",
    "estimate_potential_for",
    "financial_assessment_reason",
    "format_potential_factors",
    "has_month_over_month_revenue_decline_text",
    "leading_signal_factor_label",
    "leading_signal_reason",
    "month_over_month_revenue_caveat",
    "quality_label",
    "revenue_reason",
    "score_data_note",
    "scoring_text_for_document",
    "upside_evidence_reason_prefix",
]
