from __future__ import annotations

from app.ui.operator_quota_presenter import quota_operator_summary


def test_operator_quota_presenter_summarizes_smart_order_and_fallback() -> None:
    summary = quota_operator_summary(
        {
            "recommended_model": "gemini-3.5-flash",
            "model_order": ["gemini-3.5-flash", "gemma-4-31b-it"],
            "models": [
                {
                    "model": "gemini-3.5-flash",
                    "status": "ready",
                    "requests_remaining": 42,
                    "request_budget": 1500,
                },
                {
                    "model": "gemma-4-31b-it",
                    "status": "ready",
                    "routing_tier": "high_quota_fallback",
                    "requests_remaining": 14400,
                    "request_budget": 14400,
                },
            ],
        }
    )

    assert summary["recommended_model"] == "gemini-3.5-flash"
    assert summary["remaining"] == "42 / 1500"
    assert summary["state"] == "ready"
    assert summary["model_order_label"] == "順序：gemini-3.5-flash → gemma-4-31b-it"
    assert summary["limited_model_label"] == "受限：無"
    assert summary["high_quota_fallback_label"] == "高額度保底：gemma-4-31b-it"
    assert summary["operator_caption"] == (
        "聰明優先｜免費額度 42 / 1500｜下一順位 gemma-4-31b-it｜保底 gemma-4-31b-it"
    )


def test_operator_quota_presenter_surfaces_first_limited_model() -> None:
    summary = quota_operator_summary(
        {
            "recommended_model": "gemini-2.5-flash",
            "model_order": ["gemini-3.5-flash", "gemini-2.5-flash"],
            "models": [
                {
                    "model": "gemini-3.5-flash",
                    "status": "exhausted",
                    "requests_remaining": 0,
                    "request_budget": 1500,
                },
                {
                    "model": "gemini-2.5-flash",
                    "status": "ready",
                    "requests_remaining": 120,
                    "request_budget": 1500,
                },
            ],
        }
    )

    assert summary["limited_model_label"] == "受限：gemini-3.5-flash（耗盡）"
    assert "受限：gemini-3.5-flash（耗盡）" in summary["operator_caption"]
