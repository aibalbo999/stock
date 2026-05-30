from types import SimpleNamespace

import httpx

from app.services.llm_client import APIKeyRotator, LLMClient, get_shared_rotator


def fake_settings(**overrides) -> SimpleNamespace:
    defaults = {
        "primary_llm_model": "gemini-test",
        "llm_max_retries_per_key": 2,
        "llm_base_retry_delay_seconds": 0.5,
        "llm_max_retry_delay_seconds": 5.0,
        "llm_total_timeout_seconds": 60.0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_api_key_rotator_advances_starting_key() -> None:
    rotator = APIKeyRotator(["a", "b", "c"])

    assert rotator.candidates() == [(0, "a"), (1, "b"), (2, "c")]
    assert rotator.candidates() == [(1, "b"), (2, "c"), (0, "a")]


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
