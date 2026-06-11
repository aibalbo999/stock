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
            "graph_reasoning_path_count": 5,
            "graph_reasoning_coverage_ratio": 0.75,
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
        "追蹤覆蓋": 2,
        "圖譜推理路徑": 5,
        "圖譜推理覆蓋率": "75%",
        "平均 LLM 延遲 ms": 123.45,
        "P95 LLM 延遲 ms": 456.78,
        "P95 檢索延遲 ms": 12.34,
        "關鍵字後援": 1,
        "額度略過": 2,
        "模型降級": 1,
    }
    rendered_metrics = str(report_observability_metric_values(summary))
    assert "GraphRAG paths" not in rendered_metrics
    assert "Graph 覆蓋率" not in rendered_metrics
    assert "P95 Retrieval ms" not in rendered_metrics
    assert "Keyword fallback" not in rendered_metrics
    assert "Quota skip" not in rendered_metrics
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
        "追蹤覆蓋": 0,
        "圖譜推理路徑": 0,
        "圖譜推理覆蓋率": "-",
        "平均 LLM 延遲 ms": "-",
        "P95 LLM 延遲 ms": "-",
        "P95 檢索延遲 ms": "-",
        "關鍵字後援": 0,
        "額度略過": 0,
        "模型降級": 0,
    }
    assert report_observability_alert_rows({}) == []
    assert report_observability_bottleneck_rows({}) == []
    assert report_observability_recommendation_rows({}) == []
    assert report_observability_report_rows({}) == []
