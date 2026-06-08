from __future__ import annotations

from datetime import date
from typing import Optional

from app.models.schemas import EntityMatch, FinancialMetric, RiskFinding, RiskType, Source


def make_finding(
    ticker: str,
    name: str,
    evidence: str,
    risk_type: RiskType = RiskType.short_term_volatility,
    *,
    topic: str = "測試主題",
    publisher: str = "測試新聞",
    published_at: date | None = None,
    segment_id: str = "test",
    segment_name: str = "測試產業",
    matched_alias: str | None = None,
) -> RiskFinding:
    return RiskFinding(
        risk_type=risk_type,
        topic=topic,
        evidence=evidence,
        source=Source(title=evidence, publisher=publisher, published_at=published_at or date(2026, 5, 22)),
        related_companies=[
            EntityMatch(
                ticker=ticker,
                name=name,
                segment_id=segment_id,
                segment_name=segment_name,
                matched_alias=matched_alias or name,
            )
        ],
    )


def make_financial_metrics(
    ticker: str,
    revenues: list[float],
    net_incomes: list[float],
    liabilities: Optional[list[float]] = None,
    equities: Optional[list[float]] = None,
) -> list[FinancialMetric]:
    years = list(range(2022, 2022 + len(revenues)))
    liabilities = liabilities or [100.0 for _ in years]
    equities = equities or [200.0 for _ in years]
    metrics: list[FinancialMetric] = []
    for year, revenue, net_income, liability, equity in zip(years, revenues, net_incomes, liabilities, equities):
        report_date = date(year, 3, 31)
        metrics.extend(
            [
                FinancialMetric(
                    ticker=ticker,
                    report_date=report_date,
                    statement_type="income_statement",
                    metric="營業收入",
                    value=revenue,
                    source="test",
                ),
                FinancialMetric(
                    ticker=ticker,
                    report_date=report_date,
                    statement_type="income_statement",
                    metric="本期淨利",
                    value=net_income,
                    source="test",
                ),
                FinancialMetric(
                    ticker=ticker,
                    report_date=report_date,
                    statement_type="balance_sheet",
                    metric="負債總額",
                    value=liability,
                    source="test",
                ),
                FinancialMetric(
                    ticker=ticker,
                    report_date=report_date,
                    statement_type="balance_sheet",
                    metric="權益總額",
                    value=equity,
                    source="test",
                ),
            ]
        )
    return metrics
