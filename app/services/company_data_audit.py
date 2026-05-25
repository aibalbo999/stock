from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time import now_taipei
from app.db.models import (
    AnalysisRun,
    FinancialMetricSnapshot,
    GeneratedReport,
    MonthlyRevenueSnapshot,
    NewsArticle,
    RiskClassificationCache,
    StockPriceSnapshot,
    ValuationMetricSnapshot,
)


PRICE_MIN_ROWS = 20
MONTHLY_REVENUE_MIN_ROWS = 12
FINANCIAL_MIN_PERIODS = 20
VALUATION_MIN_ROWS = 1
COMPANY_TEXT_MIN_COUNT = 2
COMPANY_FINDING_MIN_COUNT = 1
PRICE_MAX_AGE_DAYS = 7
MONTHLY_REVENUE_MAX_AGE_DAYS = 75
FINANCIAL_MAX_AGE_DAYS = 180
VALUATION_MAX_AGE_DAYS = 14

CORE_FINANCIAL_METRICS = {
    "營收": ("Revenue",),
    "淨利": ("TotalConsolidatedProfitForThePeriod", "NetIncome"),
    "毛利": ("GrossProfit",),
    "負債": ("Liabilities",),
    "權益": ("Equity", "EquityAttributableToOwnersOfParent"),
    "營業現金流": ("CashFlowsFromOperatingActivities", "NetCashInflowFromOperatingActivities"),
}


@dataclass(frozen=True)
class ReportCompanyCounts:
    text_count: int | None = None
    finding_count: int | None = None


def audit_report_company_data(session: Session, report_id: int) -> dict:
    report = session.get(GeneratedReport, report_id)
    if report is None:
        raise ValueError(f"report not found: {report_id}")
    tickers = _report_tickers(report)
    run_payload = _report_run_payload(session, report_id)
    return audit_company_data(session, tickers, markdown=report.markdown, run_payload=run_payload)


def audit_company_data(
    session: Session,
    tickers: list[str],
    markdown: str = "",
    run_payload: dict | None = None,
) -> dict:
    report_counts = parse_report_company_counts(markdown)
    rows = [_audit_one_ticker(session, ticker, report_counts.get(ticker)) for ticker in tickers]
    summary = {
        "total": len(rows),
        "sufficient": sum(1 for row in rows if row["status"] == "sufficient"),
        "partial": sum(1 for row in rows if row["status"] == "partial"),
        "insufficient": sum(1 for row in rows if row["status"] == "insufficient"),
    }
    return {
        "status": "sufficient" if summary["total"] and summary["sufficient"] == summary["total"] else "needs_attention",
        "summary": summary,
        "rows": rows,
        "thresholds": {
            "price_min_rows": PRICE_MIN_ROWS,
            "monthly_revenue_min_rows": MONTHLY_REVENUE_MIN_ROWS,
            "financial_min_periods": FINANCIAL_MIN_PERIODS,
            "valuation_min_rows": VALUATION_MIN_ROWS,
            "company_text_min_count": COMPANY_TEXT_MIN_COUNT,
            "company_finding_min_count": COMPANY_FINDING_MIN_COUNT,
        },
        "notes": _audit_notes(rows, run_payload or {}),
    }


def parse_report_company_counts(markdown: str) -> dict[str, ReportCompanyCounts]:
    counts: dict[str, ReportCompanyCounts] = {}
    current_ticker: str | None = None
    for line in markdown.splitlines():
        heading = re.match(r"^###\s+(\d{4})\s+", line.strip())
        if heading:
            current_ticker = heading.group(1)
            counts.setdefault(current_ticker, ReportCompanyCounts())
            continue
        if current_ticker is None:
            continue
        text_match = re.search(r"有\s+(\d+)\s+筆公司相關文本", line)
        finding_match = re.search(r"需追蹤\s+(\d+)\s+筆風險/機會歸因", line)
        if text_match or finding_match:
            previous = counts.get(current_ticker, ReportCompanyCounts())
            counts[current_ticker] = ReportCompanyCounts(
                text_count=int(text_match.group(1)) if text_match else previous.text_count,
                finding_count=int(finding_match.group(1)) if finding_match else previous.finding_count,
            )
    return counts


def _audit_one_ticker(
    session: Session,
    ticker: str,
    report_count: ReportCompanyCounts | None = None,
) -> dict:
    today = now_taipei().date()
    price = _price_stats(session, ticker)
    revenue = _monthly_revenue_stats(session, ticker)
    financial = _financial_stats(session, ticker)
    valuation = _valuation_stats(session, ticker)
    evidence = _evidence_stats(session, ticker, report_count)

    checks = {
        "price": _fresh_count_check(price["rows"], price["latest_date"], PRICE_MIN_ROWS, PRICE_MAX_AGE_DAYS, today),
        "monthly_revenue": _fresh_count_check(
            revenue["rows"],
            revenue["latest_date"],
            MONTHLY_REVENUE_MIN_ROWS,
            MONTHLY_REVENUE_MAX_AGE_DAYS,
            today,
        ),
        "financial_metrics": _financial_check(financial, today),
        "valuation": _fresh_count_check(
            valuation["rows"],
            valuation["latest_date"],
            VALUATION_MIN_ROWS,
            VALUATION_MAX_AGE_DAYS,
            today,
        ),
        "company_evidence": evidence["effective_text_count"] >= COMPANY_TEXT_MIN_COUNT,
        "risk_findings": evidence["effective_finding_count"] >= COMPANY_FINDING_MIN_COUNT,
        "persisted_company_evidence": evidence["db_text_count"] >= COMPANY_TEXT_MIN_COUNT,
        "persisted_risk_findings": evidence["db_finding_count"] >= COMPANY_FINDING_MIN_COUNT,
    }
    missing = _missing_reasons(checks, financial)
    if not missing:
        status = "sufficient"
    elif checks["price"] and checks["monthly_revenue"] and checks["financial_metrics"] and checks["valuation"]:
        status = "partial"
    else:
        status = "insufficient"
    return {
        "ticker": ticker,
        "status": status,
        "missing": missing,
        "checks": checks,
        "price": price,
        "monthly_revenue": revenue,
        "financial_metrics": financial,
        "valuation": valuation,
        "evidence": evidence,
    }


def _price_stats(session: Session, ticker: str) -> dict:
    return _dated_row_stats(session, StockPriceSnapshot, ticker, StockPriceSnapshot.trade_date)


def _monthly_revenue_stats(session: Session, ticker: str) -> dict:
    return _dated_row_stats(session, MonthlyRevenueSnapshot, ticker, MonthlyRevenueSnapshot.revenue_date)


def _valuation_stats(session: Session, ticker: str) -> dict:
    stats = _dated_row_stats(session, ValuationMetricSnapshot, ticker, ValuationMetricSnapshot.trade_date)
    latest = session.scalars(
        select(ValuationMetricSnapshot)
        .where(ValuationMetricSnapshot.ticker == ticker)
        .order_by(ValuationMetricSnapshot.trade_date.desc())
        .limit(1)
    ).first()
    stats["has_pe_or_pb"] = bool(latest and (latest.pe_ratio is not None or latest.pb_ratio is not None))
    return stats


def _financial_stats(session: Session, ticker: str) -> dict:
    rows = list(session.scalars(select(FinancialMetricSnapshot).where(FinancialMetricSnapshot.ticker == ticker)))
    periods = {row.report_date for row in rows}
    metrics = {row.metric for row in rows}
    missing_core = [
        label
        for label, aliases in CORE_FINANCIAL_METRICS.items()
        if not any(any(alias in metric for alias in aliases) for metric in metrics)
    ]
    latest_date = max(periods) if periods else None
    return {
        "rows": len(rows),
        "periods": len(periods),
        "latest_date": latest_date.isoformat() if latest_date else None,
        "missing_core_metrics": missing_core,
    }


def _evidence_stats(
    session: Session,
    ticker: str,
    report_count: ReportCompanyCounts | None,
) -> dict:
    articles = list(
        session.scalars(
            select(NewsArticle).where(NewsArticle.entity_matches_json.like(f"%{ticker}%"))
        )
    )
    document_ids = [article.id for article in articles]
    risk_count = 0
    if document_ids:
        risk_count = int(
            session.scalar(
                select(func.count())
                .select_from(RiskClassificationCache)
                .where(RiskClassificationCache.document_id.in_(document_ids))
            )
            or 0
        )
    db_text_count = len(articles)
    report_text_count = report_count.text_count if report_count else None
    report_finding_count = report_count.finding_count if report_count else None
    latest_article_date = max((article.published_at for article in articles if article.published_at), default=None)
    return {
        "db_text_count": db_text_count,
        "db_finding_count": risk_count,
        "db_publishers": len({article.publisher or article.url or article.title for article in articles}),
        "latest_db_article_date": latest_article_date.isoformat() if latest_article_date else None,
        "report_text_count": report_text_count,
        "report_finding_count": report_finding_count,
        "effective_text_count": max(db_text_count, report_text_count or 0),
        "effective_finding_count": max(risk_count, report_finding_count or 0),
    }


def _dated_row_stats(session: Session, model: Any, ticker: str, date_column: Any) -> dict:
    row = session.execute(
        select(func.count(), func.max(date_column)).where(model.ticker == ticker)
    ).one()
    latest_date = row[1]
    return {
        "rows": int(row[0] or 0),
        "latest_date": latest_date.isoformat() if latest_date else None,
    }


def _fresh_count_check(
    rows: int,
    latest_date_value: str | None,
    min_rows: int,
    max_age_days: int,
    today: date,
) -> bool:
    if rows < min_rows or latest_date_value is None:
        return False
    latest_date = date.fromisoformat(latest_date_value)
    age_days = (today - latest_date).days
    return 0 <= age_days <= max_age_days


def _financial_check(financial: dict, today: date) -> bool:
    if financial["periods"] < FINANCIAL_MIN_PERIODS or financial["missing_core_metrics"]:
        return False
    if not financial["latest_date"]:
        return False
    return (today - date.fromisoformat(financial["latest_date"])).days <= FINANCIAL_MAX_AGE_DAYS


def _missing_reasons(checks: dict[str, bool], financial: dict) -> list[str]:
    labels = {
        "price": "股價歷史不足或過舊",
        "monthly_revenue": "月營收不足或過舊",
        "financial_metrics": "五年財報不足、過舊或缺核心科目",
        "valuation": "估值資料不足或過舊",
        "company_evidence": "公司層級文本證據不足",
        "risk_findings": "公司層級 AI 風險/機會歸因不足",
        "persisted_company_evidence": "可稽核入庫公司文本不足",
        "persisted_risk_findings": "可稽核入庫 AI 歸因不足",
    }
    missing = [label for key, label in labels.items() if not checks[key]]
    if financial.get("missing_core_metrics"):
        missing.append("缺核心財報科目：" + "、".join(financial["missing_core_metrics"]))
    return missing


def _audit_notes(rows: list[dict], run_payload: dict) -> list[str]:
    notes = []
    has_report_only_evidence = any(
        row["evidence"]["report_text_count"]
        and row["evidence"]["report_text_count"] > row["evidence"]["db_text_count"]
        for row in rows
    )
    if has_report_only_evidence:
        notes.append("部分公司有報告內動態證據，但新聞入庫的公司對應不足；後續需修正 entity mapping 入庫流程。")
    if run_payload.get("source_audit"):
        notes.append("本審計同時檢查報告文字與資料庫快取；整體 source audit 不代表每檔公司都足夠。")
    return notes


def _report_tickers(report: GeneratedReport) -> list[str]:
    try:
        tickers = json.loads(report.tickers_json)
    except json.JSONDecodeError:
        return []
    return [str(ticker) for ticker in tickers if str(ticker).strip()]


def _report_run_payload(session: Session, report_id: int) -> dict:
    run = session.scalars(
        select(AnalysisRun)
        .where(AnalysisRun.report_id == report_id)
        .order_by(AnalysisRun.started_at.desc())
        .limit(1)
    ).first()
    if run is None:
        return {}
    try:
        payload = json.loads(run.payload_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
