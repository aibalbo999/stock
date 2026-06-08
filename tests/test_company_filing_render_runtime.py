from types import SimpleNamespace

from app.core.config import get_settings
from app.data_sources.company_filings import (
    company_filing_browser_render_configured,
    company_filing_browser_render_provider,
    company_filing_browser_render_provider_capability,
    company_filing_browser_render_status,
    company_filing_playwright_browser_status,
    company_filing_playwright_render_enabled,
    company_filing_render_fallback_configured,
)


def test_company_filing_browser_render_is_explicitly_configured(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_URL", "https://browserless.example/content")
    get_settings.cache_clear()
    try:
        assert company_filing_browser_render_configured() is True
        assert company_filing_browser_render_provider() == "browserless"
    finally:
        get_settings.cache_clear()


def test_company_filing_browser_render_provider_capability_labels_unlockers() -> None:
    assert company_filing_browser_render_provider_capability("browserless") == {
        "provider": "browserless",
        "tier": "browser_render",
        "captcha_unlocker": False,
        "purpose": "JavaScript rendering and browser-like page fetches.",
    }
    flaresolverr = company_filing_browser_render_provider_capability("flaresolverr")

    assert flaresolverr["tier"] == "unlocker"
    assert flaresolverr["captcha_unlocker"] is True


def test_company_filing_browser_render_status_checks_endpoint_reachability(monkeypatch) -> None:
    captured = {}

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

    def fake_create_connection(address, timeout):
        captured["address"] = address
        captured["timeout"] = timeout
        return FakeSocket()

    monkeypatch.setattr("app.data_sources.company_filing_render.socket.create_connection", fake_create_connection)

    status = company_filing_browser_render_status(
        enabled=True,
        endpoint="http://127.0.0.1:3000/content?token=secret",
        timeout_seconds=0.5,
    )

    assert captured == {"address": ("127.0.0.1", 3000), "timeout": 0.5}
    assert status["url_configured"] is True
    assert status["connection_checked"] is True
    assert status["smoke_cli"].endswith("--url https://example.com/ --json")
    assert status["endpoint_reachable"] is True
    assert status["runtime_available"] is True
    assert status["fallback_reason"] is None


def test_company_filing_browser_render_status_reports_unreachable_endpoint(monkeypatch) -> None:
    def fake_create_connection(address, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr("app.data_sources.company_filing_render.socket.create_connection", fake_create_connection)

    status = company_filing_browser_render_status(
        enabled=True,
        endpoint="http://127.0.0.1:3000/content?token=secret",
        timeout_seconds=0.5,
    )

    assert status["connection_checked"] is True
    assert status["endpoint_reachable"] is False
    assert status["runtime_available"] is False
    assert status["fallback_reason"] == "browser_render_endpoint_unreachable:TimeoutError"


def test_company_filing_playwright_render_is_enabled_by_default() -> None:
    get_settings.cache_clear()
    try:
        assert company_filing_playwright_render_enabled() is True
    finally:
        get_settings.cache_clear()


def test_company_filing_playwright_render_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", "false")
    get_settings.cache_clear()
    try:
        assert company_filing_playwright_render_enabled() is False
    finally:
        get_settings.cache_clear()


def test_company_filing_render_fallback_ignores_playwright_without_dependency(monkeypatch) -> None:
    monkeypatch.setattr("app.data_sources.company_filing_render.company_filing_playwright_available", lambda: False)
    get_settings.cache_clear()
    try:
        assert company_filing_render_fallback_configured() is False
    finally:
        get_settings.cache_clear()


def test_company_filing_playwright_browser_status_requires_installed_browser(monkeypatch, tmp_path) -> None:
    executable = tmp_path / "chromium"
    executable.write_text("#!/bin/sh\n")

    class FakeLauncher:
        executable_path = str(executable)

    class FakePlaywrightContext:
        def __enter__(self):
            return SimpleNamespace(chromium=FakeLauncher())

        def __exit__(self, exc_type, exc, traceback):
            return None

    def fake_import_module(name):
        if name == "playwright.sync_api":
            return SimpleNamespace(sync_playwright=lambda: FakePlaywrightContext())
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("app.data_sources.company_filing_render.company_filing_playwright_available", lambda: True)
    monkeypatch.setattr("app.data_sources.company_filing_render.importlib.import_module", fake_import_module)

    status = company_filing_playwright_browser_status("chromium")

    assert status["dependency_available"] is True
    assert status["browser_available"] is True
    assert status["browser_executable_exists"] is True
    assert status["fallback_reason"] is None


def test_company_filing_playwright_browser_status_reports_missing_browser_binary(
    monkeypatch,
    tmp_path,
) -> None:
    missing_executable = tmp_path / "missing-chromium"

    class FakeLauncher:
        executable_path = str(missing_executable)

    class FakePlaywrightContext:
        def __enter__(self):
            return SimpleNamespace(chromium=FakeLauncher())

        def __exit__(self, exc_type, exc, traceback):
            return None

    monkeypatch.setattr("app.data_sources.company_filing_render.company_filing_playwright_available", lambda: True)
    monkeypatch.setattr(
        "app.data_sources.company_filing_render.importlib.import_module",
        lambda name: SimpleNamespace(sync_playwright=lambda: FakePlaywrightContext()),
    )

    status = company_filing_playwright_browser_status("chromium")

    assert status["dependency_available"] is True
    assert status["browser_available"] is False
    assert status["fallback_reason"].startswith("missing_browser_binary:chromium")
