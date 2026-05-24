from types import SimpleNamespace

import httpx

from app.services.llm_client import APIKeyRotator, LLMClient, get_shared_rotator


def test_api_key_rotator_advances_starting_key() -> None:
    rotator = APIKeyRotator(["a", "b", "c"])

    assert rotator.candidates() == [(0, "a"), (1, "b"), (2, "c")]
    assert rotator.candidates() == [(1, "b"), (2, "c"), (0, "a")]


def test_llm_client_rotates_after_retryable_error(monkeypatch) -> None:
    client = object.__new__(LLMClient)
    client.settings = SimpleNamespace(primary_llm_model="gemini-test")
    client.rotator = APIKeyRotator(["bad-key", "good-key"])
    calls = []

    def fake_call(prompt: str, api_key: str) -> str:
        calls.append((prompt, api_key))
        if api_key == "bad-key":
            response = httpx.Response(429, request=httpx.Request("POST", "https://example.test"))
            raise httpx.HTTPStatusError("rate limited", request=response.request, response=response)
        return "ok"

    monkeypatch.setattr(client, "_call_gemini", fake_call)

    result = client.generate_with_metadata("prompt")

    assert result.text == "ok"
    assert result.key_index == 1
    assert calls == [("prompt", "bad-key"), ("prompt", "good-key")]


def test_shared_rotator_reuses_same_pool() -> None:
    first = get_shared_rotator(["shared-a", "shared-b"])
    second = get_shared_rotator(["shared-a", "shared-b"])

    assert first is second
    assert first.candidates()[0] == (0, "shared-a")
    assert second.candidates()[0] == (1, "shared-b")
