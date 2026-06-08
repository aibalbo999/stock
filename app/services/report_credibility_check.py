from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import timedelta
from typing import Any

from app.core.time import now_taipei
from app.models.schemas import (
    Company,
    FinancialMetric,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ReportRequest,
    ValuationMetric,
)
from app.services import report_company_narrative, report_formatting, report_potential
from app.services.leading_signals import LeadingSignal


def publisher_label(document: NewsDocument) -> str:
    return document.source.publisher or document.source.url or document.title or "來源不明"


def latest_source_date_label(documents: list[NewsDocument]) -> str:
    latest_dates = [
        document.source.published_at
        for document in documents
        if document.source.published_at is not None
    ]
    return max(latest_dates).isoformat() if latest_dates else "日期不明"


def company_limitations(
    *,
    related_documents: list[NewsDocument],
    related_findings: list,
    related_publisher_count: int,
    has_snapshot: bool,
    has_revenue: bool,
    financial_metric_count: int,
    has_valuation: bool,
    filing_missing: list[str],
) -> list[str]:
    limitations = []
    if len(related_documents) < 2:
        limitations.append("公司文本少於 2 筆")
    if related_publisher_count < 2:
        limitations.append("來源家數少於 2")
    if not related_findings:
        limitations.append("缺少風險/機會歸因")
    if not has_snapshot:
        limitations.append("缺股價")
    if not has_revenue:
        limitations.append("缺月營收")
    if not financial_metric_count:
        limitations.append("缺已揭露年度財報")
    if not has_valuation:
        limitations.append("缺估值")
    if filing_missing:
        limitations.append("缺公司公開文件")
    return limitations


def credibility_label(
    quality: dict,
    related_documents: list[NewsDocument],
    related_findings: list,
    related_publisher_count: int,
) -> str:
    if quality["grade"] == "supported" and related_publisher_count >= 2 and related_findings:
        return "高"
    if quality["grade"] in {"supported", "partial"} or (
        len(related_documents) >= 2 and related_publisher_count >= 2
    ):
        return "中"
    return "低"


def render_credibility_check(
    *,
    request: ReportRequest,
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
) -> str:
    if not tickers:
        return "目前沒有形成可驗證股票範圍；本報告可信度不足，只能作為主題觀察。"

    publishers = {publisher_label(document) for document in documents}
    dated_documents = [document for document in documents if document.source.published_at is not None]
    cutoff = now_taipei().date() - timedelta(days=request.lookback_days)
    recent_documents = [
        document
        for document in dated_documents
        if document.source.published_at and document.source.published_at >= cutoff
    ]
    snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
    revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
    metrics_by_ticker = report_company_narrative.group_financial_metrics(financial_metrics or [])
    valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
    companies_by_ticker = {company.ticker: company for company in companies}
    include_fundamentals = financial_metrics is not None or valuation_metrics is not None

    company_rows = []
    counts = {"高": 0, "中": 0, "低": 0}
    for ticker in tickers:
        company = companies_by_ticker.get(ticker)
        related_documents = related_documents_resolver(ticker, documents)
        related_findings = related_findings_resolver(ticker, findings)
        related_publishers = {publisher_label(document) for document in related_documents}
        ticker_metrics = metrics_by_ticker.get(ticker, [])
        signal = (leading_signals or {}).get(ticker)
        filing_missing = company_filing_missing_resolver(ticker, documents)
        quality = report_potential.data_quality_grade(
            related_documents,
            related_findings,
            snapshots.get(ticker),
            revenues.get(ticker),
            ticker_metrics,
            valuations.get(ticker),
            include_fundamentals,
            signal,
            filing_missing,
            recent_source_days=request.lookback_days,
        )
        limitations = company_limitations(
            related_documents=related_documents,
            related_findings=related_findings,
            related_publisher_count=len(related_publishers),
            has_snapshot=ticker in snapshots,
            has_revenue=ticker in revenues,
            financial_metric_count=len(ticker_metrics),
            has_valuation=ticker in valuations,
            filing_missing=filing_missing,
        )
        credibility = credibility_label(
            quality,
            related_documents,
            related_findings,
            len(related_publishers),
        )
        counts[credibility] += 1
        label = f"{ticker} {company.name if company else ticker}"
        company_rows.append(
            report_formatting.table_row(
                [
                    label,
                    credibility,
                    f"{len(related_documents)} 筆 / {len(related_publishers)} 來源",
                    f"{len(related_findings)} 筆",
                    latest_source_date_label(related_documents),
                    "、".join(limitations[:5]) if limitations else "未發現重大資料缺口",
                ]
            )
        )

    date_coverage = f"{len(dated_documents)}/{len(documents)} 筆" if documents else "0/0 筆"
    recent_coverage = f"{len(recent_documents)}/{len(documents)} 筆" if documents else "0/0 筆"
    source_status = "可追溯" if documents else "不足"
    diversity_status = "多來源" if len(publishers) >= 3 else "偏少"
    date_status = "可判讀" if dated_documents else "不足"
    company_status = "可用" if counts["高"] or counts["中"] else "不足"
    lines = [
        "本段檢查正式報告的分析可信度；這不同於「候選公司審計」的入選支持度。若分析可信度不足，結論會降級為觀察或待補資料。",
        "",
        "| 檢查項目 | 狀態 | 本次證據 | 對投資判斷的影響 |",
        "|---|---|---|---|",
        f"| 可追溯來源 | {source_status} | 共 {len(documents)} 筆文本 | 沒有來源時只保留主題觀察，不產生買進研究。 |",
        f"| 來源多樣性 | {diversity_status} | {len(publishers)} 個發布者 | 來源過少時，避免被單一新聞或單一觀點誤導。 |",
        f"| 全體來源時間戳 | {date_status} | {date_coverage} 有日期；近 {request.lookback_days} 天 {recent_coverage} | 這是全報告證據池覆蓋率；個股仍需看下方最近來源日期。 |",
        f"| 公司層級分析完整度 | {company_status} | 高分析可信度 {counts['高']} 檔、中分析可信度 {counts['中']} 檔、低分析可信度 {counts['低']} 檔 | 只有題材但缺近期公司證據時，不列入可研究標的。 |",
        f"| 市場與財務資料 | 可檢查 | 股價 {len(snapshots)} 檔、月營收 {len(revenues)} 檔、估值 {len(valuations)} 檔 | 財務或估值缺口會限制投資理由強度。 |",
        f"| 風險/機會歸因 | {'可用' if findings else '不足'} | {len(findings)} 筆系統驗證後歸因 | 風險未歸因時，不把新聞熱度直接當投資理由。 |",
        "",
        "### 個股可信度核對",
        "| 股票 | 分析可信度 | 公司文本 | 歸因證據 | 最近來源日期 | 主要限制 |",
        "|---|---|---:|---:|---|---|",
        *company_rows,
        "",
        "### 分析可信度判讀規則",
        "- 高分析可信度：公司文本、來源家數、風險/機會歸因、股價、月營收、財報、估值、公司文件與近期公司文本大致齊備。",
        "- 中分析可信度：已有公司層級證據，但仍有財務、估值、官方文件或近期資料缺口。",
        "- 低分析可信度：文本、來源家數或公司層級歸因不足；只能觀察，不應形成買進研究。",
    ]
    return "\n".join(lines)
