from __future__ import annotations

from app.models.schemas import ValuationMetric
from app.services.report_quality import is_stale_market_data_source


def valuation_position_label_for(
    valuation: ValuationMetric | None,
    peer_summary: dict[str, float | None] | None = None,
    has_negative_profitability: bool = False,
) -> str:
    if not valuation:
        return "缺估值"
    if is_stale_market_data_source(valuation.source):
        return "估值為快取救援，需刷新"
    pressure, discount = _peer_pressure_discount_counts(valuation, peer_summary or {})
    return _relative_valuation_label(
        pressure,
        discount,
        has_negative_profitability=has_negative_profitability,
    )


def _peer_pressure_discount_counts(
    valuation: ValuationMetric,
    peer_summary: dict[str, float | None],
) -> tuple[int, int]:
    pe_avg = peer_summary.get("pe_avg")
    pb_avg = peer_summary.get("pb_avg")
    pressure = _relative_pressure_count(valuation.pe_ratio, pe_avg)
    discount = _relative_discount_count(valuation.pe_ratio, pe_avg)
    pressure += _relative_pressure_count(valuation.pb_ratio, pb_avg)
    discount += _relative_discount_count(valuation.pb_ratio, pb_avg)
    return pressure, discount


def _relative_pressure_count(value: float | None, average: float | None) -> int:
    return int(value is not None and bool(average) and value > average * 1.1)


def _relative_discount_count(value: float | None, average: float | None) -> int:
    return int(value is not None and bool(average) and value < average * 0.9)


def _relative_valuation_label(
    pressure: int,
    discount: int,
    *,
    has_negative_profitability: bool,
) -> str:
    if pressure >= 2:
        return "目前估值偏高"
    if pressure == 1 and discount == 0:
        return "目前估值略高"
    if has_negative_profitability and discount > 0 and pressure == 0:
        return "獲利為負，不判低估"
    if discount >= 2:
        return "目前估值低於同業"
    if discount == 1 and pressure == 0:
        return "目前估值略低"
    return "目前估值接近同業"


__all__ = ["valuation_position_label_for"]
