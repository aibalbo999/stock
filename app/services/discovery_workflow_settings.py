from __future__ import annotations

from typing import Any


def discovery_analysis_mode(payload: Any) -> str:
    return "deep" if payload.deep_analysis else payload.analysis_mode


def is_deep_discovery(payload: Any) -> bool:
    return discovery_analysis_mode(payload) == "deep"


def discovery_fetch_settings(payload: Any) -> tuple[int, int, int]:
    limit_per_query = max(payload.limit_per_query, 8)
    evidence_limit = max(payload.evidence_limit, 80)
    mode = discovery_analysis_mode(payload)
    max_queries = 24 if mode == "fast" else 36
    if mode == "deep":
        limit_per_query = max(limit_per_query, 20)
        evidence_limit = max(evidence_limit, 180)
        max_queries = 72
    return limit_per_query, evidence_limit, max_queries


def discovery_effective_lookback_days(payload: Any) -> int:
    mode = discovery_analysis_mode(payload)
    if mode == "deep":
        return max(payload.lookback_days, 120)
    if mode == "standard":
        return max(payload.lookback_days, 60)
    return payload.lookback_days


def discovery_document_limit(payload: Any, evidence_limit: int) -> int:
    mode = discovery_analysis_mode(payload)
    if mode == "deep":
        return max(1000, evidence_limit * 5)
    if mode == "standard":
        return max(600, evidence_limit * 4)
    return max(300, evidence_limit * 3)


def discovery_market_history_days(payload: Any) -> int:
    return (
        max(payload.lookback_days, 720)
        if is_deep_discovery(payload)
        else max(payload.lookback_days, 240)
    )


def discovery_valuation_history_days(payload: Any) -> int:
    return (
        max(payload.lookback_days, 180)
        if is_deep_discovery(payload)
        else max(payload.lookback_days, 30)
    )


__all__ = [
    "discovery_analysis_mode",
    "discovery_document_limit",
    "discovery_effective_lookback_days",
    "discovery_fetch_settings",
    "discovery_market_history_days",
    "discovery_valuation_history_days",
    "is_deep_discovery",
]
