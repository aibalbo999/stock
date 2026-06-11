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
            {
                "severity": "warning",
                "code": "report_llm_fallback_used",
                "message": "Some latest reports used LLM fallback routing.",
            },
            "ignored",
        ],
        "bottlenecks": [
            {
                "id": 7,
                "topic": "AI 伺服器",
                "severity": "warning",
                "score": 42.5,
                "dominant_factor": "llm_latency",
                "reasons": "llm_latency_ms=9000；quota_skips=1",
                "next_action": "檢查 prompt 長度與模型選擇。",
                "llm_latency_ms": 9000,
                "retrieval_latency_ms": 12.34,
            },
            None,
        ],
        "recommendations": [
            {
                "code": "llm_quota_routing",
                "priority": 20,
                "severity": "warning",
                "affected_reports": 2,
                "evidence": "fallback=1; quota_skips=1; degraded=1; keyword_fallback=1",
                "next_action": "確認 smart model 在 fallback 前，且 cooldown 結束後再重試。",
                "top_report_id": 7,
                "top_topic": "AI 伺服器",
                "top_dominant_factor": "llm_latency",
                "top_score": 42.5,
            },
            "ignored",
        ],
        "reports": [
            {
                "id": 7,
                "topic": "AI 伺服器",
                "model": "gemini-3.5-flash",
                "llm_latency_ms": 9000,
                "retrieval_latency_ms": 12.34,
                "total_token_estimate": 4096,
                "estimated_cost_usd": 0.0012,
                "degraded_from_primary": True,
                "keyword_fallback": True,
                "graph_reasoning_path_count": 2,
                "graph_reasoning_coverage_ratio": 1.0,
            },
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
        {
            "嚴重度": "警告",
            "提醒": "部分最新版報告使用模型降級路由。",
            "下一步": "檢查今日模型額度、冷卻與模型順序；確認聰明模型額度用完後才降級。",
        }
    ]
    rendered_alerts = str(report_observability_alert_rows(summary))
    assert "report_llm_fallback_used" not in rendered_alerts
    assert "Some latest reports" not in rendered_alerts
    assert "cooldown" not in rendered_alerts
    assert report_observability_bottleneck_rows(summary) == [
        {
            "報告": "#7",
            "主題": "AI 伺服器",
            "嚴重度": "警告",
            "主要瓶頸": "LLM 延遲",
            "分數": 42.5,
            "原因": "LLM 延遲 9000 ms；額度略過 1 次",
            "下一步": "檢查 prompt 長度與模型選擇。",
        }
    ]
    assert report_observability_recommendation_rows(summary) == [
        {
            "優先順序": 20,
            "嚴重度": "警告",
            "建議": "模型額度與降級路由",
            "影響": "2 份報告",
            "關聯報告": "#7",
            "主要瓶頸": "LLM 延遲",
            "證據": "後援 1 次；額度略過 1 次；模型降級 1 次；關鍵字後援 1 次",
            "下一步": "確認聰明模型在後援前，且冷卻結束後再重試。",
        }
    ]
    assert report_observability_report_rows(summary) == [
        {
            "報告": "#7",
            "主題": "AI 伺服器",
            "模型": "gemini-3.5-flash",
            "LLM 延遲 ms": 9000,
            "檢索延遲 ms": 12.34,
            "Token 估算": 4096,
            "估算成本 USD": 0.0012,
            "模型降級": "是",
            "關鍵字後援": "是",
            "圖譜推理路徑": 2,
            "圖譜推理覆蓋率": "100%",
        }
    ]
    rendered_rows = str(
        report_observability_bottleneck_rows(summary)
        + report_observability_recommendation_rows(summary)
        + report_observability_report_rows(summary)
    )
    assert "dominant_factor" not in rendered_rows
    assert "llm_latency_ms" not in rendered_rows
    assert "top_report_id" not in rendered_rows
    assert "graph_reasoning_coverage_ratio" not in rendered_rows
    assert "fallback=1" not in rendered_rows
    assert "quota_skips=1" not in rendered_rows
    assert "degraded=1" not in rendered_rows
    assert "keyword_fallback=1" not in rendered_rows
    assert "smart model" not in rendered_rows
    assert "cooldown" not in rendered_rows


def test_report_observability_rows_localize_trace_payload_terms() -> None:
    summary = {
        "alerts": [
            {
                "severity": "warning",
                "code": "report_trace_missing",
            }
        ],
        "bottlenecks": [
            {
                "id": 8,
                "topic": "散熱",
                "severity": "warning",
                "score": 10,
                "dominant_factor": "trace_missing",
                "next_action": "重新產生或檢查 run payload 是否寫入 report_execution trace。",
            }
        ],
        "recommendations": [
            {
                "code": "trace_missing",
                "priority": 10,
                "severity": "warning",
                "affected_reports": 1,
                "evidence": "trace_missing=1",
                "next_action": "重新產生缺 trace 的報告，並確認 run payload 寫入 report_execution。",
            }
        ],
    }

    rendered = str(
        report_observability_alert_rows(summary)
        + report_observability_bottleneck_rows(summary)
        + report_observability_recommendation_rows(summary)
    )

    assert "報告產生紀錄的輸入內容" in rendered
    assert "報告追蹤資料" in rendered
    assert "run payload" not in rendered
    assert "report_execution" not in rendered
    assert "trace" not in rendered


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
