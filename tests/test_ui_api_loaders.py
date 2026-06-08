from __future__ import annotations

from types import SimpleNamespace

import requests

from app.ui import api_loaders


class FakeStreamlit:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)


def test_load_api_json_or_default_returns_api_payload(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    captured = {}
    monkeypatch.setattr(api_loaders, "st", fake_st)

    def fake_api_get(path: str, *, timeout: float = 10) -> dict:
        captured.update({"path": path, "timeout": timeout})
        return {"ok": True}

    monkeypatch.setattr(api_loaders, "api_get", fake_api_get)

    assert api_loaders.load_api_json_or_default(
        "/services/status",
        {},
        error_message="讀取服務狀態失敗",
        timeout=3,
    ) == {"ok": True}
    assert captured == {"path": "/services/status", "timeout": 3}
    assert fake_st.errors == []


def test_load_api_json_or_default_reports_error_and_copies_fallback(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    fallback = {"items": []}
    monkeypatch.setattr(api_loaders, "st", fake_st)

    response = SimpleNamespace(json=lambda: {"detail": "status endpoint down"})
    exc = requests.HTTPError("500 Server Error")
    exc.response = response

    def fake_api_get(path: str) -> dict:
        raise exc

    monkeypatch.setattr(api_loaders, "api_get", fake_api_get)

    result = api_loaders.load_api_json_or_default(
        "/services/status",
        fallback,
        error_message="讀取服務狀態失敗",
    )

    assert result == {"items": []}
    assert result is not fallback
    result["items"].append("mutated")
    assert fallback == {"items": []}
    assert fake_st.errors == ["讀取服務狀態失敗：status endpoint down"]
