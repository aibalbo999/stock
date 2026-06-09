from __future__ import annotations

from app.models.schemas import (
    FinancialMetric,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ReportRequest,
    ValuationMetric,
)
from app.services import (
    report_action_checklist,
    report_company_matrix,
    report_executive_snapshot,
    report_investment_recommendations,
    report_monitoring_checklist,
)
from app.services.followup_actions import FollowUpActionPlanner, render_follow_up_actions_markdown
from app.services.leading_signals import LeadingSignal
from app.services.report_reading import REPORT_READING_SORT_NOTE


class ReportGeneratorDecisionViewsMixin:
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
