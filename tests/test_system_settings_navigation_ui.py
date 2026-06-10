from __future__ import annotations

from app.ui.system_settings import settings_section_label


def test_settings_section_label_routes_maintenance_and_ai_quota_to_maintenance_view() -> None:
    assert settings_section_label("maintenance") == "維護"
    assert settings_section_label("ai_quota") == "維護"


def test_settings_section_label_defaults_to_scope_for_unknown_route() -> None:
    assert settings_section_label(None) == "股票範圍"
    assert settings_section_label("unknown") == "股票範圍"
