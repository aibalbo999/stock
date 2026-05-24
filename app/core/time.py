from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def now_taipei() -> datetime:
    return datetime.now(TAIPEI_TZ)


def today_taipei() -> date:
    return now_taipei().date()


def format_taipei(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(TAIPEI_TZ).isoformat(timespec="seconds")
