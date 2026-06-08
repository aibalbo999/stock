from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.services import llm_client as llm_module
from app.services.api_key_rotation import APIKeyRotator, get_shared_rotator
from app.services.llm_attempts import summarize_llm_attempts
from app.services.llm_client import LLMClient, LLMResult
from app.services import llm_runtime


@pytest.fixture(autouse=True)
def clear_model_quota_cooldowns():
    with llm_module._model_quota_cooldowns_lock:
        llm_module._model_quota_cooldowns.clear()
    yield
    with llm_module._model_quota_cooldowns_lock:
        llm_module._model_quota_cooldowns.clear()


def fake_settings(**overrides) -> SimpleNamespace:
    defaults = {
        "primary_llm_model": "gemini-test",
        "llm_provider": "gemini_http",
        "llm_fallback_models": "",
        "llm_max_retries_per_key": 2,
        "llm_base_retry_delay_seconds": 0.5,
        "llm_max_retry_delay_seconds": 5.0,
        "llm_total_timeout_seconds": 60.0,
        "llm_model_quota_cooldown_seconds": 3600.0,
        "llm_quota_hard_routing_enabled": False,
        "llm_observability_enabled": True,
        "llm_observability_provider": "local",
        "llm_observability_external_dispatch_enabled": True,
        "llm_observability_project_name": "stock-analysis",
        "llm_input_cost_per_1k_tokens_usd": 0.01,
        "llm_output_cost_per_1k_tokens_usd": 0.02,
        "langsmith_api_key": None,
        "langsmith_endpoint": "",
        "phoenix_endpoint": "",
        "phoenix_api_key": None,
        "openai_api_key": None,
        "anthropic_api_key": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_api_key_rotator_advances_starting_key() -> None:
    rotator = APIKeyRotator(["a", "b", "c"])

    assert rotator.candidates() == [(0, "a"), (1, "b"), (2, "c")]
    assert rotator.candidates() == [(1, "b"), (2, "c"), (0, "a")]


def test_llm_provider_payload_helpers_are_split_from_client() -> None:
    client_source = Path("app/services/llm_client.py").read_text()
    provider_source = Path("app/services/llm_provider_calls.py").read_text()

    assert "def call_litellm(" in provider_source
    assert "def call_google_genai(" in provider_source
    assert "def call_gemini_vision(" in provider_source
    assert "litellm.completion" not in client_source
    assert "client.models.generate_content" not in client_source
    assert "inlineData" not in client_source


def test_llm_runtime_helpers_are_split_from_client() -> None:
    client_source = Path("app/services/llm_client.py").read_text()
    runtime_source = Path("app/services/llm_runtime.py").read_text()

    response = httpx.Response(
        503,
        headers={"Retry-After": "3.5"},
        request=httpx.Request("POST", "https://example.test"),
    )

    assert LLMResult is llm_runtime.LLMResult
    assert llm_module.RETRYABLE_HTTP_STATUSES is llm_runtime.RETRYABLE_HTTP_STATUSES
    assert llm_module.DEFAULT_MAX_RETRIES_PER_KEY == llm_runtime.DEFAULT_MAX_RETRIES_PER_KEY
    assert llm_module._model_quota_cooldowns is llm_runtime._model_quota_cooldowns
    assert llm_module._model_quota_cooldowns_lock is llm_runtime._model_quota_cooldowns_lock
    assert (
        llm_runtime.llm_retry_delay_seconds(
            response,
            attempt=0,
            base_retry_delay_seconds=0.5,
            max_retry_delay_seconds=5.0,
        )
        == 3.5
    )
    assert (
        llm_runtime.llm_attempt_record(
            provider="google_genai",
            model="gemini-3.5-flash",
            outcome="quota_cooldown",
            cooldown_seconds=2.3456,
        )["cooldown_seconds"]
        == 2.346
    )
    assert "@dataclass(frozen=True)\nclass LLMResult" not in client_source
    assert "def llm_retry_delay_seconds(" in runtime_source
    assert "def exception_status_code(" in runtime_source
    assert "def model_quota_cooldown_remaining(" in runtime_source


def test_llm_observability_attachment_is_split_from_client() -> None:
    client_source = Path("app/services/llm_client.py").read_text()
    observability_source = Path("app/services/llm_observability.py").read_text()

    assert "def attach_llm_observability(" in observability_source
    assert "build_llm_observability_trace(" not in client_source
    assert "dispatch_llm_observability_trace(" not in client_source
    assert '"external_trace_dispatch"' not in client_source


def test_llm_quota_cooldown_runtime_tracks_shared_model_state() -> None:
    with llm_runtime._model_quota_cooldowns_lock:
        llm_runtime._model_quota_cooldowns.clear()

    llm_runtime.start_model_quota_cooldown("gemini/gemini-3.5-flash", 30.0, now=100.0)

    assert llm_runtime.model_quota_cooldown_remaining("gemini-3.5-flash", now=110.0) == 20.0
    assert llm_runtime.model_quota_cooldown_remaining("models/gemini-3.5-flash", now=130.0) == 0.0
    assert llm_runtime.model_daily_quota_exhausted("gemini/gemini-3.5-flash", {"gemini-3.5-flash"})
    assert (
        llm_runtime.daily_quota_exhausted_model_keys(
            fake_settings(llm_quota_hard_routing_enabled=False)
        )
        == set()
    )


def test_llm_client_rotates_after_retryable_error(monkeypatch) -> None:
    client = object.__new__(LLMClient)
    client.settings = fake_settings()
    client.rotator = APIKeyRotator(["bad-key", "good-key"])
    calls = []

    def fake_call(prompt: str, api_key: str, **_kwargs) -> str:
        calls.append((prompt, api_key))
        if api_key == "bad-key":
            response = httpx.Response(429, request=httpx.Request("POST", "https://example.test"))
            raise httpx.HTTPStatusError("rate limited", request=response.request, response=response)
        return "ok"

    monkeypatch.setattr(client, "_call_gemini", fake_call)
    monkeypatch.setattr(client, "_sleep_before_retry", lambda response, attempt: None)

    result = client.generate_with_metadata("prompt")

    assert result.text == "ok"
    assert result.key_index == 1
    assert calls == [
        ("prompt", "bad-key"),
        ("prompt", "bad-key"),
        ("prompt", "bad-key"),
        ("prompt", "good-key"),
    ]
    assert result.observability["operation"] == "chat_completion"
    assert result.observability["latency_ms"] >= 0
    assert result.observability["input_token_estimate"] >= 1
    assert result.observability["output_token_estimate"] >= 1
    assert result.observability["estimated_cost_usd"] is not None
    assert result.observability["external_trace_dispatch"]["reason"] == "local_sink"


def test_llm_client_retries_503_before_rotating(monkeypatch) -> None:
    client = object.__new__(LLMClient)
    client.settings = fake_settings()
    client.rotator = APIKeyRotator(["flaky-key"])
    calls = []

    def fake_call(prompt: str, api_key: str, **_kwargs) -> str:
        calls.append((prompt, api_key))
        if len(calls) == 1:
            response = httpx.Response(503, request=httpx.Request("POST", "https://example.test"))
            raise httpx.HTTPStatusError("unavailable", request=response.request, response=response)
        return "ok-after-retry"

    monkeypatch.setattr(client, "_call_gemini", fake_call)
    monkeypatch.setattr(client, "_sleep_before_retry", lambda response, attempt: None)

    result = client.generate_with_metadata("prompt")

    assert result.text == "ok-after-retry"
    assert result.key_index == 0
    assert calls == [("prompt", "flaky-key"), ("prompt", "flaky-key")]


def test_llm_retry_delay_uses_retry_after_header() -> None:
    client = object.__new__(LLMClient)
    client.settings = fake_settings()
    response = httpx.Response(
        503,
        headers={"Retry-After": "2"},
        request=httpx.Request("POST", "https://example.test"),
    )

    assert client._retry_delay_seconds(response, attempt=0) == 2
    assert client._retry_delay_seconds(None, attempt=2) == 2.0


def test_llm_client_uses_configured_retry_count(monkeypatch) -> None:
    client = object.__new__(LLMClient)
    client.settings = fake_settings(llm_max_retries_per_key=1)
    client.rotator = APIKeyRotator(["flaky-key", "good-key"])
    calls = []

    def fake_call(prompt: str, api_key: str, **_kwargs) -> str:
        calls.append((prompt, api_key))
        if api_key == "flaky-key":
            response = httpx.Response(503, request=httpx.Request("POST", "https://example.test"))
            raise httpx.HTTPStatusError("unavailable", request=response.request, response=response)
        return "ok"

    monkeypatch.setattr(client, "_call_gemini", fake_call)
    monkeypatch.setattr(client, "_sleep_before_retry", lambda response, attempt: None)

    result = client.generate_with_metadata("prompt")

    assert result.text == "ok"
    assert calls == [
        ("prompt", "flaky-key"),
        ("prompt", "flaky-key"),
        ("prompt", "good-key"),
    ]


def test_shared_rotator_reuses_same_pool() -> None:
    first = get_shared_rotator(["shared-a", "shared-b"])
    second = get_shared_rotator(["shared-a", "shared-b"])

    assert first is second
    assert first.candidates()[0] == (0, "shared-a")
    assert second.candidates()[0] == (1, "shared-b")


def test_litellm_provider_uses_fallback_model(monkeypatch) -> None:
    client = object.__new__(LLMClient)
    client.settings = fake_settings(
        llm_provider="litellm",
        primary_llm_model="gemini-primary",
        llm_fallback_models="gemini/gemini-backup",
        llm_max_retries_per_key=0,
    )
    client.rotator = APIKeyRotator(["gemini-key"])
    calls = []

    monkeypatch.setattr("app.services.llm_client.import_module", lambda name: object())

    def fake_call(prompt: str, model: str, api_key: str | None = None, **_kwargs) -> str:
        calls.append((prompt, model, api_key))
        if model == "gemini/gemini-primary":
            response = httpx.Response(429, request=httpx.Request("POST", "https://example.test"))
            raise httpx.HTTPStatusError("rate limited", request=response.request, response=response)
        return "backup ok"

    monkeypatch.setattr(client, "_call_litellm", fake_call)
    monkeypatch.setattr(client, "_sleep_before_retry", lambda response, attempt: None)

    result = client.generate_with_metadata("prompt")

    assert result.text == "backup ok"
    assert result.provider == "litellm"
    assert result.model == "gemini/gemini-backup"
    assert result.attempts == (
        {
            "provider": "litellm",
            "outcome": "http_error",
            "model": "gemini/gemini-primary",
            "key_index": 0,
            "attempt": 1,
            "status": 429,
            "retryable": True,
        },
        {
            "provider": "litellm",
            "outcome": "success",
            "model": "gemini/gemini-backup",
            "key_index": 0,
            "attempt": 1,
        },
    )
    assert calls == [
        ("prompt", "gemini/gemini-primary", "gemini-key"),
        ("prompt", "gemini/gemini-backup", "gemini-key"),
    ]


def test_litellm_provider_can_fallback_from_gemini_to_anthropic(monkeypatch) -> None:
    client = object.__new__(LLMClient)
    client.settings = fake_settings(
        llm_provider="litellm",
        primary_llm_model="gemini-primary",
        llm_fallback_models="claude-3-5-haiku",
        llm_max_retries_per_key=0,
        anthropic_api_key="anthropic-key",
    )
    client.rotator = APIKeyRotator(["gemini-key"])
    calls = []

    monkeypatch.setattr("app.services.llm_client.import_module", lambda name: object())

    def fake_call(prompt: str, model: str, api_key: str | None = None, **_kwargs) -> str:
        calls.append((prompt, model, api_key))
        if model == "gemini/gemini-primary":
            response = httpx.Response(429, request=httpx.Request("POST", "https://example.test"))
            raise httpx.HTTPStatusError("rate limited", request=response.request, response=response)
        return "anthropic backup ok"

    monkeypatch.setattr(client, "_call_litellm", fake_call)
    monkeypatch.setattr(client, "_sleep_before_retry", lambda response, attempt: None)

    result = client.generate_with_metadata("prompt")

    assert result.text == "anthropic backup ok"
    assert result.provider == "litellm"
    assert result.model == "anthropic/claude-3-5-haiku"
    assert calls == [
        ("prompt", "gemini/gemini-primary", "gemini-key"),
        ("prompt", "anthropic/claude-3-5-haiku", "anthropic-key"),
    ]


def test_litellm_provider_skips_missing_provider_key_and_tries_next_model(monkeypatch) -> None:
    client = object.__new__(LLMClient)
    client.settings = fake_settings(
        llm_provider="litellm",
        primary_llm_model="gemini-primary",
        llm_fallback_models="gpt-4o-mini",
        llm_max_retries_per_key=0,
        openai_api_key="openai-key",
    )
    client.rotator = APIKeyRotator([])
    calls = []

    monkeypatch.setattr("app.services.llm_client.import_module", lambda name: object())

    def fake_call(prompt: str, model: str, api_key: str | None = None, **_kwargs) -> str:
        calls.append((prompt, model, api_key))
        return "openai backup ok"

    monkeypatch.setattr(client, "_call_litellm", fake_call)

    result = client.generate_with_metadata("prompt")

    assert result.text == "openai backup ok"
    assert result.model == "gpt-4o-mini"
    assert result.attempts == (
        {
            "provider": "litellm",
            "outcome": "missing_api_key",
            "model": "gemini/gemini-primary",
        },
        {
            "provider": "litellm",
            "outcome": "success",
            "model": "gpt-4o-mini",
            "attempt": 1,
        },
    )
    assert calls == [("prompt", "gpt-4o-mini", "openai-key")]


def test_litellm_provider_uses_gemma_cloud_model_with_gemini_key(monkeypatch) -> None:
    client = object.__new__(LLMClient)
    client.settings = fake_settings(
        llm_provider="litellm",
        primary_llm_model="gemini-3.5-flash",
        local_llm_model="gemma-4-31b-it",
        llm_fallback_models="",
        llm_max_retries_per_key=0,
    )
    client.rotator = APIKeyRotator(["gemini-key"])
    calls = []

    monkeypatch.setattr("app.services.llm_client.import_module", lambda name: object())

    def fake_call(prompt: str, model: str, api_key: str | None = None, **_kwargs) -> str:
        calls.append((prompt, model, api_key))
        if model == "gemini/gemini-3.5-flash":
            error = RuntimeError("rate limited")
            error.status_code = 429
            raise error
        return "cloud ok"

    monkeypatch.setattr(client, "_call_litellm", fake_call)

    result = client.generate_with_metadata("prompt")

    assert result.text == "cloud ok"
    assert result.model == "gemini/gemma-4-31b-it"
    assert result.attempts == (
        {
            "provider": "litellm",
            "outcome": "http_error",
            "model": "gemini/gemini-3.5-flash",
            "key_index": 0,
            "attempt": 1,
            "status": 429,
            "retryable": True,
        },
        {
            "provider": "litellm",
            "outcome": "success",
            "model": "gemini/gemma-4-31b-it",
            "key_index": 0,
            "attempt": 1,
        },
    )
    assert calls == [
        ("prompt", "gemini/gemini-3.5-flash", "gemini-key"),
        ("prompt", "gemini/gemma-4-31b-it", "gemini-key"),
    ]


def test_litellm_model_chain_limits_key_rotation_and_retries(monkeypatch) -> None:
    client = object.__new__(LLMClient)
    client.settings = fake_settings(
        llm_provider="litellm",
        primary_llm_model="gemini-primary",
        llm_fallback_models="gemini-backup",
        llm_max_retries_per_key=2,
    )
    client.rotator = APIKeyRotator(["key-a", "key-b", "key-c"])

    monkeypatch.setattr("app.services.llm_client.import_module", lambda name: object())

    def fake_call(prompt: str, model: str, api_key: str | None = None, **_kwargs) -> str:
        response = httpx.Response(429, request=httpx.Request("POST", "https://example.test"))
        raise httpx.HTTPStatusError("rate limited", request=response.request, response=response)

    monkeypatch.setattr(client, "_call_litellm", fake_call)

    result = client._generate_with_litellm("prompt")

    assert result.fallback is True
    assert [attempt["model"] for attempt in result.attempts] == [
        "gemini/gemini-primary",
        "gemini/gemini-backup",
    ]
    assert [attempt.get("attempt") for attempt in result.attempts] == [1, 1]
    assert [attempt.get("key_index") for attempt in result.attempts] == [0, 1]


def test_generate_structured_with_metadata_passes_tool_schema_to_litellm(monkeypatch) -> None:
    client = object.__new__(LLMClient)
    client.settings = fake_settings(
        llm_provider="litellm",
        primary_llm_model="gpt-test",
        llm_max_retries_per_key=0,
        openai_api_key="openai-key",
    )
    client.rotator = APIKeyRotator([])
    captured = {}

    monkeypatch.setattr("app.services.llm_client.import_module", lambda name: object())

    def fake_call(prompt: str, model: str, api_key: str | None = None, **kwargs) -> str:
        captured["call"] = {
            "prompt": prompt,
            "model": model,
            "api_key": api_key,
            "tools": kwargs.get("tools"),
            "tool_choice": kwargs.get("tool_choice"),
        }
        return '{"items":[]}'

    monkeypatch.setattr(client, "_call_litellm", fake_call)

    result = client.generate_structured_with_metadata(
        "prompt",
        tool_name="submit_report_supplement",
        tool_schema={
            "type": "function",
            "function": {
                "name": "submit_report_supplement",
                "parameters": {"type": "object"},
            },
        },
    )

    assert result.text == '{"items":[]}'
    assert captured["call"]["tools"][0]["function"]["name"] == "submit_report_supplement"
    assert captured["call"]["tool_choice"] == {
        "type": "function",
        "function": {"name": "submit_report_supplement"},
    }


def test_litellm_unavailable_falls_back_to_existing_gemini_http(monkeypatch) -> None:
    client = object.__new__(LLMClient)
    client.settings = fake_settings(llm_provider="litellm")
    client.rotator = APIKeyRotator(["gemini-key"])

    def missing_litellm(name: str):
        if name == "litellm":
            raise ImportError("missing")
        return object()

    monkeypatch.setattr("app.services.llm_client.import_module", missing_litellm)
    monkeypatch.setattr(client, "_call_gemini", lambda prompt, api_key, **_kwargs: "direct ok")

    result = client.generate_with_metadata("prompt")

    assert result.text == "direct ok"
    assert result.provider == "gemini_http"
    assert result.attempts == (
        {"provider": "litellm", "outcome": "dependency_unavailable", "error": "ImportError"},
        {
            "provider": "gemini_http",
            "outcome": "success",
            "model": "gemini-test",
            "key_index": 0,
            "attempt": 1,
        },
    )


def test_google_genai_provider_rotates_keys_before_http_fallback(monkeypatch) -> None:
    client = object.__new__(LLMClient)
    client.settings = fake_settings(llm_provider="google_genai", llm_max_retries_per_key=0)
    client.rotator = APIKeyRotator(["bad-key", "good-key"])
    calls = []

    monkeypatch.setattr("app.services.llm_client.import_module", lambda name: object())

    def fake_call(prompt: str, api_key: str, **_kwargs) -> str:
        calls.append((prompt, api_key))
        if api_key == "bad-key":
            response = httpx.Response(429, request=httpx.Request("POST", "https://example.test"))
            raise httpx.HTTPStatusError("rate limited", request=response.request, response=response)
        return "sdk ok"

    monkeypatch.setattr(client, "_call_google_genai", fake_call)
    monkeypatch.setattr(client, "_sleep_before_retry", lambda response, attempt: None)

    result = client.generate_with_metadata("prompt")

    assert result.text == "sdk ok"
    assert result.provider == "google_genai"
    assert result.key_index == 1
    assert result.attempts == (
        {
            "provider": "google_genai",
            "outcome": "http_error",
            "model": "gemini-test",
            "key_index": 0,
            "attempt": 1,
            "status": 429,
            "retryable": True,
        },
        {
            "provider": "google_genai",
            "outcome": "success",
            "model": "gemini-test",
            "key_index": 1,
            "attempt": 1,
        },
    )
    assert calls == [("prompt", "bad-key"), ("prompt", "good-key")]


def test_google_genai_model_chain_limits_key_rotation_and_uses_fallback(monkeypatch) -> None:
    client = object.__new__(LLMClient)
    client.settings = fake_settings(
        llm_provider="google_genai",
        primary_llm_model="gemini-primary",
        llm_fallback_models="gemini-backup",
        llm_max_retries_per_key=2,
    )
    client.rotator = APIKeyRotator(["key-a", "key-b", "key-c"])
    calls = []

    monkeypatch.setattr("app.services.llm_client.import_module", lambda name: object())

    def fake_call(prompt: str, api_key: str, *, model: str | None = None, **_kwargs) -> str:
        calls.append((prompt, model, api_key))
        if model == "gemini-primary":
            response = httpx.Response(429, request=httpx.Request("POST", "https://example.test"))
            raise httpx.HTTPStatusError("rate limited", request=response.request, response=response)
        return "backup ok"

    monkeypatch.setattr(client, "_call_google_genai", fake_call)

    result = client.generate_with_metadata("prompt")

    assert result.text == "backup ok"
    assert result.model == "gemini-backup"
    assert calls == [
        ("prompt", "gemini-primary", "key-a"),
        ("prompt", "gemini-backup", "key-b"),
    ]
    assert [attempt.get("attempt") for attempt in result.attempts] == [1, 1]
    assert [attempt.get("key_index") for attempt in result.attempts] == [0, 1]


def test_google_genai_model_quota_cooldown_skips_recently_limited_model(monkeypatch) -> None:
    with llm_module._model_quota_cooldowns_lock:
        llm_module._model_quota_cooldowns.clear()
    client = object.__new__(LLMClient)
    client.settings = fake_settings(
        llm_provider="google_genai",
        primary_llm_model="gemini-3.5-flash",
        llm_fallback_models="gemini-2.5-flash,gemma-4-31b-it,gemini-3.1-flash-lite",
        llm_model_quota_cooldown_seconds=3600.0,
    )
    client.rotator = APIKeyRotator(["key-a", "key-b"])
    calls = []

    monkeypatch.setattr("app.services.llm_client.import_module", lambda name: object())

    def fake_call(prompt: str, api_key: str, *, model: str | None = None, **_kwargs) -> str:
        calls.append((prompt, model, api_key))
        if model == "gemini-3.5-flash":
            response = httpx.Response(429, request=httpx.Request("POST", "https://example.test"))
            raise httpx.HTTPStatusError(
                "quota exhausted", request=response.request, response=response
            )
        return "2.5 ok"

    monkeypatch.setattr(client, "_call_google_genai", fake_call)

    first = client.generate_with_metadata("prompt")
    assert first.text == "2.5 ok"
    assert first.model == "gemini-2.5-flash"
    assert calls == [
        ("prompt", "gemini-3.5-flash", "key-a"),
        ("prompt", "gemini-2.5-flash", "key-b"),
    ]

    calls.clear()
    second = client.generate_with_metadata("prompt")

    assert second.text == "2.5 ok"
    assert second.model == "gemini-2.5-flash"
    assert calls == [
        ("prompt", "gemini-2.5-flash", "key-a"),
    ]
    assert any(
        attempt.get("model") == "gemini-3.5-flash" and attempt.get("outcome") == "quota_cooldown"
        for attempt in second.attempts
    )
    with llm_module._model_quota_cooldowns_lock:
        llm_module._model_quota_cooldowns.clear()


def test_google_genai_daily_quota_guard_skips_exhausted_model(monkeypatch) -> None:
    client = object.__new__(LLMClient)
    client.settings = fake_settings(
        llm_provider="google_genai",
        primary_llm_model="gemini-primary",
        llm_fallback_models="gemini-backup",
        llm_quota_hard_routing_enabled=True,
    )
    client.rotator = APIKeyRotator(["key"])
    calls = []

    monkeypatch.setattr(llm_module, "import_module", lambda name: object())
    monkeypatch.setattr(client, "_daily_quota_exhausted_model_keys", lambda: {"gemini-primary"})

    def fake_call(prompt: str, api_key: str, *, model: str, **_kwargs) -> str:
        calls.append((prompt, api_key, model))
        return "ok"

    monkeypatch.setattr(client, "_call_google_genai", fake_call)

    result = client._generate_with_google_genai("prompt")

    assert result.text == "ok"
    assert calls == [("prompt", "key", "gemini-backup")]
    assert result.attempts[0]["model"] == "gemini-primary"
    assert result.attempts[0]["outcome"] == "quota_daily_exhausted"
    assert result.attempts[-1]["model"] == "gemini-backup"
    assert result.attempts[-1]["outcome"] == "success"


def test_google_genai_unavailable_falls_back_to_existing_gemini_http(monkeypatch) -> None:
    client = object.__new__(LLMClient)
    client.settings = fake_settings(llm_provider="google-genai")
    client.rotator = APIKeyRotator(["gemini-key"])

    def missing_google_genai(name: str):
        if name == "google.genai":
            raise ImportError("missing")
        return object()

    monkeypatch.setattr("app.services.llm_client.import_module", missing_google_genai)
    monkeypatch.setattr(client, "_call_gemini", lambda prompt, api_key, **_kwargs: "direct ok")

    result = client.generate_with_metadata("prompt")

    assert result.text == "direct ok"
    assert result.provider == "gemini_http"


def test_call_google_genai_uses_official_sdk_shape(monkeypatch) -> None:
    client = object.__new__(LLMClient)
    client.settings = fake_settings(primary_llm_model="gemini-test")
    captured = {}

    class FakeModels:
        def generate_content(self, **kwargs):
            captured["generate_content"] = kwargs
            return SimpleNamespace(text="sdk text")

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.models = FakeModels()

    fake_module = SimpleNamespace(Client=FakeClient)
    fake_types = SimpleNamespace(GenerateContentConfig=lambda **kwargs: {"config": kwargs})
    monkeypatch.setattr(
        "app.services.llm_client.import_module",
        lambda name: fake_module if name == "google.genai" else fake_types,
    )

    text = client._call_google_genai("prompt", "google-key", timeout_seconds=20)

    assert text == "sdk text"
    assert captured["client"] == {"api_key": "google-key"}
    assert captured["generate_content"]["model"] == "gemini-test"
    assert captured["generate_content"]["contents"] == "prompt"
    assert captured["generate_content"]["config"] == {
        "config": {"temperature": 0.2, "top_p": 0.8, "max_output_tokens": 8192}
    }


def test_llm_client_vision_uses_litellm_image_payload(monkeypatch) -> None:
    client = object.__new__(LLMClient)
    client.settings = fake_settings(
        llm_provider="litellm",
        primary_llm_model="gpt-4o-mini",
        openai_api_key="openai-key",
    )
    client.rotator = APIKeyRotator([])
    captured = {}

    monkeypatch.setattr("app.services.llm_client.import_module", lambda name: object())

    def fake_call(prompt: str, *, images, model: str, api_key: str | None = None, **_kwargs) -> str:
        captured["prompt"] = prompt
        captured["images"] = images
        captured["model"] = model
        captured["api_key"] = api_key
        return "vision ok"

    monkeypatch.setattr(client, "_call_litellm_vision", fake_call)

    result = client.generate_vision_with_metadata(
        "read table",
        images=[{"mime_type": "image/png", "data": b"page-bytes"}],
    )

    assert result.text == "vision ok"
    assert result.provider == "litellm"
    assert result.model == "gpt-4o-mini"
    assert result.observability["operation"] == "vision_completion"
    assert captured == {
        "prompt": "read table",
        "images": [{"mime_type": "image/png", "base64": "cGFnZS1ieXRlcw=="}],
        "model": "gpt-4o-mini",
        "api_key": "openai-key",
    }


def test_llm_client_vision_can_use_gemini_http(monkeypatch) -> None:
    client = object.__new__(LLMClient)
    client.settings = fake_settings(llm_provider="gemini_http", primary_llm_model="gemini-vision")
    client.rotator = APIKeyRotator(["gemini-key"])
    captured = {}

    def fake_call(prompt: str, *, images, api_key: str, model: str, **_kwargs) -> str:
        captured["prompt"] = prompt
        captured["images"] = images
        captured["api_key"] = api_key
        captured["model"] = model
        return "gemini vision ok"

    monkeypatch.setattr(client, "_call_gemini_vision", fake_call)

    result = client.generate_vision_with_metadata(
        "read table",
        images=[{"mime_type": "image/png", "base64": "already-encoded"}],
        model="gemini-vision-override",
    )

    assert result.text == "gemini vision ok"
    assert result.provider == "gemini_http"
    assert result.model == "gemini-vision-override"
    assert captured == {
        "prompt": "read table",
        "images": [{"mime_type": "image/png", "base64": "already-encoded"}],
        "api_key": "gemini-key",
        "model": "gemini-vision-override",
    }


def test_llm_client_vision_skips_gemma_text_fallback(monkeypatch) -> None:
    client = object.__new__(LLMClient)
    client.settings = fake_settings(
        llm_provider="gemini_http",
        primary_llm_model="gemma-4-31b-it",
        llm_fallback_models="gemini-2.5-flash",
    )
    client.rotator = APIKeyRotator(["gemini-key"])
    calls = []

    def fake_call(prompt: str, *, images, api_key: str, model: str, **_kwargs) -> str:
        calls.append(model)
        return "vision ok"

    monkeypatch.setattr(client, "_call_gemini_vision", fake_call)

    result = client.generate_vision_with_metadata(
        "read table",
        images=[{"mime_type": "image/png", "base64": "already-encoded"}],
    )

    assert result.text == "vision ok"
    assert result.model == "gemini-2.5-flash"
    assert calls == ["gemini-2.5-flash"]


def test_summarize_llm_attempts_classifies_provider_fallback_failures() -> None:
    summary = summarize_llm_attempts(
        (
            {
                "provider": "litellm",
                "model": "gemini/gemini-primary",
                "outcome": "http_error",
                "status": 429,
                "retryable": True,
            },
            {
                "provider": "litellm",
                "model": "anthropic/claude-3-5-haiku",
                "outcome": "provider_error",
                "error": "APIConnectionError",
                "retryable": True,
            },
            {
                "provider": "gemini_http",
                "model": "gemini-test",
                "outcome": "success",
            },
        )
    )

    assert summary == {
        "attempt_count": 3,
        "providers_tried": ["litellm", "gemini_http"],
        "models_tried": ["gemini/gemini-primary", "anthropic/claude-3-5-haiku", "gemini-test"],
        "outcome_counts": {"http_error": 1, "provider_error": 1, "success": 1},
        "failure_category_counts": {"provider_error": 1, "rate_limited": 1},
        "http_status_counts": {"429": 1},
        "failed_attempt_count": 2,
        "successful_attempt_count": 1,
        "retryable_failure_count": 2,
        "retry_used": False,
        "success_after_failure": True,
        "provider_fallback_used": True,
        "model_fallback_used": True,
        "fallback_path_used": True,
        "primary_failure_category": "rate_limited",
        "last_failure_category": "provider_error",
        "primary_provider": "litellm",
        "primary_model": "gemini/gemini-primary",
        "final_provider": "gemini_http",
        "final_model": "gemini-test",
        "final_outcome": "success",
        "final_success": True,
    }
