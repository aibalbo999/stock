from __future__ import annotations

from datetime import timedelta

from app.core.time import now_taipei
from app.models.schemas import (
    FinancialMetric,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ValuationMetric,
)
from app.services.leading_signals import LeadingSignal
from app.services.report_quality import is_stale_market_data_source


def data_quality_grade_for(
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
    missing: list[str] = []
    has_company_filing = _has_company_filing(
        include_fundamentals,
        company_filing_missing,
    )
    _append_document_quality_gaps(missing, related_documents, related_findings, has_company_filing)
    _append_market_quality_gaps(missing, snapshot, monthly_revenue)
    _append_fundamental_quality_gaps(
        missing,
        include_fundamentals=include_fundamentals,
        financial_metrics=financial_metrics,
        valuation=valuation,
        leading_signal=leading_signal,
        company_filing_missing=company_filing_missing,
        related_documents=related_documents,
        recent_source_days=recent_source_days,
    )
    return {
        "grade": _quality_grade(missing, snapshot, monthly_revenue, financial_metrics, valuation),
        "missing": missing,
    }


def _has_company_filing(
    include_fundamentals: bool,
    company_filing_missing: list[str] | None,
) -> bool:
    return (
        include_fundamentals
        and company_filing_missing is not None
        and not company_filing_missing
    )


def _append_document_quality_gaps(
    missing: list[str],
    related_documents: list[NewsDocument],
    related_findings,
    has_company_filing: bool,
) -> None:
    has_topic_attribution = (
        bool(related_findings) or has_company_filing or len(related_documents) >= 2
    )
    if len(related_documents) < 2 and not has_company_filing:
        missing.append("公司文本不足")
    if not has_topic_attribution:
        missing.append("缺主題歸因")


def _append_market_quality_gaps(
    missing: list[str],
    snapshot: MarketSnapshot | None,
    monthly_revenue: MonthlyRevenue | None,
) -> None:
    if not snapshot:
        missing.append("缺股價")
    elif is_stale_market_data_source(snapshot.source):
        missing.append("股價為快取救援")
    if not monthly_revenue:
        missing.append("缺月營收")
    elif is_stale_market_data_source(monthly_revenue.source):
        missing.append("月營收為快取救援")


def _append_fundamental_quality_gaps(
    missing: list[str],
    *,
    include_fundamentals: bool,
    financial_metrics: list[FinancialMetric] | None,
    valuation: ValuationMetric | None,
    leading_signal: LeadingSignal | None,
    company_filing_missing: list[str] | None,
    related_documents: list[NewsDocument],
    recent_source_days: int | None,
) -> None:
    if not include_fundamentals:
        return
    _append_financial_metric_gaps(missing, financial_metrics)
    _append_valuation_gaps(missing, valuation)
    if leading_signal is not None and not leading_signal.has_signal_data:
        missing.append("缺近況訊號")
    _append_recent_source_gap(missing, related_documents, recent_source_days)
    missing.extend(company_filing_missing or [])


def _append_financial_metric_gaps(
    missing: list[str],
    financial_metrics: list[FinancialMetric] | None,
) -> None:
    if not financial_metrics:
        missing.append("缺已揭露年度財報")
    elif any(is_stale_market_data_source(metric.source) for metric in financial_metrics):
        missing.append("財報為快取救援")


def _append_valuation_gaps(
    missing: list[str],
    valuation: ValuationMetric | None,
) -> None:
    if not valuation:
        missing.append("缺估值")
    elif is_stale_market_data_source(valuation.source):
        missing.append("估值為快取救援")


def _append_recent_source_gap(
    missing: list[str],
    related_documents: list[NewsDocument],
    recent_source_days: int | None,
) -> None:
    if recent_source_days is None or not related_documents:
        return
    cutoff = now_taipei().date() - timedelta(days=recent_source_days)
    latest_related_date = max(
        (
            document.source.published_at
            for document in related_documents
            if document.source.published_at is not None
        ),
        default=None,
    )
    if latest_related_date is None or latest_related_date < cutoff:
        missing.append(f"缺近 {recent_source_days} 天公司文本")


def _quality_grade(
    missing: list[str],
    snapshot: MarketSnapshot | None,
    monthly_revenue: MonthlyRevenue | None,
    financial_metrics: list[FinancialMetric] | None,
    valuation: ValuationMetric | None,
) -> str:
    if not missing:
        return "supported"
    if snapshot and monthly_revenue and financial_metrics and valuation:
        return "partial"
    return "weak"


__all__ = ["data_quality_grade_for"]
