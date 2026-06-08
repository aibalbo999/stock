from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from app.models.schemas import (
    Company,
    FinancialMetric,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ValuationMetric,
)
from app.services import report_company_narrative, report_formatting, report_potential
from app.services.leading_signals import LeadingSignal
from app.services.report_financial_assessment import peer_valuation_summary


def render_score_breakdown(
    *,
    tickers: list[str],
    documents: list[NewsDocument],
    findings: Any,
    market_snapshots: list[MarketSnapshot],
    monthly_revenues: list[MonthlyRevenue] | None = None,
    financial_metrics: list[FinancialMetric] | None = None,
    valuation_metrics: list[ValuationMetric] | None = None,
    leading_signals: dict[str, LeadingSignal] | None = None,
    companies: Iterable[Company],
    related_documents_resolver: Callable[[str, list[NewsDocument]], list[NewsDocument]],
    related_findings_resolver: Callable[[str, Any], list],
) -> str:
    if not tickers:
        return "目前無足夠數據判斷。"

    snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
    revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
    metrics_by_ticker = report_company_narrative.group_financial_metrics(financial_metrics or [])
    valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
    peer_summary = peer_valuation_summary(list(valuations.values()))
    companies_by_ticker = {company.ticker: company for company in companies}
    lines = [
        "此段拆解研究分級來源；分數是排序與風險控管用途，不代表預期報酬率。",
        "",
        "| 股票 | 目前情境升值分 | 目前情境降值分 | 主要加分 | 主要風險 | 資料提醒 |",
        "|---|---:|---:|---|---|---|",
    ]
    for ticker in tickers:
        company = companies_by_ticker.get(ticker)
        label = f"{ticker} {company.name if company else ticker}"
        related_documents = related_documents_resolver(ticker, documents)
        related_findings = related_findings_resolver(ticker, findings)
        ticker_metrics = metrics_by_ticker.get(ticker, [])
        valuation = valuations.get(ticker)
        estimate = report_potential.estimate_potential(
            related_documents,
            related_findings,
            snapshots.get(ticker),
            monthly_revenue=revenues.get(ticker),
            leading_signal=(leading_signals or {}).get(ticker),
            financial_metrics=ticker_metrics,
            valuation=valuation,
            peer_valuation_summary=peer_summary,
        )
        lines.append(
            report_formatting.table_row(
                [
                    label,
                    f"{estimate['upside_pct']} 分",
                    f"{estimate['downside_pct']} 分",
                    report_potential.format_potential_factors(estimate["upside_factors"]),
                    report_potential.format_potential_factors(estimate["downside_factors"]),
                    report_potential.score_data_note(
                        estimate["confidence_notes"],
                        ticker_metrics,
                        valuation,
                    ),
                ]
            )
        )
    return "\n".join(lines)
