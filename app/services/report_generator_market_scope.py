from __future__ import annotations

from app.db.session import session_scope
from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ValuationMetric
from app.services import report_market_snapshots, report_scope_sections
from app.services.leading_signals import LeadingSignal


class ReportGeneratorMarketScopeMixin:
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
