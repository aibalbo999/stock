from __future__ import annotations

from app.services.report_observability_bottlenecks import (
    metric_float,
    metric_int,
    report_observability_bottleneck_rows,
    report_observability_recommendations,
)


def test_report_observability_bottleneck_rows_score_and_sort_report_risks() -> None:
    rows = [
        {
            "id": 1,
            "topic": "AI",
            "trace_captured": False,
            "fallback_path_used": False,
            "generated_at": "2026-06-02T08:00:00",
        },
        {
            "id": 2,
            "topic": "散熱",
            "trace_captured": True,
            "fallback_path_used": True,
            "quota_skip_count": 2,
            "keyword_fallback": True,
            "routing_reason": "quota_or_cooldown_skip",
            "llm_latency_ms": 6500,
            "retrieval_latency_ms": 1200,
            "total_token_estimate": 16000,
            "estimated_cost_usd": 0.02,
            "generated_at": "2026-06-02T09:00:00",
        },
    ]

    bottlenecks = report_observability_bottleneck_rows(rows)

    assert bottlenecks[0]["id"] == 2
    assert bottlenecks[0]["dominant_factor"] == "llm_fallback"
    assert bottlenecks[0]["severity"] == "warning"
    assert "quota_skips=2" in bottlenecks[0]["reasons"]
    assert "keyword_reranker_fallback" in bottlenecks[0]["reasons"]
    assert "quota/routing" in bottlenecks[0]["next_action"]
    assert bottlenecks[1]["dominant_factor"] == "trace_missing"


def test_report_observability_recommendations_reference_top_bottleneck() -> None:
    rows = [{"llm_latency_ms": 5200, "total_token_estimate": 13000, "estimated_cost_usd": 0.01}]
    bottlenecks = [{"id": 8, "topic": "AI", "dominant_factor": "token_volume", "score": 12.5}]
    totals = {
        "trace_missing_count": 1,
        "fallback_path_count": 1,
        "quota_skip_count": 2,
        "degraded_from_primary_count": 1,
        "retryable_failure_count": 1,
        "keyword_fallback_count": 1,
        "graph_reasoning_missing_count": 1,
        "graph_reasoning_partial_count": 0,
        "graph_reasoning_coverage_ratio": 0.5,
        "p95_llm_latency_ms": 5200,
    }

    recommendations = report_observability_recommendations(rows, totals, bottlenecks)

    assert [row["code"] for row in recommendations[:4]] == [
        "trace_missing",
        "llm_quota_routing",
        "llm_retryable_failures",
        "reranker_model_fallback",
    ]
    assert recommendations[0]["top_report_id"] == 8
    assert recommendations[0]["top_dominant_factor"] == "token_volume"
    assert "聰明模型" in recommendations[1]["next_action"]


def test_report_observability_metric_helpers_coerce_numeric_text() -> None:
    assert metric_int("12.8") == 12
    assert metric_float("12.8") == 12.8
    assert metric_int(None, default=3) == 3
    assert metric_float("bad", default=1.5) == 1.5
