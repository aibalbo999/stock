from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    FinancialMetricSnapshot,
    MonthlyRevenueSnapshot,
    StockPriceSnapshot,
    ValuationMetricSnapshot,
)
from app.models.schemas import (
    FinancialMetric,
    MarketSnapshot,
    MonthlyRevenue,
    ValuationMetric,
)

__all__ = [
    "FinancialMetricRepository",
    "MarketRepository",
    "MonthlyRevenueRepository",
    "ValuationMetricRepository",
]


class MarketRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_snapshots(self, snapshots: list[MarketSnapshot]) -> list[StockPriceSnapshot]:
        rows: list[StockPriceSnapshot] = []
        for snapshot in snapshots:
            statement = select(StockPriceSnapshot).where(
                StockPriceSnapshot.ticker == snapshot.ticker,
                StockPriceSnapshot.trade_date == snapshot.trade_date,
            )
            row = self.session.scalars(statement).first()
            values = snapshot.model_dump()
            if row is None:
                row = StockPriceSnapshot(**values)
                self.session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            rows.append(row)
        self.session.flush()
        return rows

    def latest_by_tickers(self, tickers: list[str]) -> list[MarketSnapshot]:
        snapshots: list[MarketSnapshot] = []
        for ticker in tickers:
            statement = (
                select(StockPriceSnapshot)
                .where(StockPriceSnapshot.ticker == ticker)
                .order_by(StockPriceSnapshot.trade_date.desc())
                .limit(1)
            )
            row = self.session.scalars(statement).first()
            if row:
                snapshots.append(self._to_snapshot(row))
        return snapshots

    def latest_trade_date(self) -> date | None:
        statement = (
            select(StockPriceSnapshot.trade_date)
            .order_by(StockPriceSnapshot.trade_date.desc())
            .limit(1)
        )
        return self.session.scalars(statement).first()

    def history_by_tickers(
        self, tickers: list[str], limit: int = 80
    ) -> dict[str, list[MarketSnapshot]]:
        histories: dict[str, list[MarketSnapshot]] = {}
        for ticker in tickers:
            statement = (
                select(StockPriceSnapshot)
                .where(StockPriceSnapshot.ticker == ticker)
                .order_by(StockPriceSnapshot.trade_date.desc())
                .limit(limit)
            )
            rows = list(self.session.scalars(statement))
            histories[ticker] = [self._to_snapshot(row) for row in reversed(rows)]
        return histories

    @staticmethod
    def _to_snapshot(row: StockPriceSnapshot) -> MarketSnapshot:
        return MarketSnapshot(
            ticker=row.ticker,
            trade_date=row.trade_date,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            spread=row.spread,
            trading_volume=row.trading_volume,
            trading_money=row.trading_money,
            trading_turnover=row.trading_turnover,
            source=row.source,
            fetched_at=row.fetched_at,
        )


class MonthlyRevenueRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_revenues(self, revenues: list[MonthlyRevenue]) -> list[MonthlyRevenueSnapshot]:
        rows: list[MonthlyRevenueSnapshot] = []
        for revenue in revenues:
            statement = select(MonthlyRevenueSnapshot).where(
                MonthlyRevenueSnapshot.ticker == revenue.ticker,
                MonthlyRevenueSnapshot.revenue_date == revenue.revenue_date,
            )
            row = self.session.scalars(statement).first()
            values = revenue.model_dump(exclude={"yoy_pct"})
            if row is None:
                row = MonthlyRevenueSnapshot(**values)
                self.session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            rows.append(row)
        self.session.flush()
        return rows

    def latest_by_tickers(self, tickers: list[str]) -> list[MonthlyRevenue]:
        latest: list[MonthlyRevenue] = []
        for ticker in tickers:
            statement = (
                select(MonthlyRevenueSnapshot)
                .where(MonthlyRevenueSnapshot.ticker == ticker)
                .order_by(MonthlyRevenueSnapshot.revenue_date.desc())
                .limit(1)
            )
            row = self.session.scalars(statement).first()
            if row:
                latest.append(self._to_revenue(row, self._yoy_pct(row)))
        return latest

    def history_by_tickers(
        self, tickers: list[str], limit: int = 18
    ) -> dict[str, list[MonthlyRevenue]]:
        histories: dict[str, list[MonthlyRevenue]] = {}
        for ticker in tickers:
            statement = (
                select(MonthlyRevenueSnapshot)
                .where(MonthlyRevenueSnapshot.ticker == ticker)
                .order_by(MonthlyRevenueSnapshot.revenue_date.desc())
                .limit(limit)
            )
            rows = list(self.session.scalars(statement))
            histories[ticker] = [
                self._to_revenue(row, self._yoy_pct(row)) for row in reversed(rows)
            ]
        return histories

    def _yoy_pct(self, row: MonthlyRevenueSnapshot) -> float | None:
        previous = self.session.scalars(
            select(MonthlyRevenueSnapshot)
            .where(
                MonthlyRevenueSnapshot.ticker == row.ticker,
                MonthlyRevenueSnapshot.revenue_year == row.revenue_year - 1,
                MonthlyRevenueSnapshot.revenue_month == row.revenue_month,
            )
            .limit(1)
        ).first()
        if previous is None or previous.revenue <= 0:
            return None
        return round((row.revenue - previous.revenue) / previous.revenue * 100, 2)

    @staticmethod
    def _to_revenue(row: MonthlyRevenueSnapshot, yoy_pct: float | None = None) -> MonthlyRevenue:
        return MonthlyRevenue(
            ticker=row.ticker,
            revenue_date=row.revenue_date,
            revenue=row.revenue,
            revenue_year=row.revenue_year,
            revenue_month=row.revenue_month,
            yoy_pct=yoy_pct,
            source=row.source,
            fetched_at=row.fetched_at,
        )


class FinancialMetricRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_metrics(self, metrics: list[FinancialMetric]) -> list[FinancialMetricSnapshot]:
        rows: list[FinancialMetricSnapshot] = []
        for metric in metrics:
            statement = select(FinancialMetricSnapshot).where(
                FinancialMetricSnapshot.ticker == metric.ticker,
                FinancialMetricSnapshot.report_date == metric.report_date,
                FinancialMetricSnapshot.statement_type == metric.statement_type,
                FinancialMetricSnapshot.metric == metric.metric,
            )
            row = self.session.scalars(statement).first()
            values = metric.model_dump()
            if row is None:
                row = FinancialMetricSnapshot(**values)
                self.session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            rows.append(row)
        self.session.flush()
        return rows

    def by_tickers(self, tickers: list[str]) -> list[FinancialMetric]:
        if not tickers:
            return []
        statement = (
            select(FinancialMetricSnapshot)
            .where(FinancialMetricSnapshot.ticker.in_(tickers))
            .order_by(FinancialMetricSnapshot.report_date.desc())
        )
        return [self._to_metric(row) for row in self.session.scalars(statement)]

    @staticmethod
    def _to_metric(row: FinancialMetricSnapshot) -> FinancialMetric:
        return FinancialMetric(
            ticker=row.ticker,
            report_date=row.report_date,
            statement_type=row.statement_type,
            metric=row.metric,
            value=row.value,
            origin_name=row.origin_name,
            source=row.source,
            fetched_at=row.fetched_at,
        )


class ValuationMetricRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_valuations(self, valuations: list[ValuationMetric]) -> list[ValuationMetricSnapshot]:
        rows: list[ValuationMetricSnapshot] = []
        for valuation in valuations:
            statement = select(ValuationMetricSnapshot).where(
                ValuationMetricSnapshot.ticker == valuation.ticker,
                ValuationMetricSnapshot.trade_date == valuation.trade_date,
            )
            row = self.session.scalars(statement).first()
            values = valuation.model_dump()
            if row is None:
                row = ValuationMetricSnapshot(**values)
                self.session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            rows.append(row)
        self.session.flush()
        return rows

    def latest_by_tickers(self, tickers: list[str]) -> list[ValuationMetric]:
        latest: list[ValuationMetric] = []
        for ticker in tickers:
            statement = (
                select(ValuationMetricSnapshot)
                .where(ValuationMetricSnapshot.ticker == ticker)
                .order_by(ValuationMetricSnapshot.trade_date.desc())
                .limit(1)
            )
            row = self.session.scalars(statement).first()
            if row:
                latest.append(self._to_valuation(row))
        return latest

    @staticmethod
    def _to_valuation(row: ValuationMetricSnapshot) -> ValuationMetric:
        return ValuationMetric(
            ticker=row.ticker,
            trade_date=row.trade_date,
            pe_ratio=row.pe_ratio,
            pb_ratio=row.pb_ratio,
            dividend_yield=row.dividend_yield,
            source=row.source,
            fetched_at=row.fetched_at,
        )
