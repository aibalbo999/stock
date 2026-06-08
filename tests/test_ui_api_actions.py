from __future__ import annotations

from types import SimpleNamespace

import requests

from app.ui import api_actions


class FakeStreamlit:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)


def test_run_api_action_or_none_returns_action_result(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(api_actions, "st", fake_st)

    assert api_actions.run_api_action_or_none(
        lambda: {"saved": True},
        error_message="儲存失敗",
    ) == {"saved": True}
    assert fake_st.errors == []


def test_run_api_action_or_none_reports_request_error(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(api_actions, "st", fake_st)

    response = SimpleNamespace(json=lambda: {"detail": "backend offline"})
    exc = requests.HTTPError("500 Server Error")
    exc.response = response

    assert (
        api_actions.run_api_action_or_none(
            lambda: (_ for _ in ()).throw(exc),
            error_message="匯入失敗",
        )
        is None
    )
    assert fake_st.errors == ["匯入失敗：backend offline"]


def test_run_api_action_or_none_reports_value_error(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(api_actions, "st", fake_st)

    assert (
        api_actions.run_api_action_or_none(
            lambda: (_ for _ in ()).throw(ValueError("invalid json")),
            error_message="儲存失敗",
        )
        is None
    )
    assert fake_st.errors == ["儲存失敗：invalid json"]
