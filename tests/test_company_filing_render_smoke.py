from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app.core.config import get_settings
from app.models.schemas import NewsDocument, Source
from scripts import company_filing_render_smoke as smoke


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _browser_runtime(**overrides) -> dict:
    payload = {
        "enabled": False,
        "provider": "browserless",
        "url_configured": False,
        "runtime_available": False,
        "fallback_reason": "browser_render_disabled",
    }
    payload.update(overrides)
    return payload


def _playwright_runtime(**overrides) -> dict:
    payload = {
        "browser": "chromium",
        "dependency_available": True,
        "browser_available": False,
        "fallback_reason": "missing_browser_binary:chromium",
    }
    payload.update(overrides)
    return payload


def _document(text: str = "Example Domain rendered text") -> NewsDocument:
    return NewsDocument(
        id="rendered-example",
        title="Example Domain",
        text=text,
        source=Source(
            title="Example Domain",
            url="https://example.com/",
            publisher="render smoke",
            published_at=date(2026, 1, 1),
        ),
    )


def test_company_filing_render_smoke_reports_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "company_filing_browser_render_status", lambda: _browser_runtime())
    monkeypatch.setattr(smoke, "company_filing_playwright_browser_status", lambda _browser: _playwright_runtime())
    monkeypatch.setattr(smoke, "company_filing_proxy_urls", lambda: [])

    report = asyncio.run(smoke.company_filing_render_smoke_report())

    assert report["status"] == "not_configured"
    assert report["ready"] is False
    assert "company_filing_render_smoke.py" in report["smoke_command"]
    assert smoke.smoke_exit_code(report, strict=False) == 0
    assert smoke.smoke_exit_code(report, strict=True) == 1


def test_company_filing_render_smoke_uses_browser_render(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "true")
    monkeypatch.setattr(
        smoke,
        "company_filing_browser_render_status",
        lambda: _browser_runtime(
            enabled=True,
            url_configured=True,
            runtime_available=True,
            fallback_reason=None,
        ),
    )
    monkeypatch.setattr(smoke, "company_filing_playwright_browser_status", lambda _browser: _playwright_runtime())
    monkeypatch.setattr(smoke, "company_filing_proxy_urls", lambda: [])

    class FakeFetcher:
        async def _fetch_browser_rendered_url_as_document(self, url: str):
            self.url = url
            return _document()

    fetcher = FakeFetcher()

    report = asyncio.run(
        smoke.company_filing_render_smoke_report(
            url="https://example.com/",
            fetcher=fetcher,
        )
    )

    assert report["status"] == "ready"
    assert report["ready"] is True
    assert report["attempts"][0]["kind"] == "browser_render"
    assert report["attempts"][0]["document"]["published_at"] == "2026-01-01"
    assert fetcher.url == "https://example.com/"


def test_company_filing_render_smoke_reports_unavailable_runtime(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "true")
    monkeypatch.setattr(
        smoke,
        "company_filing_browser_render_status",
        lambda: _browser_runtime(
            enabled=True,
            url_configured=True,
            runtime_available=False,
            fallback_reason="browser_render_endpoint_unreachable:ConnectionRefusedError",
        ),
    )
    monkeypatch.setattr(smoke, "company_filing_playwright_browser_status", lambda _browser: _playwright_runtime())
    monkeypatch.setattr(smoke, "company_filing_proxy_urls", lambda: [])

    report = asyncio.run(smoke.company_filing_render_smoke_report())

    assert report["status"] == "unavailable"
    assert report["ready"] is False
    assert report["attempts"][0]["runnable"] is False
    assert "not reachable or installed" in report["remediation"]


def test_company_filing_render_smoke_uses_playwright_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", "true")
    monkeypatch.setattr(smoke, "company_filing_browser_render_status", lambda: _browser_runtime())
    monkeypatch.setattr(
        smoke,
        "company_filing_playwright_browser_status",
        lambda _browser: _playwright_runtime(browser_available=True, fallback_reason=None),
    )
    monkeypatch.setattr(smoke, "company_filing_proxy_urls", lambda: [])

    class FakeFetcher:
        async def _fetch_playwright_rendered_url_as_document(self, url: str):
            self.url = url
            return _document()

    report = asyncio.run(
        smoke.company_filing_render_smoke_report(fetcher=FakeFetcher())
    )

    assert report["status"] == "ready"
    assert report["attempts"][0]["kind"] == "playwright_render"


def test_company_filing_render_smoke_uses_proxy_fetch(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "company_filing_browser_render_status", lambda: _browser_runtime())
    monkeypatch.setattr(smoke, "company_filing_playwright_browser_status", lambda _browser: _playwright_runtime())
    monkeypatch.setattr(smoke, "company_filing_proxy_urls", lambda: ["http://proxy.example:8080"])

    class FakeFetcher:
        async def _fetch_url_as_document(self, url: str):
            self.url = url
            return _document()

    report = asyncio.run(
        smoke.company_filing_render_smoke_report(fetcher=FakeFetcher())
    )

    assert report["status"] == "ready"
    assert report["proxy_count"] == 1
    assert report["attempts"][0]["kind"] == "proxy_fetch"


def test_company_filing_render_smoke_reports_failed_attempt(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "true")
    monkeypatch.setattr(
        smoke,
        "company_filing_browser_render_status",
        lambda: _browser_runtime(
            enabled=True,
            url_configured=True,
            runtime_available=True,
            fallback_reason=None,
        ),
    )
    monkeypatch.setattr(smoke, "company_filing_playwright_browser_status", lambda _browser: _playwright_runtime())
    monkeypatch.setattr(smoke, "company_filing_proxy_urls", lambda: [])

    class FakeFetcher:
        async def _fetch_browser_rendered_url_as_document(self, _url: str):
            raise TimeoutError("render timed out")

    report = asyncio.run(
        smoke.company_filing_render_smoke_report(fetcher=FakeFetcher())
    )

    assert report["status"] == "failed"
    assert report["attempts"][0]["error"]["category"] == "timeout"
    assert smoke.smoke_exit_code(report, strict=False) == 1


def test_company_filing_render_smoke_main_prints_json(monkeypatch, capsys) -> None:
    async def fake_report(**_kwargs):
        return {"status": "ready", "ready": True}

    monkeypatch.setattr(smoke, "company_filing_render_smoke_report", fake_report)

    assert smoke.main(["--json"]) == 0
    assert '"status": "ready"' in capsys.readouterr().out
