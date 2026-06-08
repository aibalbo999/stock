from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from app.services.task_cancellation import TaskCancelledError

T = TypeVar("T")
E = TypeVar("E")


@dataclass(frozen=True)
class TickerRows(Generic[T, E]):
    ticker: str
    rows: list[T]
    error: E | None = None


async def fetch_ticker_rows(
    *,
    tickers: list[str],
    concurrency: int,
    dataset: str,
    fetch_rows: Callable[[str], Awaitable[list[T]]],
    make_error: Callable[[str, str, Exception], E],
    check_cancelled: Callable[[], None] | None = None,
) -> list[TickerRows[T, E]]:
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def fetch_one(ticker: str) -> TickerRows[T, E]:
        async with semaphore:
            if check_cancelled is not None:
                check_cancelled()
            try:
                return TickerRows(ticker=ticker, rows=await fetch_rows(ticker))
            except TaskCancelledError:
                raise
            except Exception as exc:
                return TickerRows(ticker=ticker, rows=[], error=make_error(ticker, dataset, exc))

    return await asyncio.gather(*(fetch_one(ticker) for ticker in tickers))


def collect_history_by_ticker(
    results: list[TickerRows[T, E]],
    *,
    dataset: str,
    empty_error: Callable[[str, str], E],
    sort_key: Callable[[T], object],
) -> tuple[dict[str, list[T]], list[E]]:
    histories: dict[str, list[T]] = {}
    errors: list[E] = []
    for result in results:
        if result.error is not None:
            errors.append(result.error)
            continue
        if result.rows:
            histories[result.ticker] = sorted(result.rows, key=sort_key)
        else:
            errors.append(empty_error(result.ticker, dataset))
            histories[result.ticker] = []
    return histories, errors


def collect_flat_rows(
    results: list[TickerRows[T, E]],
    *,
    dataset: str,
    empty_error: Callable[[str, str], E],
) -> tuple[list[T], list[E]]:
    rows: list[T] = []
    errors: list[E] = []
    for result in results:
        if result.error is not None:
            errors.append(result.error)
            continue
        if result.rows:
            rows.extend(result.rows)
        else:
            errors.append(empty_error(result.ticker, dataset))
    return rows, errors


def collect_latest_rows(
    results: list[TickerRows[T, E]],
    *,
    dataset: str,
    empty_error: Callable[[str, str], E],
    sort_key: Callable[[T], object],
) -> tuple[list[T], list[E]]:
    rows: list[T] = []
    errors: list[E] = []
    for result in results:
        if result.error is not None:
            errors.append(result.error)
            continue
        if result.rows:
            rows.append(sorted(result.rows, key=sort_key)[-1])
        else:
            errors.append(empty_error(result.ticker, dataset))
    return rows, errors


def latest_rows_from_histories(
    histories: dict[str, list[T]],
    *,
    sort_key: Callable[[T], object],
) -> list[T]:
    return [sorted(history, key=sort_key)[-1] for history in histories.values() if history]
