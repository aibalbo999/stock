from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEY_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|cookie|password|secret|token)\b(\s*[=:]\s*)([^\s,;]+)"
)
MAX_PREVIEW_LENGTH = 240


def safe_key_names(payload: dict) -> list[str]:
    names = {safe_key_name(key) for key in payload.keys()}
    return sorted(name for name in names if name)


def safe_key_name(key: object) -> str:
    text = str(key).strip()
    if not text:
        return ""
    lowered = text.casefold()
    if any(marker in lowered for marker in SENSITIVE_KEY_MARKERS):
        return "<sensitive>"
    return text


def sensitive_key_count(value: Any) -> int:
    if isinstance(value, dict):
        count = sum(
            1
            for key in value.keys()
            if any(marker in str(key).casefold() for marker in SENSITIVE_KEY_MARKERS)
        )
        return count + sum(sensitive_key_count(item) for item in value.values())
    if isinstance(value, list):
        return sum(sensitive_key_count(item) for item in value)
    return 0


def ticker_count(value: Any) -> int:
    tickers: set[str] = set()
    collect_tickers(value, tickers)
    return len(tickers)


def collect_tickers(value: Any, tickers: set[str], *, key_hint: str = "") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            collect_tickers(nested, tickers, key_hint=str(key).casefold())
        return
    if isinstance(value, list) and key_hint == "tickers":
        for item in value:
            text = str(item).strip()
            if text:
                tickers.add(text)


def redact_sensitive_text(value: str) -> str:
    return SECRET_ASSIGNMENT_RE.sub(r"\1\2<redacted>", value)


def truncate_preview(value: str, *, limit: int = MAX_PREVIEW_LENGTH) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


__all__ = [
    "collect_tickers",
    "redact_sensitive_text",
    "safe_key_name",
    "safe_key_names",
    "sensitive_key_count",
    "ticker_count",
    "truncate_preview",
]
