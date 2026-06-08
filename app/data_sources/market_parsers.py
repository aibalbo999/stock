from __future__ import annotations

from calendar import monthrange
from datetime import date

from app.core.time import utc_now_naive
from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ValuationMetric


def row_to_snapshot(row: dict) -> MarketSnapshot:
    return MarketSnapshot(
        ticker=str(row.get("stock_id") or row.get("data_id")),
        trade_date=date.fromisoformat(row["date"]),
        open=float_or_none(row.get("open")),
        high=float_or_none(row.get("max")),
        low=float_or_none(row.get("min")),
        close=float_or_none(row.get("close")),
        spread=float_or_none(row.get("spread")),
        trading_volume=int_or_none(row.get("Trading_Volume")),
        trading_money=int_or_none(row.get("Trading_money")),
        trading_turnover=float_or_none(row.get("Trading_turnover")),
        fetched_at=utc_now_naive(),
    )


def twse_openapi_row_to_snapshot(row: dict, ticker: str, source: str) -> MarketSnapshot:
    return MarketSnapshot(
        ticker=str(row.get("Code") or ticker),
        trade_date=roc_date_to_date(row.get("Date")),
        open=float_or_none(row.get("OpeningPrice")),
        high=float_or_none(row.get("HighestPrice")),
        low=float_or_none(row.get("LowestPrice")),
        close=float_or_none(row.get("ClosingPrice")),
        spread=float_or_none(row.get("Change")),
        trading_volume=int_or_none(row.get("TradeVolume")),
        trading_money=int_or_none(row.get("TradeValue")),
        source=source,
        fetched_at=utc_now_naive(),
    )


def tpex_openapi_row_to_snapshot(row: dict, ticker: str, source: str) -> MarketSnapshot:
    return MarketSnapshot(
        ticker=str(row.get("SecuritiesCompanyCode") or ticker),
        trade_date=roc_date_to_date(row.get("Date")),
        open=float_or_none(row.get("Open")),
        high=float_or_none(row.get("High")),
        low=float_or_none(row.get("Low")),
        close=float_or_none(row.get("Close")),
        spread=float_or_none(row.get("Change")),
        trading_volume=int_or_none(row.get("TradingShares")),
        trading_money=int_or_none(row.get("TransactionAmount")),
        source=source,
        fetched_at=utc_now_naive(),
    )


def fugle_row_to_snapshot(row: dict, ticker: str) -> MarketSnapshot:
    return MarketSnapshot(
        ticker=str(row.get("symbol") or row.get("stock_id") or row.get("data_id") or ticker),
        trade_date=date.fromisoformat(row["date"]),
        open=float_or_none(row.get("open")),
        high=float_or_none(row.get("high")),
        low=float_or_none(row.get("low")),
        close=float_or_none(row.get("close")),
        spread=float_or_none(row.get("change") or row.get("spread")),
        trading_volume=int_or_none(row.get("volume")),
        trading_money=int_or_none(row.get("turnover")),
        source="Fugle historical candles",
        fetched_at=utc_now_naive(),
    )


def fugle_stats_row_to_snapshot(row: dict, ticker: str) -> MarketSnapshot:
    return MarketSnapshot(
        ticker=str(row.get("symbol") or ticker),
        trade_date=date.fromisoformat(row["date"]),
        open=float_or_none(row.get("openPrice")),
        high=float_or_none(row.get("highPrice")),
        low=float_or_none(row.get("lowPrice")),
        close=float_or_none(row.get("closePrice")),
        spread=float_or_none(row.get("change")),
        trading_volume=int_or_none(row.get("tradeVolume")),
        trading_money=int_or_none(row.get("tradeValue")),
        source="Fugle historical stats",
        fetched_at=utc_now_naive(),
    )


def row_to_monthly_revenue(row: dict) -> MonthlyRevenue:
    revenue_date = date.fromisoformat(row["date"])
    return MonthlyRevenue(
        ticker=str(row.get("stock_id") or row.get("data_id")),
        revenue_date=revenue_date,
        revenue=int_or_none(row.get("revenue")) or 0,
        revenue_year=int(row.get("revenue_year") or revenue_date.year),
        revenue_month=int(row.get("revenue_month") or revenue_date.month),
        fetched_at=utc_now_naive(),
    )


def official_openapi_row_to_monthly_revenue(row: dict, source: str) -> MonthlyRevenue:
    revenue_year_month = str(row.get("資料年月") or "")
    if len(revenue_year_month) < 5:
        revenue_date = roc_date_to_date(row.get("出表日期"))
        revenue_year = revenue_date.year
        revenue_month = revenue_date.month
    else:
        revenue_year = roc_year_to_ad(int(revenue_year_month[:-2]))
        revenue_month = int(revenue_year_month[-2:])
        revenue_date = date(
            revenue_year,
            revenue_month,
            monthrange(revenue_year, revenue_month)[1],
        )
    return MonthlyRevenue(
        ticker=str(row.get("公司代號")),
        revenue_date=revenue_date,
        revenue=int_or_none(row.get("營業收入-當月營收")) or 0,
        revenue_year=revenue_year,
        revenue_month=revenue_month,
        yoy_pct=float_or_none(row.get("營業收入-去年同月增減(%)")),
        source=source,
        fetched_at=utc_now_naive(),
    )


def row_to_financial_metric(row: dict, statement_type: str, source: str) -> FinancialMetric:
    return FinancialMetric(
        ticker=str(row.get("stock_id") or row.get("data_id")),
        report_date=date.fromisoformat(row["date"]),
        statement_type=statement_type,
        metric=str(row.get("type") or row.get("metric") or row.get("origin_name")),
        value=float(row.get("value")),
        origin_name=row.get("origin_name"),
        source=f"FinMind {source}",
        fetched_at=utc_now_naive(),
    )


def official_statement_metrics(
    row: dict,
    report_date: date,
    *,
    statement_type: str,
    metric_names: tuple[str, ...],
    source: str,
) -> list[FinancialMetric]:
    ticker = str(row.get("公司代號") or row.get("SecuritiesCompanyCode"))
    metrics: list[FinancialMetric] = []
    for metric_name in metric_names:
        value = float_or_none(row.get(metric_name))
        if value is None:
            continue
        metrics.append(
            FinancialMetric(
                ticker=ticker,
                report_date=report_date,
                statement_type=statement_type,
                metric=metric_name,
                value=value,
                origin_name=metric_name,
                source=source,
                fetched_at=utc_now_naive(),
            )
        )
    return metrics


def row_to_valuation_metric(row: dict) -> ValuationMetric:
    return ValuationMetric(
        ticker=str(row.get("stock_id") or row.get("data_id")),
        trade_date=date.fromisoformat(row["date"]),
        pe_ratio=float_or_none(
            row.get("PER") or row.get("pe_ratio") or row.get("PE")
        ),
        pb_ratio=float_or_none(
            row.get("PBR") or row.get("pb_ratio") or row.get("PB")
        ),
        dividend_yield=float_or_none(
            row.get("dividend_yield") or row.get("DividendYield")
        ),
        fetched_at=utc_now_naive(),
    )


def twse_openapi_row_to_valuation_metric(row: dict, ticker: str, source: str) -> ValuationMetric:
    return ValuationMetric(
        ticker=str(row.get("Code") or ticker),
        trade_date=roc_date_to_date(row.get("Date")),
        pe_ratio=float_or_none(row.get("PEratio")),
        pb_ratio=float_or_none(row.get("PBratio")),
        dividend_yield=float_or_none(row.get("DividendYield")),
        source=source,
        fetched_at=utc_now_naive(),
    )


def tpex_openapi_row_to_valuation_metric(row: dict, ticker: str, source: str) -> ValuationMetric:
    return ValuationMetric(
        ticker=str(row.get("SecuritiesCompanyCode") or ticker),
        trade_date=roc_date_to_date(row.get("Date")),
        pe_ratio=float_or_none(row.get("PriceEarningRatio")),
        pb_ratio=float_or_none(row.get("PriceBookRatio")),
        dividend_yield=float_or_none(row.get("YieldRatio")),
        source=source,
        fetched_at=utc_now_naive(),
    )


def official_statement_report_date(row: dict) -> date:
    year = int(row.get("年度") or row.get("Year"))
    season = int(row.get("季別") or row.get("Season"))
    ad_year = roc_year_to_ad(year)
    quarter_end_month = min(12, max(1, season * 3))
    return date(ad_year, quarter_end_month, monthrange(ad_year, quarter_end_month)[1])


def roc_date_to_date(value) -> date:
    raw = str(value or "").strip()
    if len(raw) != 7 or not raw.isdigit():
        return date.fromisoformat(raw)
    year = roc_year_to_ad(int(raw[:3]))
    return date(year, int(raw[3:5]), int(raw[5:7]))


def roc_year_to_ad(year: int) -> int:
    return year + 1911 if year < 1_000 else year


def float_or_none(value) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    return float(str(value).replace(",", "").replace("+", ""))


def int_or_none(value) -> int | None:
    if value in (None, "", "-", "--"):
        return None
    return int(float(str(value).replace(",", "").replace("+", "")))
