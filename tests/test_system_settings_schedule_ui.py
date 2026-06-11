from __future__ import annotations

from typing import Any

from app.ui import system_settings_schedule


class FakeScheduleStreamlit:
    def __init__(
        self,
        *,
        checked: dict[str, bool] | None = None,
        pressed: set[str] | None = None,
    ) -> None:
        self.checked = checked or {}
        self.pressed = pressed or set()
        self.buttons: list[dict[str, Any]] = []
        self.captions: list[str] = []
        self.checkboxes: list[dict[str, Any]] = []

    def __enter__(self) -> "FakeScheduleStreamlit":
        return self

    def __exit__(self, *_args) -> bool:
        return False

    def button(self, label: str, **kwargs):
        self.buttons.append({"label": label, **kwargs})
        return label in self.pressed and not kwargs.get("disabled")

    def caption(self, body: str) -> None:
        self.captions.append(str(body))

    def checkbox(self, label: str, *, value: bool = False, key: str):
        self.checkboxes.append({"label": label, "value": value, "key": key})
        return self.checked.get(key, value)

    def code(self, *_args, **_kwargs) -> None:
        return None

    def columns(self, count_or_spec, **_kwargs):
        count = count_or_spec if isinstance(count_or_spec, int) else len(count_or_spec)
        return [self for _ in range(count)]

    def expander(self, *_args, **_kwargs):
        return self

    def info(self, _body: str) -> None:
        return None

    def multiselect(self, _label: str, *, options, default, **_kwargs):
        return list(default or options[:1])

    def number_input(self, _label: str, *, value, **_kwargs):
        return value

    def selectbox(self, _label: str, *, options, index: int = 0, **_kwargs):
        return list(options)[index]

    def text_input(self, _label: str, *, value: str = "", **_kwargs):
        return value

    def toggle(self, _label: str, *, value: bool = False, **_kwargs):
        return value


def _schedule_config() -> dict[str, Any]:
    return {
        "enabled": True,
        "task": "latest_report_update",
        "hour": 15,
        "minute": 30,
        "topic": "",
        "tickers": ["2330"],
        "lookback_days": 120,
        "force_refresh": False,
        "refresh_company_filings": True,
        "rerun_report": True,
        "maintenance_cleanup_enabled": True,
        "maintenance_cleanup_hour": 3,
        "maintenance_cleanup_minute": 20,
        "maintenance_cleanup_failed_runs": False,
        "maintenance_cleanup_orphan_report_refs": True,
        "maintenance_cleanup_latest_reports_only": True,
        "maintenance_cleanup_stale_running_minutes": 240,
        "timezone": "Asia/Taipei",
    }


def test_schedule_settings_save_requires_confirmation_before_submit(monkeypatch) -> None:
    fake_st = FakeScheduleStreamlit(pressed={"儲存排程設定"})
    saved: list[dict[str, Any]] = []

    monkeypatch.setattr(system_settings_schedule, "st", fake_st)
    monkeypatch.setattr(system_settings_schedule, "render_section_header", lambda *_args: None)
    monkeypatch.setattr(system_settings_schedule, "_load_schedule_config", _schedule_config)
    monkeypatch.setattr(
        system_settings_schedule,
        "_save_schedule_config",
        lambda **payload: saved.append(payload),
    )

    system_settings_schedule.render_schedule_tab(["2330", "2382"])

    assert fake_st.checkboxes == [
        {
            "label": "我了解這會更新自動排程與每日維護設定",
            "value": False,
            "key": "confirm_schedule_settings_save",
        }
    ]
    assert any("避免誤觸排程變更" in caption for caption in fake_st.captions)
    assert {"label": "儲存排程設定", "type": "primary", "disabled": True} in fake_st.buttons
    assert saved == []


def test_schedule_settings_save_submits_after_confirmation(monkeypatch) -> None:
    fake_st = FakeScheduleStreamlit(
        checked={"confirm_schedule_settings_save": True},
        pressed={"儲存排程設定"},
    )
    saved: list[dict[str, Any]] = []

    monkeypatch.setattr(system_settings_schedule, "st", fake_st)
    monkeypatch.setattr(system_settings_schedule, "render_section_header", lambda *_args: None)
    monkeypatch.setattr(system_settings_schedule, "_load_schedule_config", _schedule_config)
    monkeypatch.setattr(
        system_settings_schedule,
        "_save_schedule_config",
        lambda **payload: saved.append(payload),
    )

    system_settings_schedule.render_schedule_tab(["2330", "2382"])

    assert {"label": "儲存排程設定", "type": "primary", "disabled": False} in fake_st.buttons
    assert saved == [
        {
            "enabled": True,
            "task": "latest_report_update",
            "hour": 15,
            "minute": 30,
            "topic": "",
            "tickers": ["2330"],
            "lookback_days": 120,
            "force_refresh": False,
            "rerun_report": True,
            "refresh_company_filings": True,
            "maintenance_cleanup_enabled": True,
            "maintenance_cleanup_hour": 3,
            "maintenance_cleanup_minute": 20,
            "maintenance_cleanup_failed_runs": False,
            "maintenance_cleanup_orphan_report_refs": True,
            "maintenance_cleanup_latest_reports_only": True,
            "maintenance_cleanup_stale_running_minutes": 240,
        }
    ]
