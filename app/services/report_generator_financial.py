from __future__ import annotations

from app.models.schemas import (
    FinancialMetric,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ValuationMetric,
)
from app.services import report_company_narrative, report_decision_rules
from app.services.leading_signals import LeadingSignal
from app.services.report_financial_assessment import (
    decline_risk_points,
    financial_valuation_assessment,
    has_negative_profitability,
    peer_valuation_summary,
    series_growth_pct,
    series_period_text,
    valuation_position_label,
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


class ReportGeneratorFinancialMixin:
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
    def _margin_text(
        gross_profit: dict[int, float], net_income: dict[int, float], revenue: dict[int, float]
    ) -> str:
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
