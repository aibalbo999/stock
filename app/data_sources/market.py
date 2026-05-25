from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime

import httpx

from app.core.config import get_settings
from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ValuationMetric


@dataclass(frozen=True)
class MarketFetchError:
    ticker: str
    dataset: str
    error: str

    def model_dump(self) -> dict:
        return {
            "ticker": self.ticker,
            "dataset": self.dataset,
            "error": self.error,
        }


class MarketDataClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.timeout = httpx.Timeout(20.0, connect=8.0)
        self.concurrency = 5

    async def get_price_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[MarketSnapshot]:
        params = {
            "dataset": "TaiwanStockPrice",
            "data_id": ticker,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
        headers = {}
        if self.settings.finmind_token:
            headers["Authorization"] = f"Bearer {self.settings.finmind_token}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                "https://api.finmindtrade.com/api/v4/data",
                params=params,
                headers=headers,
            )
            response.raise_for_status()

        payload = response.json()
        rows = payload.get("data", [])
        return [self._row_to_snapshot(row) for row in rows]

    async def get_latest_snapshots(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> list[MarketSnapshot]:
        snapshots, _errors = await self.get_latest_snapshots_with_errors(tickers, start_date, end_date)
        return snapshots

    async def get_latest_snapshots_with_errors(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> tuple[list[MarketSnapshot], list[MarketFetchError]]:
        histories, errors = await self.get_price_histories_with_errors(tickers, start_date, end_date)
        snapshots = [
            sorted(history, key=lambda item: item.trade_date)[-1]
            for history in histories.values()
            if history
        ]
        return snapshots, errors

    async def get_price_histories_with_errors(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> tuple[dict[str, list[MarketSnapshot]], list[MarketFetchError]]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def fetch_one(ticker: str):
            async with semaphore:
                try:
                    return ticker, await self.get_price_history(ticker, start_date, end_date), None
                except Exception as exc:
                    return ticker, [], self._fetch_error(ticker, "TaiwanStockPrice", exc)

        results = await asyncio.gather(*(fetch_one(ticker) for ticker in tickers))
        histories: dict[str, list[MarketSnapshot]] = {}
        errors: list[MarketFetchError] = []
        for ticker, history, error in results:
            if error:
                errors.append(error)
                continue
            if history:
                histories[ticker] = sorted(history, key=lambda item: item.trade_date)
            else:
                errors.append(
                    MarketFetchError(
                        ticker=ticker,
                        dataset="TaiwanStockPrice",
                        error="FinMind returned no price rows for requested period",
                    )
                )
                histories[ticker] = []
        return histories, errors

    async def get_monthly_revenue_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[MonthlyRevenue]:
        params = {
            "dataset": "TaiwanStockMonthRevenue",
            "data_id": ticker,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
        headers = {}
        if self.settings.finmind_token:
            headers["Authorization"] = f"Bearer {self.settings.finmind_token}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                "https://api.finmindtrade.com/api/v4/data",
                params=params,
                headers=headers,
            )
            response.raise_for_status()

        payload = response.json()
        rows = payload.get("data", [])
        return [self._row_to_monthly_revenue(row) for row in rows]

    async def get_monthly_revenue_histories(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> list[MonthlyRevenue]:
        revenues, _errors = await self.get_monthly_revenue_histories_with_errors(tickers, start_date, end_date)
        return revenues

    async def get_monthly_revenue_histories_with_errors(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> tuple[list[MonthlyRevenue], list[MarketFetchError]]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def fetch_one(ticker: str):
            async with semaphore:
                try:
                    return ticker, await self.get_monthly_revenue_history(ticker, start_date, end_date), None
                except Exception as exc:
                    return ticker, [], self._fetch_error(ticker, "TaiwanStockMonthRevenue", exc)

        results = await asyncio.gather(*(fetch_one(ticker) for ticker in tickers))
        revenues: list[MonthlyRevenue] = []
        errors: list[MarketFetchError] = []
        for ticker, ticker_revenues, error in results:
            if error:
                errors.append(error)
                continue
            if ticker_revenues:
                revenues.extend(ticker_revenues)
            else:
                errors.append(
                    MarketFetchError(
                        ticker=ticker,
                        dataset="TaiwanStockMonthRevenue",
                        error="FinMind returned no monthly revenue rows for requested period",
                    )
                )
        return revenues, errors

    async def get_financial_metrics_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[FinancialMetric]:
        datasets = {
            "TaiwanStockFinancialStatements": "income_statement",
            "TaiwanStockBalanceSheet": "balance_sheet",
            "TaiwanStockCashFlowsStatement": "cash_flow",
        }
        metrics: list[FinancialMetric] = []
        for dataset, statement_type in datasets.items():
            params = {
                "dataset": dataset,
                "data_id": ticker,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            }
            headers = {}
            if self.settings.finmind_token:
                headers["Authorization"] = f"Bearer {self.settings.finmind_token}"

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    "https://api.finmindtrade.com/api/v4/data",
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
            payload = response.json()
            metrics.extend(
                self._row_to_financial_metric(row, statement_type, dataset)
                for row in payload.get("data", [])
                if self._float_or_none(row.get("value")) is not None
            )
        return metrics

    async def get_financial_metrics_histories_with_errors(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> tuple[list[FinancialMetric], list[MarketFetchError]]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def fetch_one(ticker: str):
            async with semaphore:
                try:
                    return ticker, await self.get_financial_metrics_history(ticker, start_date, end_date), None
                except Exception as exc:
                    return ticker, [], self._fetch_error(ticker, "FinMindFinancialStatements", exc)

        results = await asyncio.gather(*(fetch_one(ticker) for ticker in tickers))
        metrics: list[FinancialMetric] = []
        errors: list[MarketFetchError] = []
        for ticker, ticker_metrics, error in results:
            if error:
                errors.append(error)
                continue
            if ticker_metrics:
                metrics.extend(ticker_metrics)
            else:
                errors.append(
                    MarketFetchError(
                        ticker=ticker,
                        dataset="FinMindFinancialStatements",
                        error="FinMind returned no financial statement rows for requested period",
                    )
                )
        return metrics, errors

    async def get_valuation_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[ValuationMetric]:
        params = {
            "dataset": "TaiwanStockPER",
            "data_id": ticker,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
        headers = {}
        if self.settings.finmind_token:
            headers["Authorization"] = f"Bearer {self.settings.finmind_token}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                "https://api.finmindtrade.com/api/v4/data",
                params=params,
                headers=headers,
            )
            response.raise_for_status()

        payload = response.json()
        return [self._row_to_valuation_metric(row) for row in payload.get("data", [])]

    async def get_latest_valuations_with_errors(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> tuple[list[ValuationMetric], list[MarketFetchError]]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def fetch_one(ticker: str):
            async with semaphore:
                try:
                    return ticker, await self.get_valuation_history(ticker, start_date, end_date), None
                except Exception as exc:
                    return ticker, [], self._fetch_error(ticker, "TaiwanStockPER", exc)

        results = await asyncio.gather(*(fetch_one(ticker) for ticker in tickers))
        valuations: list[ValuationMetric] = []
        errors: list[MarketFetchError] = []
        for ticker, history, error in results:
            if error:
                errors.append(error)
                continue
            if history:
                valuations.append(sorted(history, key=lambda item: item.trade_date)[-1])
            else:
                errors.append(
                    MarketFetchError(
                        ticker=ticker,
                        dataset="TaiwanStockPER",
                        error="FinMind returned no valuation rows for requested period",
                    )
                )
        return valuations, errors

    @staticmethod
    def _fetch_error(ticker: str, dataset: str, exc: Exception) -> MarketFetchError:
        message = str(exc) or exc.__class__.__name__
        return MarketFetchError(ticker=ticker, dataset=dataset, error=message)

    @staticmethod
    def _row_to_snapshot(row: dict) -> MarketSnapshot:
        return MarketSnapshot(
            ticker=str(row.get("stock_id") or row.get("data_id")),
            trade_date=date.fromisoformat(row["date"]),
            open=MarketDataClient._float_or_none(row.get("open")),
            high=MarketDataClient._float_or_none(row.get("max")),
            low=MarketDataClient._float_or_none(row.get("min")),
            close=MarketDataClient._float_or_none(row.get("close")),
            spread=MarketDataClient._float_or_none(row.get("spread")),
            trading_volume=MarketDataClient._int_or_none(row.get("Trading_Volume")),
            trading_money=MarketDataClient._int_or_none(row.get("Trading_money")),
            trading_turnover=MarketDataClient._float_or_none(row.get("Trading_turnover")),
            fetched_at=datetime.utcnow(),
        )

    @staticmethod
    def _row_to_monthly_revenue(row: dict) -> MonthlyRevenue:
        revenue_date = date.fromisoformat(row["date"])
        return MonthlyRevenue(
            ticker=str(row.get("stock_id") or row.get("data_id")),
            revenue_date=revenue_date,
            revenue=MarketDataClient._int_or_none(row.get("revenue")) or 0,
            revenue_year=int(row.get("revenue_year") or revenue_date.year),
            revenue_month=int(row.get("revenue_month") or revenue_date.month),
            fetched_at=datetime.utcnow(),
        )

    @staticmethod
    def _row_to_financial_metric(row: dict, statement_type: str, source: str) -> FinancialMetric:
        return FinancialMetric(
            ticker=str(row.get("stock_id") or row.get("data_id")),
            report_date=date.fromisoformat(row["date"]),
            statement_type=statement_type,
            metric=str(row.get("type") or row.get("metric") or row.get("origin_name")),
            value=float(row.get("value")),
            origin_name=row.get("origin_name"),
            source=f"FinMind {source}",
            fetched_at=datetime.utcnow(),
        )

    @staticmethod
    def _row_to_valuation_metric(row: dict) -> ValuationMetric:
        return ValuationMetric(
            ticker=str(row.get("stock_id") or row.get("data_id")),
            trade_date=date.fromisoformat(row["date"]),
            pe_ratio=MarketDataClient._float_or_none(
                row.get("PER") or row.get("pe_ratio") or row.get("PE")
            ),
            pb_ratio=MarketDataClient._float_or_none(
                row.get("PBR") or row.get("pb_ratio") or row.get("PB")
            ),
            dividend_yield=MarketDataClient._float_or_none(
                row.get("dividend_yield") or row.get("DividendYield")
            ),
            fetched_at=datetime.utcnow(),
        )

    @staticmethod
    def _float_or_none(value) -> float | None:
        return None if value in (None, "") else float(value)

    @staticmethod
    def _int_or_none(value) -> int | None:
        return None if value in (None, "") else int(value)
