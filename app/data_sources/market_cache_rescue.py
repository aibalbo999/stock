from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import TypeVar

STALE_CACHE_SOURCE_MARKER = "cached-stale"

T = TypeVar("T")


async def get_or_fetch_with_rescue(
    *,
    ticker: str,
    start_date: date,
    end_date: date,
    cache_get: Callable[[str, date, date], list[T] | None],
    cache_set: Callable[[str, date, date, list[T]], None],
    fetch_primary: Callable[[], Awaitable[list[T]]],
    fetch_fallback: Callable[[], Awaitable[list[T]]],
    get_stale_rows: Callable[[], list[T] | None],
) -> list[T]:
    cached = cache_get(ticker, start_date, end_date)
    if cached is not None:
        return cached

    try:
        rows = await fetch_primary()
    except Exception:
        fallback_rows = await fetch_fallback()
        if fallback_rows:
            cache_set(ticker, start_date, end_date, fallback_rows)
            return fallback_rows
        stale_rows = get_stale_rows()
        if stale_rows is not None:
            return stale_rows
        raise

    if not rows:
        fallback_rows = await fetch_fallback()
        if fallback_rows:
            cache_set(ticker, start_date, end_date, fallback_rows)
            return fallback_rows
        stale_rows = get_stale_rows()
        if stale_rows is not None:
            return stale_rows

    cache_set(ticker, start_date, end_date, rows)
    return rows


def get_stale_cache_rows(
    cache,
    *,
    method_name: str,
    ticker: str,
    marker: str = STALE_CACHE_SOURCE_MARKER,
) -> list | None:
    getter = getattr(cache, method_name, None)
    if not callable(getter):
        return None
    try:
        rows = getter(ticker)
    except Exception:
        return None
    if not rows:
        return None
    return [mark_stale_cache_source(row, marker=marker) for row in rows]


def mark_stale_cache_source(row, *, marker: str = STALE_CACHE_SOURCE_MARKER):
    source = str(getattr(row, "source", "") or "")
    if marker in source:
        return row
    if not source:
        return row.model_copy(update={"source": marker})
    suffix = f"; {marker}"
    max_source_length = 100
    trimmed_source = source[: max(0, max_source_length - len(suffix))]
    return row.model_copy(update={"source": f"{trimmed_source}{suffix}"})
