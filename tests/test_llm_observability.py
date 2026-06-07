from __future__ import annotations

from types import SimpleNamespace

from app.services.llm_observability import (
    build_llm_observability_trace,
    llm_observability_status,
    llm_observability_trace_sink_status,
)


def _settings(**overrides) -> SimpleNamespace:
    values = {
        "llm_observability_enabled": True,
        "llm_observability_provider": "local",
        "llm_input_cost_per_1k_tokens_usd": 0.0,
        "llm_output_cost_per_1k_tokens_usd": 0.0,
        "llm_model_cost_rate_card_usd": "",
        "llm_daily_cost_budget_usd": 0.0,
        "llm_cost_warning_ratio": 0.8,
        "langsmith_api_key": None,
        "phoenix_endpoint": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_langsmith_observability_sink_reports_ready_and_marks_trace_export() -> None:
    settings = _settings(
        llm_observability_provider="langsmith",
        langsmith_api_key="test-key",
    )

    status = llm_observability_status(settings)
    trace = build_llm_observability_trace(
        prompt="請摘要 AI 供應鏈",
        result=SimpleNamespace(
            text="摘要",
            provider="google_genai",
            model="gemini-3.5-flash",
            fallback=False,
            attempts=({"provider": "google_genai", "model": "gemini-3.5-flash", "outcome": "success"},),
        ),
        latency_ms=123.45,
        operation="report_generation",
        settings=settings,
    )

    assert status["trace_sink"]["provider"] == "langsmith"
    assert status["trace_sink"]["external_sink"] is True
    assert status["trace_sink"]["ready"] is True
    assert status["external_trace_ready"] is True
    assert status["external_trace_missing_settings"] == []
    assert status["trace_export_mode"] == "external_trace"
    assert status["trace_export_target"] == "langsmith"
    assert trace["external_trace_provider"] == "langsmith"
    assert trace["trace_export_mode"] == "external_trace"
    assert trace["trace_export_target"] == "langsmith"


def test_phoenix_observability_sink_stays_local_until_endpoint_is_configured() -> None:
    status = llm_observability_status(_settings(llm_observability_provider="phoenix"))

    assert status["trace_sink"]["provider"] == "phoenix"
    assert status["trace_sink"]["ready"] is False
    assert status["trace_sink"]["missing_settings"] == ["PHOENIX_ENDPOINT"]
    assert status["external_trace_configured"] is False
    assert status["external_trace_ready"] is False
    assert status["trace_export_mode"] == "local_trace_with_external_sink_pending"
    assert status["trace_export_target"] == "local"


def test_local_observability_sink_can_be_disabled_explicitly() -> None:
    status = llm_observability_trace_sink_status(
        _settings(llm_observability_enabled=False),
    )

    assert status["provider"] == "local"
    assert status["enabled"] is False
    assert status["ready"] is False
    assert status["trace_export_mode"] == "disabled"
    assert status["trace_export_target"] is None
