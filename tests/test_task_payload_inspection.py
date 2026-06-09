from __future__ import annotations

from app.services.task_payload_inspection import (
    redact_sensitive_text,
    safe_key_names,
    sensitive_key_count,
    ticker_count,
    truncate_preview,
)


def test_payload_inspection_redacts_sensitive_keys_and_counts_nested_values() -> None:
    payload = {
        "topic": "AI 產業鏈",
        "api_key": "secret",
        "request": {
            "tickers": ["2330", "", "2330", "2454"],
            "headers": {"Authorization": "Bearer hidden"},
        },
        "items": [{"password": "pw"}, {"token": "tok"}],
    }

    assert safe_key_names(payload) == ["<sensitive>", "items", "request", "topic"]
    assert sensitive_key_count(payload) == 4
    assert ticker_count(payload) == 2


def test_payload_inspection_redacts_secret_assignments_and_truncates_preview() -> None:
    assert (
        redact_sensitive_text("api_key=abc authorization:Bearer123 password = pw ok")
        == "api_key=<redacted> authorization:<redacted> password = <redacted> ok"
    )

    assert truncate_preview("abc", limit=4) == "abc"
    assert truncate_preview("abcdef", limit=4) == "abc…"
