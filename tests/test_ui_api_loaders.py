from __future__ import annotations

from types import SimpleNamespace

import requests

from app.ui import api_loaders


class FakeStreamlit:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def info(self, message: str) -> None:
        self.infos.append(message)


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
    assert fake_st.warnings == []


def test_load_api_json_or_default_can_report_warning(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(api_loaders, "st", fake_st)
    monkeypatch.setattr(
        api_loaders,
        "api_get",
        lambda path: (_ for _ in ()).throw(requests.ConnectionError("offline")),
    )

    assert (
        api_loaders.load_api_json_or_default(
            "/reports/7/company-data-audit",
            {},
            error_message="個股資料足夠性檢查失敗",
            notify="warning",
        )
        == {}
    )
    assert fake_st.errors == []
    assert fake_st.warnings == ["個股資料足夠性檢查失敗：offline"]


def test_load_api_json_or_default_can_suppress_notification(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(api_loaders, "st", fake_st)
    monkeypatch.setattr(
        api_loaders,
        "api_get",
        lambda path: (_ for _ in ()).throw(requests.ConnectionError("offline")),
    )

    assert api_loaders.load_api_json_or_default(
        "/reports/7/follow-up/plan",
        {"_load_error": True},
        error_message="讀取補強任務預覽失敗",
        notify="none",
    ) == {"_load_error": True}
    assert fake_st.errors == []
    assert fake_st.warnings == []
    assert fake_st.infos == []


def test_load_api_json_or_default_reports_not_found_info(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(api_loaders, "st", fake_st)

    response = SimpleNamespace(status_code=404, json=lambda: {"detail": "not found"})
    exc = requests.HTTPError("404 Client Error")
    exc.response = response
    monkeypatch.setattr(
        api_loaders,
        "api_get",
        lambda path: (_ for _ in ()).throw(exc),
    )

    assert (
        api_loaders.load_api_json_or_default(
            "/tasks/task-1/run",
            None,
            error_message="查詢失敗",
            not_found_message="尚未找到對應紀錄；任務剛送出時可能需要等待。",
        )
        is None
    )
    assert fake_st.errors == []
    assert fake_st.warnings == []
    assert fake_st.infos == ["尚未找到對應紀錄；任務剛送出時可能需要等待。"]
