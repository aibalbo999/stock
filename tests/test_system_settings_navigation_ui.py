from __future__ import annotations

import app.ui.system_settings as system_settings
from app.ui.system_settings import (
    maintenance_focus_from_pending_section,
    settings_section_label,
)


def test_settings_section_label_routes_maintenance_and_ai_quota_to_maintenance_view() -> None:
    assert settings_section_label("maintenance") == "維護"
    assert settings_section_label("ai_quota") == "維護"


def test_maintenance_focus_from_pending_section_preserves_ai_quota_route() -> None:
    assert maintenance_focus_from_pending_section("ai_quota") == "ai_quota"
    assert maintenance_focus_from_pending_section("maintenance") is None
    assert maintenance_focus_from_pending_section("schedule") is None
    assert maintenance_focus_from_pending_section(None) is None


def test_settings_section_label_defaults_to_scope_for_unknown_route() -> None:
    assert settings_section_label(None) == "股票範圍"
    assert settings_section_label("unknown") == "股票範圍"


def test_render_system_settings_preserves_ai_quota_focus(monkeypatch) -> None:
    class FakeWhitelist:
        def allowed_tickers(self) -> set[str]:
            return {"2330"}

    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = {"pending_settings_section": "ai_quota"}

        def radio(self, _label, options, **_kwargs):
            return self.session_state["settings_section"]

    fake_st = FakeStreamlit()
    rendered: list[str] = []
    monkeypatch.setattr(system_settings, "st", fake_st)
    monkeypatch.setattr(system_settings, "SupplyChainWhitelist", FakeWhitelist)
    monkeypatch.setattr(system_settings, "render_scope_tab", lambda _whitelist: rendered.append("scope"))
    monkeypatch.setattr(system_settings, "render_schedule_tab", lambda _tickers: rendered.append("schedule"))
    monkeypatch.setattr(system_settings, "render_maintenance_tab", lambda: rendered.append("maintenance"))

    system_settings.render_system_settings()

    assert fake_st.session_state["settings_section"] == "維護"
    assert fake_st.session_state["pending_maintenance_focus"] == "ai_quota"
    assert rendered == ["maintenance"]
