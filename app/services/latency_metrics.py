from __future__ import annotations

import math
from collections.abc import Iterable, Sequence


def latency_distribution(values: Iterable[float | int]) -> dict[str, float | None]:
    sorted_values = sorted(float(value) for value in values)
    if not sorted_values:
        return {"avg": None, "p95": None, "max": None}
    return {
        "avg": round(sum(sorted_values) / len(sorted_values), 2),
        "p95": round(nearest_rank_percentile(sorted_values, 95), 2),
        "max": round(sorted_values[-1], 2),
    }


def nearest_rank_percentile(sorted_values: Sequence[float], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    bounded_percentile = max(0.0, min(float(percentile), 100.0))
    rank = max(1, math.ceil((bounded_percentile / 100.0) * len(sorted_values)))
    return float(sorted_values[min(rank - 1, len(sorted_values) - 1)])
