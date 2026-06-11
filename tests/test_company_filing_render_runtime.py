from types import SimpleNamespace

from app.core.config import get_settings
from app.data_sources.company_filings import (
    company_filing_browser_render_configured,
    company_filing_browser_render_configuration_check,
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
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_PROVIDER", "browserless")
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
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_PROVIDER", "browserless")
    monkeypatch.delenv("COMPANY_FILING_BROWSER_RENDER_TOKEN", raising=False)
    get_settings.cache_clear()

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

    def fake_create_connection(address, timeout):
        captured["address"] = address
        captured["timeout"] = timeout
        return FakeSocket()

    monkeypatch.setattr(
        "app.data_sources.company_filing_render.socket.create_connection", fake_create_connection
    )

    try:
        status = company_filing_browser_render_status(
            enabled=True,
            endpoint="http://127.0.0.1:3000/content?token=secret",
            timeout_seconds=0.5,
        )
    finally:
        get_settings.cache_clear()

    assert captured == {"address": ("127.0.0.1", 3000), "timeout": 0.5}
    assert status["configuration_ready"] is True
    assert status["configuration_check"]["status"] == "ready"
    assert status["url_configured"] is True
    assert status["token_required"] is False
    assert status["token_configured"] is False
    assert status["connection_checked"] is True
    assert status["smoke_cli"].endswith("--url https://example.com/ --json")
    assert status["endpoint_reachable"] is True
    assert status["runtime_available"] is True
    assert status["fallback_reason"] is None


def test_company_filing_browser_render_status_reports_unreachable_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_PROVIDER", "browserless")
    monkeypatch.delenv("COMPANY_FILING_BROWSER_RENDER_TOKEN", raising=False)
    get_settings.cache_clear()

    def fake_create_connection(address, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(
        "app.data_sources.company_filing_render.socket.create_connection", fake_create_connection
    )

    try:
        status = company_filing_browser_render_status(
            enabled=True,
            endpoint="http://127.0.0.1:3000/content?token=secret",
            timeout_seconds=0.5,
        )
    finally:
        get_settings.cache_clear()

    assert status["configuration_ready"] is True
    assert status["connection_checked"] is True
    assert status["endpoint_reachable"] is False
    assert status["runtime_available"] is False
    assert status["fallback_reason"] == "browser_render_endpoint_unreachable:TimeoutError"


def test_company_filing_browser_render_configuration_accepts_flaresolverr_without_token() -> None:
    status = company_filing_browser_render_configuration_check(
        enabled=True,
        provider="flaresolverr",
        endpoint="http://127.0.0.1:8191/v1",
        token="",
    )

    assert status["ready"] is True
    assert status["status"] == "ready"
    assert status["provider_supported"] is True
    assert status["token_required"] is False
    assert status["endpoint_valid"] is True


def test_company_filing_browser_render_requires_token_for_managed_unlocker(monkeypatch) -> None:
    def fail_create_connection(address, timeout):
        raise AssertionError("socket check should wait until configuration is complete")

    monkeypatch.setattr(
        "app.data_sources.company_filing_render.socket.create_connection", fail_create_connection
    )
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_PROVIDER", "scrapingbee")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_URL", "https://app.scrapingbee.com/api/v1")
    monkeypatch.delenv("COMPANY_FILING_BROWSER_RENDER_TOKEN", raising=False)
    get_settings.cache_clear()
    try:
        assert company_filing_browser_render_configured() is False
        status = company_filing_browser_render_status()
    finally:
        get_settings.cache_clear()

    assert status["configuration_ready"] is False
    assert status["configuration_check"]["status"] == "missing_required_env"
    assert status["configuration_check"]["missing_env_keys"] == [
        "COMPANY_FILING_BROWSER_RENDER_TOKEN"
    ]
    assert status["token_required"] is True
    assert status["token_configured"] is False
    assert status["connection_checked"] is False
    assert status["runtime_available"] is False
    assert status["fallback_reason"] == "missing_browser_render_token"


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
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "false")
    monkeypatch.setattr(
        "app.data_sources.company_filing_render.company_filing_playwright_available", lambda: False
    )
    get_settings.cache_clear()
    try:
        assert company_filing_render_fallback_configured() is False
    finally:
        get_settings.cache_clear()


def test_company_filing_playwright_browser_status_requires_installed_browser(
    monkeypatch, tmp_path
) -> None:
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

    monkeypatch.setattr(
        "app.data_sources.company_filing_render.company_filing_playwright_available", lambda: True
    )
    monkeypatch.setattr(
        "app.data_sources.company_filing_render.importlib.import_module", fake_import_module
    )

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

    monkeypatch.setattr(
        "app.data_sources.company_filing_render.company_filing_playwright_available", lambda: True
    )
    monkeypatch.setattr(
        "app.data_sources.company_filing_render.importlib.import_module",
        lambda name: SimpleNamespace(sync_playwright=lambda: FakePlaywrightContext()),
    )

    status = company_filing_playwright_browser_status("chromium")

    assert status["dependency_available"] is True
    assert status["browser_available"] is False
    assert status["fallback_reason"].startswith("missing_browser_binary:chromium")
