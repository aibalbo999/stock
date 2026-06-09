from __future__ import annotations

from app.models.schemas import FinancialMetric, ValuationMetric
from app.services.report_financial_assessment_rules import (
    decline_risk_points as decline_risk_points,
    financial_valuation_assessment_payload as financial_valuation_assessment_payload,
    has_negative_profitability as has_negative_profitability,
    peer_valuation_summary as peer_valuation_summary,
    series_growth_pct as series_growth_pct,
    series_period_text as series_period_text,
)
from app.services.report_valuation_position import (
    valuation_position_label_for as valuation_position_label_for,
)


def financial_valuation_assessment(
    financial_metrics: list[FinancialMetric] | None = None,
    valuation: ValuationMetric | None = None,
    peer_summary: dict[str, float | None] | None = None,
) -> dict:
    return financial_valuation_assessment_payload(financial_metrics, valuation, peer_summary)


def valuation_position_label(
    valuation: ValuationMetric | None,
    peer_summary: dict[str, float | None] | None = None,
    has_negative_profitability: bool = False,
) -> str:
    return valuation_position_label_for(valuation, peer_summary, has_negative_profitability)


__all__ = [
    "decline_risk_points",
    "financial_valuation_assessment",
    "financial_valuation_assessment_payload",
    "has_negative_profitability",
    "peer_valuation_summary",
    "series_growth_pct",
    "series_period_text",
    "valuation_position_label",
    "valuation_position_label_for",
]
