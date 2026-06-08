from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from app.models.schemas import (
    Company,
    FinancialMetric,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ReportRequest,
    ValuationMetric,
)
from app.services import report_formatting, report_potential
from app.services.leading_signals import LeadingSignal
from app.services.report_source_references import representative_sources


def render_early_potential_radar(
    *,
    request: ReportRequest,
    tickers: list[str],
    documents: list[NewsDocument],
    findings: Any,
    market_snapshots: list[MarketSnapshot],
    monthly_revenues: list[MonthlyRevenue] | None = None,
    leading_signals: dict[str, LeadingSignal] | None = None,
    financial_metrics: list[FinancialMetric] | None = None,
    valuation_metrics: list[ValuationMetric] | None = None,
    companies: Iterable[Company],
    candidate_audit: Iterable[dict],
    decision_contexts_resolver: Callable[..., list[dict]],
    related_documents_resolver: Callable[[str, list[NewsDocument]], list[NewsDocument]],
    related_findings_resolver: Callable[[str, Any], list],
) -> str:
    if not tickers:
        return "目前無足夠數據判斷。"
    snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
    revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
    companies_by_ticker = {company.ticker: company for company in companies}
    candidate_evidence = candidate_audit_evidence_counts(candidate_audit)
    contexts = {
        context["ticker"]: context
        for context in decision_contexts_resolver(
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
    }
    rows = []
    for ticker in tickers:
        context = contexts.get(ticker)
        if context and context["decision"] == "避開 / 降低曝險":
            continue
        related_documents = related_documents_resolver(ticker, documents)
        related_findings = related_findings_resolver(ticker, findings)
        signal = (leading_signals or {}).get(ticker)
        estimate = dict(context["estimate"]) if context else report_potential.estimate_potential(
            related_documents,
            related_findings,
            snapshots.get(ticker),
            revenues.get(ticker),
            signal,
        )
        audit_counts = candidate_evidence.get(ticker, {})
        estimate.update(
            report_potential.early_potential_profile(
                related_documents,
                revenues.get(ticker),
                signal,
                estimate["upside_pct"],
                estimate["downside_pct"],
                snapshots.get(ticker),
                document_count_override=max(
                    len(related_documents),
                    int(audit_counts.get("evidence_count") or 0),
                ),
                publisher_count_override=max(
                    publisher_count(related_documents),
                    int(audit_counts.get("source_count") or 0),
                ),
            )
        )
        if estimate["early_potential_score"] <= 0:
            continue
        if estimate["attention_label"] not in {"報導較少", "報導偏少"}:
            continue
        company = companies_by_ticker.get(ticker)
        decision_note = f"目前決策：{context['decision']}；" if context else ""
        rows.append(
            {
                "label": f"{ticker} {company.name if company else ticker}",
                "score": estimate["early_potential_score"],
                "attention": estimate["attention_label"],
                "upside": estimate["upside_pct"],
                "downside": estimate["downside_pct"],
                "reason": decision_note + estimate["early_potential_reason"],
                "source": representative_sources(related_documents, limit=2),
            }
        )
    rows.sort(key=lambda row: (-row["score"], row["downside"], -row["upside"]))
    lines = [
        "本段專門找「截至目前報導較少、但近況訊號轉強」的研究線索；已排除避開/降低曝險標的。報導較少不是利多，代表仍需更多來源、成交量與公司文件驗證。",
    ]
    if not rows:
        lines.append("")
        lines.append("目前沒有同時符合「報導較少」與「近況訊號轉強」的標的。")
        return "\n".join(lines)
    lines.extend(
        [
            "",
            "| 股票 | 早期線索分 | 截至目前報導熱度 | 目前情境升值分 | 目前情境降值分 | 為什麼可能還早 | 代表來源 |",
            "|---|---:|---|---:|---:|---|---|",
        ]
    )
    for row in rows[:8]:
        lines.append(
            report_formatting.table_row(
                [
                    row["label"],
                    str(row["score"]),
                    row["attention"],
                    f"{row['upside']} 分",
                    f"{row['downside']} 分",
                    row["reason"],
                    row["source"],
                ]
            )
        )
    return "\n".join(lines)


def candidate_audit_evidence_counts(candidate_audit: Iterable[dict]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for candidate in candidate_audit:
        ticker = str(candidate.get("ticker") or "")
        if not ticker:
            continue
        counts[ticker] = {
            "evidence_count": int(candidate.get("evidence_count") or 0),
            "source_count": int(candidate.get("evidence_source_count") or 0),
        }
    return counts


def publisher_count(documents: list[NewsDocument]) -> int:
    return len(
        {
            document.source.publisher or document.source.url or document.title
            for document in documents
        }
    )
