from app.services.latency_metrics import latency_distribution, nearest_rank_percentile


def test_latency_distribution_reports_avg_p95_and_max() -> None:
    assert latency_distribution([100, 250.125, 25, 400]) == {
        "avg": 193.78,
        "p95": 400.0,
        "max": 400.0,
    }


def test_latency_distribution_handles_empty_values() -> None:
    assert latency_distribution([]) == {"avg": None, "p95": None, "max": None}


def test_nearest_rank_percentile_bounds_percentile() -> None:
    values = [1.0, 2.0, 3.0]

    assert nearest_rank_percentile(values, -10) == 1.0
    assert nearest_rank_percentile(values, 50) == 2.0
    assert nearest_rank_percentile(values, 110) == 3.0
