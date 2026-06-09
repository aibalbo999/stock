from app.ui.report_observability_panel import (
    report_observability_alert_rows,
    report_observability_bottleneck_rows,
    report_observability_metric_values,
    report_observability_recommendation_rows,
    report_observability_report_rows,
)


def test_report_observability_metric_values_and_rows_filter_invalid_payloads() -> None:
    summary = {
        "status": "caution",
        "totals": {
            "report_count": 3,
            "trace_captured_count": 2,
            "avg_llm_latency_ms": 123.45,
            "p95_llm_latency_ms": 456.78,
            "p95_retrieval_latency_ms": 12.34,
            "keyword_fallback_count": 1,
            "quota_skip_count": 2,
            "degraded_from_primary_count": 1,
        },
        "alerts": [
            {"severity": "warning", "message": "Trace coverage is incomplete."},
            "ignored",
        ],
        "bottlenecks": [
            {"report_id": 7, "dominant_factor": "llm_latency"},
            None,
        ],
        "recommendations": [
            {"code": "llm_quota_routing", "priority": 20},
            "ignored",
        ],
        "reports": [
            {"id": 7, "llm_latency_ms": 9000},
            42,
        ],
    }

    assert report_observability_metric_values(summary) == {
        "狀態": "caution",
        "最新版報告": 3,
        "Trace 覆蓋": 2,
        "平均 LLM ms": 123.45,
        "P95 LLM ms": 456.78,
        "P95 Retrieval ms": 12.34,
        "Keyword fallback": 1,
        "Quota skip": 2,
        "模型降級": 1,
    }
    assert report_observability_alert_rows(summary) == [
        {"severity": "warning", "message": "Trace coverage is incomplete."}
    ]
    assert report_observability_bottleneck_rows(summary) == [
        {"report_id": 7, "dominant_factor": "llm_latency"}
    ]
    assert report_observability_recommendation_rows(summary) == [
        {"code": "llm_quota_routing", "priority": 20}
    ]
    assert report_observability_report_rows(summary) == [
        {"id": 7, "llm_latency_ms": 9000}
    ]


def test_report_observability_metric_values_handle_missing_summary() -> None:
    assert report_observability_metric_values({}) == {
        "狀態": "-",
        "最新版報告": 0,
        "Trace 覆蓋": 0,
        "平均 LLM ms": "-",
        "P95 LLM ms": "-",
        "P95 Retrieval ms": "-",
        "Keyword fallback": 0,
        "Quota skip": 0,
        "模型降級": 0,
    }
    assert report_observability_alert_rows({}) == []
    assert report_observability_bottleneck_rows({}) == []
    assert report_observability_recommendation_rows({}) == []
    assert report_observability_report_rows({}) == []
