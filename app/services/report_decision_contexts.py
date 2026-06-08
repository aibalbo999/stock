from __future__ import annotations

from typing import Any

from app.models.schemas import (
    FinancialMetric,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ReportRequest,
    ValuationMetric,
)
from app.services.leading_signals import LeadingSignal


def build_decision_contexts(
    generator: Any,
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
    snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
    revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
    metrics_by_ticker = generator._group_financial_metrics(financial_metrics or [])
    valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
    peer_valuation_summary = generator._peer_valuation_summary(list(valuations.values()))
    companies = {company.ticker: company for company in generator.whitelist.companies()}
    downside_gate = generator._downside_gate(request)
    contexts = []
    for ticker in tickers:
        company = companies.get(ticker)
        related_documents = generator._related_documents(ticker, documents)
        related_findings = generator._related_findings(ticker, findings)
        snapshot = snapshots.get(ticker)
        revenue = revenues.get(ticker)
        signal = (leading_signals or {}).get(ticker)
        valuation = valuations.get(ticker)
        ticker_metrics = metrics_by_ticker.get(ticker, [])
        estimate = generator._estimate_potential(
            related_documents,
            related_findings,
            snapshot,
            revenue,
            signal,
            ticker_metrics,
            valuation,
            peer_valuation_summary,
        )
        quality = generator._data_quality_grade(
            related_documents,
            related_findings,
            snapshot,
            revenue,
            ticker_metrics,
            valuation,
            financial_metrics is not None or valuation_metrics is not None,
            signal,
            generator._company_filing_missing(ticker, documents),
            recent_source_days=request.lookback_days,
        )
        decision = generator._decision_label(estimate, quality, related_findings, downside_gate, signal)
        valuation_label = generator._valuation_position_label(
            valuation,
            peer_valuation_summary,
            generator._has_negative_profitability(ticker_metrics),
        )
        contexts.append(
            {
                "ticker": ticker,
                "name": company.name if company else ticker,
                "label": f"{ticker} {company.name if company else ticker}",
                "documents": related_documents,
                "findings": related_findings,
                "snapshot": snapshot,
                "revenue": revenue,
                "valuation": valuation,
                "valuation_label": valuation_label,
                "current_price": generator._current_price_text(snapshot),
                "current_price_label": generator._current_price_label(
                    snapshot,
                    estimate,
                    quality,
                    valuation_label,
                    signal,
                    decision,
                    downside_gate,
                ),
                "estimate": estimate,
                "leading_signal": signal,
                "quality": quality,
                "decision": decision,
            }
        )
    return contexts


def ordered_tickers_for_reading(
    generator: Any,
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
    contexts = build_decision_contexts(
        generator,
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
    return [context["ticker"] for context in generator._sort_decision_contexts(contexts)]
