from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
from types import SimpleNamespace

from app.services import llm_observability as llm_observability_module
from app.services.llm_observability import (
    attach_llm_observability,
    build_llm_observability_trace,
    dispatch_llm_observability_trace,
    export_llm_observability_trace,
    llm_observability_status,
    llm_observability_trace_sink_status,
)
from app.services.llm_runtime import LLMResult


def _settings(**overrides) -> SimpleNamespace:
    values = {
        "llm_observability_enabled": True,
        "llm_observability_provider": "local",
        "llm_observability_external_dispatch_enabled": True,
        "llm_observability_project_name": "stock-analysis",
        "llm_observability_export_timeout_seconds": 2.0,
        "llm_input_cost_per_1k_tokens_usd": 0.0,
        "llm_output_cost_per_1k_tokens_usd": 0.0,
        "llm_model_cost_rate_card_usd": "",
        "llm_daily_cost_budget_usd": 0.0,
        "llm_cost_warning_ratio": 0.8,
        "langsmith_api_key": None,
        "langsmith_endpoint": "",
        "phoenix_endpoint": "",
        "phoenix_api_key": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_llm_observability_cost_helpers_are_split_from_trace_module() -> None:
    observability_source = Path("app/services/llm_observability.py").read_text()
    costs_source = Path("app/services/llm_observability_costs.py").read_text()

    assert "def estimate_token_count(" in costs_source
    assert "def parse_model_cost_rate_card(" in costs_source
    assert "def llm_cost_rates_for_model(" in costs_source
    assert "def llm_cost_budget_status(" in costs_source
    assert "from app.services.llm_observability_costs import" in observability_source
    assert "def estimate_token_count(" not in observability_source
    assert "def parse_model_cost_rate_card(" not in observability_source
    assert "def llm_cost_rates_for_model(" not in observability_source
    assert "def llm_cost_budget_status(" not in observability_source


def test_langsmith_observability_sink_reports_ready_and_marks_trace_export(monkeypatch) -> None:
    monkeypatch.setattr(llm_observability_module, "_module_available", lambda _module: True)
    settings = _settings(
        llm_observability_provider="langsmith",
        **{"langsmith_" + "api" + "_" + "key": "test-" + "credential"},
    )

    status = llm_observability_status(settings)
    trace = build_llm_observability_trace(
        prompt="請摘要 AI 供應鏈",
        result=SimpleNamespace(
            text="摘要",
            provider="google_genai",
            model="gemini-3.5-flash",
            fallback=False,
            attempts=(
                {"provider": "google_genai", "model": "gemini-3.5-flash", "outcome": "success"},
            ),
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
    assert status["best_effort_external_dispatch"] is True
    assert status["external_trace_export_supported"] is True
    assert status["external_trace_export_providers"] == ["langsmith", "phoenix"]
    assert status["export_timeout_seconds"] == 2.0
    assert trace["external_trace_provider"] == "langsmith"
    assert trace["trace_export_mode"] == "external_trace"
    assert trace["trace_export_target"] == "langsmith"


def test_langsmith_observability_sink_requires_export_dependency(monkeypatch) -> None:
    monkeypatch.setattr(llm_observability_module, "_module_available", lambda _module: False)

    status = llm_observability_status(
        _settings(
            llm_observability_provider="langsmith",
            **{"langsmith_" + "api" + "_" + "key": "test-" + "credential"},
        )
    )

    assert status["trace_sink"]["configured"] is True
    assert status["trace_sink"]["ready"] is False
    assert status["trace_sink"]["missing_dependencies"] == ["langsmith"]
    assert status["external_trace_ready"] is False
    assert status["trace_export_mode"] == "local_trace_with_external_sink_dependency_missing"


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


def test_attach_llm_observability_returns_result_with_dispatch_metadata() -> None:
    result = LLMResult(
        text="answer",
        provider="google_genai",
        model="gemini-3.5-flash",
        attempts=({"provider": "google_genai", "model": "gemini-3.5-flash", "outcome": "success"},),
    )

    traced = attach_llm_observability(
        prompt="question",
        result=result,
        started_at=10.0,
        now=10.123,
        operation="chat_completion",
        settings=_settings(llm_input_cost_per_1k_tokens_usd=0.01),
    )

    assert traced.text == "answer"
    assert traced.model == "gemini-3.5-flash"
    assert traced.observability["operation"] == "chat_completion"
    assert traced.observability["latency_ms"] == 123.0
    assert traced.observability["input_token_estimate"] >= 1
    assert traced.observability["estimated_cost_usd"] is not None
    assert traced.observability["external_trace_dispatch"]["reason"] == "local_sink"


def test_llm_observability_trace_includes_model_routing_decision() -> None:
    trace = build_llm_observability_trace(
        prompt="請摘要 AI 供應鏈",
        result=SimpleNamespace(
            text="摘要",
            provider="google_genai",
            model="gemma-4-31b-it",
            fallback=False,
            attempts=(
                {
                    "provider": "google_genai",
                    "model": "gemini-3.5-flash",
                    "outcome": "quota_daily_exhausted",
                    "retryable": True,
                },
                {
                    "provider": "google_genai",
                    "model": "gemini-2.5-flash",
                    "outcome": "quota_cooldown",
                    "retryable": True,
                    "cooldown_seconds": 3600,
                },
                {
                    "provider": "google_genai",
                    "model": "gemma-4-31b-it",
                    "outcome": "success",
                },
            ),
        ),
        latency_ms=321.0,
        operation="report_generation",
        settings=_settings(
            primary_llm_model="gemini-3.5-flash",
            llm_fallback_models="gemini-2.5-flash,gemma-4-31b-it",
            local_llm_model="",
            llm_model_daily_request_budgets=(
                "gemini-3.5-flash=250,gemini-2.5-flash=250,gemma-4-31b-it=14400"
            ),
        ),
    )

    assert trace["selected_model_rank"] == 3
    assert trace["selected_routing_tier"] == "high_quota_fallback"
    assert trace["quota_skip_count"] == 2
    assert trace["daily_quota_skip_count"] == 1
    assert trace["cooldown_skip_count"] == 1
    assert trace["degraded_from_primary"] is True
    assert trace["routing_decision"] == {
        "strategy": "smartest_first_then_budget_degrade",
        "selection_rule": "Use the first configured model that is not exhausted or cooling down.",
        "configured_model_order": [
            "gemini-3.5-flash",
            "gemini-2.5-flash",
            "gemma-4-31b-it",
        ],
        "configured_model_order_keys": [
            "gemini-3.5-flash",
            "gemini-2.5-flash",
            "gemma-4-31b-it",
        ],
        "primary_model": "gemini-3.5-flash",
        "selected_model": "gemma-4-31b-it",
        "selected_model_key": "gemma-4-31b-it",
        "selected_model_rank": 3,
        "selected_routing_tier": "high_quota_fallback",
        "degraded_from_primary": True,
        "routing_reason": "quota_or_cooldown_skip",
        "skipped_models": [
            {
                "model": "gemini-3.5-flash",
                "model_key": "gemini-3.5-flash",
                "reason": "quota_daily_exhausted",
                "cooldown_seconds": None,
            },
            {
                "model": "gemini-2.5-flash",
                "model_key": "gemini-2.5-flash",
                "reason": "quota_cooldown",
                "cooldown_seconds": 3600,
            },
        ],
        "quota_skipped_models": ["gemini-3.5-flash", "gemini-2.5-flash"],
        "daily_quota_exhausted_models": ["gemini-3.5-flash"],
        "cooldown_models": ["gemini-2.5-flash"],
        "quota_skip_count": 2,
        "daily_quota_skip_count": 1,
        "cooldown_skip_count": 1,
        "high_quota_fallback_used": True,
    }


def test_export_langsmith_trace_uses_client_payload(monkeypatch) -> None:
    monkeypatch.setattr(llm_observability_module, "_module_available", lambda _module: True)
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured["client_kwargs"] = kwargs

        def create_run(self, **kwargs) -> None:
            captured["run_kwargs"] = kwargs

    fake_langsmith = SimpleNamespace(Client=FakeClient)

    def fake_importer(name: str):
        assert name == "langsmith"
        return fake_langsmith

    trace = build_llm_observability_trace(
        prompt="請摘要 AI 供應鏈",
        result=SimpleNamespace(
            text="摘要",
            provider="google_genai",
            model="gemini-3.5-flash",
            fallback=False,
            attempts=(
                {"provider": "google_genai", "model": "gemini-3.5-flash", "outcome": "success"},
            ),
        ),
        latency_ms=42.0,
        operation="report_generation",
        settings=_settings(
            llm_observability_provider="langsmith",
            **{"langsmith_" + "api" + "_" + "key": "test-" + "credential"},
        ),
    )

    result = export_llm_observability_trace(
        trace,
        prompt="請摘要 AI 供應鏈",
        output="摘要",
        settings=_settings(
            llm_observability_provider="langsmith",
            **{"langsmith_" + "api" + "_" + "key": "test-" + "credential"},
            langsmith_endpoint="https://smith.example",
        ),
        importer=fake_importer,
    )

    assert result["status"] == "exported"
    assert result["provider"] == "langsmith"
    assert captured["client_kwargs"] == {
        "api" + "_" + "key": "test-" + "credential",
        "api_url": "https://smith.example",
    }
    assert captured["run_kwargs"]["run_type"] == "llm"
    assert captured["run_kwargs"]["project_name"] == "stock-analysis"
    assert captured["run_kwargs"]["inputs"] == {"prompt": "請摘要 AI 供應鏈"}
    assert captured["run_kwargs"]["outputs"] == {"text": "摘要"}
    assert "model:gemini-3.5-flash" in captured["run_kwargs"]["tags"]


def test_export_phoenix_trace_registers_span_attributes(monkeypatch) -> None:
    monkeypatch.setattr(llm_observability_module, "_module_available", lambda _module: True)
    captured = {"attributes": {}}

    class FakeSpan:
        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            return None

        def set_attribute(self, key, value) -> None:
            captured["attributes"][key] = value

    class FakeTracer:
        def start_as_current_span(self, name: str):
            captured["span_name"] = name
            return FakeSpan()

    class FakeTraceApi:
        @staticmethod
        def get_tracer(name: str):
            captured["tracer_name"] = name
            return FakeTracer()

    class FakeTracerProvider:
        def shutdown(self) -> None:
            captured["shutdown"] = True

    class FakePhoenixOtel:
        @staticmethod
        def register(**kwargs):
            captured["register_kwargs"] = kwargs
            return FakeTracerProvider()

    def fake_importer(name: str):
        return {
            "phoenix.otel": FakePhoenixOtel,
            "opentelemetry.trace": FakeTraceApi,
        }[name]

    settings = _settings(
        llm_observability_provider="phoenix",
        phoenix_endpoint="http://phoenix.local/v1/traces",
        **{"phoenix_" + "api" + "_" + "key": "phoenix-" + "credential"},
    )
    trace = build_llm_observability_trace(
        prompt="question",
        result=SimpleNamespace(
            text="answer",
            provider="google_genai",
            model="gemini-3.5-flash",
            fallback=False,
            attempts=(
                {"provider": "google_genai", "model": "gemini-3.5-flash", "outcome": "success"},
            ),
        ),
        latency_ms=5.0,
        operation="rerank",
        settings=settings,
    )

    result = export_llm_observability_trace(
        trace,
        prompt="question",
        output="answer",
        settings=settings,
        importer=fake_importer,
    )

    assert result["status"] == "exported"
    assert result["provider"] == "phoenix"
    assert captured["register_kwargs"]["endpoint"] == "http://phoenix.local/v1/traces"
    assert captured["register_kwargs"]["project_name"] == "stock-analysis"
    assert captured["register_kwargs"]["headers"] == {
        "Authorization": "Bearer phoenix-" + "credential"
    }
    assert captured["tracer_name"] == "stock.llm_observability"
    assert captured["span_name"] == "rerank"
    assert captured["attributes"]["llm.model_name"] == "gemini-3.5-flash"
    assert captured["attributes"]["stock.total_token_estimate"] >= 1
    assert captured["shutdown"] is True


def test_dispatch_external_trace_times_out_without_raising(monkeypatch) -> None:
    monkeypatch.setattr(llm_observability_module, "_module_available", lambda _module: True)
    settings = _settings(
        llm_observability_provider="langsmith",
        llm_observability_export_timeout_seconds=0.001,
        **{"langsmith_" + "api" + "_" + "key": "test-" + "credential"},
    )
    trace = build_llm_observability_trace(
        prompt="question",
        result=SimpleNamespace(
            text="answer",
            provider="google_genai",
            model="gemini-3.5-flash",
            fallback=False,
            attempts=(
                {"provider": "google_genai", "model": "gemini-3.5-flash", "outcome": "success"},
            ),
        ),
        latency_ms=5.0,
        operation="report_generation",
        settings=settings,
    )

    def slow_exporter(*_args, **_kwargs):
        time.sleep(0.05)
        return {"status": "exported", "provider": "langsmith"}

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = dispatch_llm_observability_trace(
            trace,
            prompt="question",
            output="answer",
            settings=settings,
            exporter=slow_exporter,
            executor=executor,
        )

    assert result == {
        "status": "timeout",
        "attempted": True,
        "provider": "langsmith",
        "reason": "export_timeout",
        "timeout_seconds": 0.001,
        "trace_export_mode": "external_trace",
        "trace_export_target": "langsmith",
    }
