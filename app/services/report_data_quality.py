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


def render_data_quality(
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
    company_filing_missing_resolver: Callable[[str, list[NewsDocument]], list[str]],
    recent_source_days: int | None = None,
) -> str:
    if not tickers:
        return "未形成可驗證股票範圍；本次報告只能保留主題觀察，不能產出個股投資判斷。"

    snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
    revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
    metrics_by_ticker = report_company_narrative.group_financial_metrics(financial_metrics or [])
    valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
    companies_by_ticker = {company.ticker: company for company in companies}
    include_fundamentals = financial_metrics is not None or valuation_metrics is not None
    strong = 0
    partial = 0
    weak = 0
    lines = [
        "本段檢查每檔股票是否同時具備新聞/RAG、主題歸因、股價、月營收、已揭露年度財報、估值與公司公開文件；資料不足時，系統會降低建議強度。",
        "",
        "| 股票 | 新聞/RAG | 主題歸因 | 股價 | 月營收 | 年度財報 | 估值 | 公司文件 | 近況訊號 | 判讀 |",
        "|---|---:|---:|---|---|---:|---|---|---|---|",
    ]
    for ticker in tickers:
        company = companies_by_ticker.get(ticker)
        related_documents = related_documents_resolver(ticker, documents)
        related_findings = related_findings_resolver(ticker, findings)
        has_snapshot = ticker in snapshots
        has_revenue = ticker in revenues
        ticker_metrics = metrics_by_ticker.get(ticker, [])
        valuation = valuations.get(ticker)
        signal = (leading_signals or {}).get(ticker)
        filing_missing = company_filing_missing_resolver(ticker, documents)
        quality = report_potential.data_quality_grade(
            related_documents,
            related_findings,
            snapshots.get(ticker),
            revenues.get(ticker),
            ticker_metrics,
            valuation,
            include_fundamentals,
            signal,
            filing_missing,
            recent_source_days=recent_source_days,
        )
        missing = quality["missing"]

        if not missing:
            verdict = "完整，可進入二次篩選"
            strong += 1
        elif quality["grade"] == "partial":
            verdict = "部分可用，僅列觀察：" + "、".join(missing)
            partial += 1
        else:
            verdict = "不足：" + "、".join(missing)
            weak += 1

        label = f"{ticker} {company.name if company else ticker}"
        price_label = snapshots[ticker].trade_date.isoformat() if has_snapshot else "缺"
        revenue_label = (
            f"{revenues[ticker].revenue_year}-{revenues[ticker].revenue_month:02d}"
            if has_revenue
            else "缺"
        )
        financial_label = str(len(ticker_metrics)) if ticker_metrics else "缺"
        valuation_label = valuation.trade_date.isoformat() if valuation else "缺"
        filing_label = "足夠" if not filing_missing else "缺"
        signal_label = signal.direction if signal and signal.has_signal_data else "缺"
        lines.append(
            report_formatting.table_row(
                [
                    label,
                    len(related_documents),
                    len(related_findings),
                    price_label,
                    revenue_label,
                    financial_label,
                    valuation_label,
                    filing_label,
                    signal_label,
                    verdict,
                ]
            )
        )

    lines.extend(
        [
            "",
            f"整體判讀：完整 {strong} 檔、部分可用 {partial} 檔、資料不足 {weak} 檔。",
        ]
    )
    if weak or partial:
        lines.append("投資結論會優先採用資料完整標的；資料不足標的不會只因單一題材或單一財務數字被列為優先買進。")
    return "\n".join(lines)
