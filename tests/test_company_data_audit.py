import json
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base,
    CompanyFiling,
    FinancialMetricSnapshot,
    GeneratedReport,
    MonthlyRevenueSnapshot,
    NewsArticle,
    RiskClassificationCache,
    StockPriceSnapshot,
    ValuationMetricSnapshot,
)
from app.services.company_data_audit import audit_report_company_data, parse_report_company_counts


def test_parse_report_company_counts() -> None:
    markdown = """
## 個別公司分析
### 2330 台積電
- 個股結論摘要：有 26 筆公司相關文本、P/E 31.06；主要檢查點：需追蹤 14 筆風險/機會歸因。
### 3017 奇鋐
- 個股結論摘要：有 10 筆公司相關文本、月營收年增 71.62%、P/E 42.31；主要檢查點：需追蹤 5 筆風險/機會歸因。
"""

    counts = parse_report_company_counts(markdown)

    assert counts["2330"].text_count == 26
    assert counts["2330"].finding_count == 14
    assert counts["3017"].text_count == 10
    assert counts["3017"].finding_count == 5


def test_company_data_audit_flags_per_company_gaps() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        report = GeneratedReport(
            title="AI 產業鏈 自動分析報告",
            topic="AI 產業鏈",
            tickers_json=json.dumps(["2330", "9999"]),
            findings_json="[]",
            markdown="""
## 個別公司分析
### 2330 台積電
- 個股結論摘要：有 5 筆公司相關文本、P/E 31.06；主要檢查點：需追蹤 2 筆風險/機會歸因。
### 9999 缺資料
- 個股結論摘要：有 0 筆公司相關文本；主要檢查點：需追蹤 0 筆風險/機會歸因。
""",
        )
        session.add(report)
        session.flush()
        _seed_complete_market_data(session, "2330")
        session.commit()

        audit = audit_report_company_data(session, report.id)

    rows = {row["ticker"]: row for row in audit["rows"]}
    assert rows["2330"]["status"] == "sufficient"
    assert rows["2330"]["checks"]["company_filings"] is True
    assert rows["9999"]["status"] == "insufficient"
    assert "股價歷史不足或過舊" in rows["9999"]["missing"]
    assert "公司層級文本證據不足" in rows["9999"]["missing"]
    assert "公司原始公開文件不足" in rows["9999"]["missing"]


def _seed_complete_market_data(session, ticker: str) -> None:
    for index in range(20):
        day = 25 - min(index, 24)
        session.add(
            StockPriceSnapshot(
                ticker=ticker,
                trade_date=date(2026, 5, day),
                close=100 + index,
                trading_volume=1000,
            )
        )
    revenue_months = [
        (2025, 6),
        (2025, 7),
        (2025, 8),
        (2025, 9),
        (2025, 10),
        (2025, 11),
        (2025, 12),
        (2026, 1),
        (2026, 2),
        (2026, 3),
        (2026, 4),
        (2026, 5),
    ]
    for year, month in revenue_months:
        session.add(
            MonthlyRevenueSnapshot(
                ticker=ticker,
                revenue_date=date(year, month, 1),
                revenue=1000,
                revenue_year=year,
                revenue_month=month,
            )
        )
    core_metrics = [
        "Revenue",
        "TotalConsolidatedProfitForThePeriod",
        "GrossProfit",
        "Liabilities",
        "Equity",
        "CashFlowsFromOperatingActivities",
    ]
    for quarter in range(20):
        report_date = date(2021 + quarter // 4, [3, 6, 9, 12][quarter % 4], 28)
        for metric in core_metrics:
            session.add(
                FinancialMetricSnapshot(
                    ticker=ticker,
                    report_date=report_date,
                    statement_type="test",
                    metric=metric,
                    value=1000,
                    source="test",
                )
            )
    session.add(
        ValuationMetricSnapshot(
            ticker=ticker,
            trade_date=date(2026, 5, 25),
            pe_ratio=20,
            pb_ratio=3,
        )
    )
    session.add(
        CompanyFiling(
            id=f"{ticker}-annual-report",
            ticker=ticker,
            company_name="測試公司",
            document_type="annual_report",
            title=f"{ticker} 年報",
            text="公司年報揭露主要產品、營收來源與風險因素。",
            publisher="公司 IR",
            published_at=date(2026, 5, 1),
        )
    )
    for index in range(2):
        document_id = f"{ticker}-doc-{index}"
        session.add(
            NewsArticle(
                id=document_id,
                title=f"{ticker} AI server evidence {index}",
                text="AI server demand evidence",
                publisher=f"publisher-{index}",
                published_at=date(2026, 5, 20 + index),
                entity_matches_json=json.dumps([{"ticker": ticker}]),
            )
        )
        session.add(
            RiskClassificationCache(
                document_id=document_id,
                topic_hash=f"hash-{index}",
                classification="opportunity_or_growth",
                topic="AI 產業鏈",
                evidence="AI server demand evidence",
                confidence=0.9,
                keywords_json="[]",
            )
        )
