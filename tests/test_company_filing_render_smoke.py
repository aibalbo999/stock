from __future__ import annotations

import asyncio
import json
from datetime import date
from types import SimpleNamespace

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


def test_company_filing_render_provider_contract_format_uses_operator_language() -> None:
    rendered = smoke.format_company_filing_render_provider_contract(
        {
            "status": "ready",
            "ready": True,
            "provider_count": 1,
            "providers": [{"provider": "browserless", "ready": True, "method": "POST"}],
        }
    )

    assert "公司文件渲染提供者格式檢查: ready" in rendered
    assert "- 就緒: 是" in rendered
    assert "- 提供者數: 1" in rendered
    assert "Company filing render provider contract" not in rendered
    assert "provider count" not in rendered
    assert "- 就緒: true" not in rendered


def test_company_filing_render_smoke_format_uses_operator_language() -> None:
    rendered = smoke.format_company_filing_render_smoke(
        {
            "status": "not_configured",
            "ready": False,
            "url": "https://example.com/",
            "proxy_count": 0,
            "browser_render_runtime": {
                "provider": "flaresolverr",
                "fallback_reason": "browser_render_disabled",
            },
            "playwright_render_runtime": {
                "browser": "chromium",
                "fallback_reason": "missing_browser_binary:chromium",
            },
            "smoke_command": ".venv/bin/python scripts/company_filing_render_smoke.py --json",
        }
    )

    assert "公司文件渲染後援檢查: not_configured" in rendered
    assert "- 就緒: 否" in rendered
    assert "- 代理數: 0" in rendered
    assert "- 瀏覽器渲染: flaresolverr / browser_render_disabled" in rendered
    assert "- 指令: .venv/bin/python scripts/company_filing_render_smoke.py --json" in rendered
    assert "Company filing render smoke" not in rendered
    assert "proxy count" not in rendered
    assert "browser render:" not in rendered
    assert "- 就緒: false" not in rendered


def test_company_filing_render_smoke_help_uses_operator_language(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        smoke.main(["--help"])

    output = capsys.readouterr().out
    assert exc_info.value.code == 0
    assert "檢查公司文件瀏覽器/代理渲染後援是否可用" in output
    assert "要渲染或抓取的公開 URL" in output
    assert "不連網檢查渲染/解鎖提供者的請求與回應格式" in output
    assert "Smoke-test" not in output
    assert "Minimum parsed text length" not in output
    assert "request and response contracts" not in output


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
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "false")
    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", "false")
    monkeypatch.setattr(smoke, "company_filing_browser_render_status", lambda: _browser_runtime())
    monkeypatch.setattr(smoke, "company_filing_playwright_browser_status", lambda _browser: _playwright_runtime())
    monkeypatch.setattr(smoke, "company_filing_proxy_urls", lambda: [])

    report = asyncio.run(smoke.company_filing_render_smoke_report())

    assert report["status"] == "not_configured"
    assert report["ready"] is False
    assert "company_filing_render_smoke.py" in report["smoke_command"]
    assert smoke.smoke_exit_code(report, strict=False) == 0
    assert smoke.smoke_exit_code(report, strict=True) == 1


def test_company_filing_render_smoke_collects_runtime_outside_event_loop(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "false")
    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", "false")

    def fake_playwright_status(_browser):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return _playwright_runtime()
        raise AssertionError("sync Playwright runtime check ran inside the event loop")

    monkeypatch.setattr(smoke, "company_filing_browser_render_status", lambda: _browser_runtime())
    monkeypatch.setattr(smoke, "company_filing_playwright_browser_status", fake_playwright_status)
    monkeypatch.setattr(smoke, "company_filing_proxy_urls", lambda: [])

    report = asyncio.run(smoke.company_filing_render_smoke_report())

    assert report["status"] == "not_configured"


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
    assert "runtime 無法連線或尚未安裝" in report["remediation"]


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


def test_company_filing_render_provider_contract_reports_supported_providers() -> None:
    report = smoke.company_filing_render_provider_contract_report()

    assert report["status"] == "ready"
    assert report["ready"] is True
    assert report["provider_count"] == 5
    providers = {row["provider"]: row for row in report["providers"]}
    assert set(providers) == {
        "brightdata",
        "browserless",
        "flaresolverr",
        "generic",
        "scrapingbee",
    }
    assert providers["flaresolverr"]["method"] == "POST"
    assert providers["flaresolverr"]["request_contract"]["json_keys"] == [
        "cmd",
        "maxTimeout",
        "url",
    ]
    assert providers["flaresolverr"]["response_contract"]["final_url"].endswith(
        "/rendered"
    )
    assert providers["scrapingbee"]["method"] == "GET"
    assert providers["scrapingbee"]["request_contract"]["param_keys"] == [
        "api_key",
        "render_js",
        "url",
    ]
    assert providers["brightdata"]["request_contract"][
        "authorization_header_configured"
    ] is True
    assert "--provider-contract" in report["smoke_command"]
    assert smoke.smoke_exit_code(report, strict=True) == 0


def test_company_filing_render_smoke_main_prints_json(monkeypatch, capsys) -> None:
    async def fake_report(**_kwargs):
        return {"status": "ready", "ready": True}

    monkeypatch.setattr(smoke, "company_filing_render_smoke_report", fake_report)

    assert smoke.main(["--json"]) == 0
    assert '"status": "ready"' in capsys.readouterr().out


def test_company_filing_render_smoke_main_can_apply_local_unlocker_defaults(
    monkeypatch,
    capsys,
) -> None:
    class FakeSettingsProvider:
        def __init__(self) -> None:
            self.clear_count = 0

        def __call__(self):
            return SimpleNamespace(
                company_filing_proxy_urls="",
                company_filing_browser_render_enabled=False,
                company_filing_browser_render_url="",
                company_filing_playwright_render_enabled=True,
            )

        def cache_clear(self) -> None:
            self.clear_count += 1

    provider = FakeSettingsProvider()

    async def fake_report(**_kwargs):
        return {
            "status": "ready",
            "ready": True,
            "provider": smoke.os.environ.get("COMPANY_FILING_BROWSER_RENDER_PROVIDER"),
            "url": smoke.os.environ.get("COMPANY_FILING_BROWSER_RENDER_URL"),
        }

    monkeypatch.setattr(smoke, "get_settings", provider)
    monkeypatch.setattr(smoke, "company_filing_render_smoke_report", fake_report)
    monkeypatch.setattr(
        smoke,
        "is_local_port_open",
        lambda _host, port: int(port) == smoke.LOCAL_FLARESOLVERR_PORT,
    )
    for key in (
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
        "COMPANY_FILING_PROXY_URLS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", "true")

    assert smoke.main(
        [
            "--local-browser-render-defaults",
            "--prefer-unlocker",
            "--json",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["provider"] == "flaresolverr"
    assert payload["url"] == "http://127.0.0.1:8191/v1"
    assert payload["local_browser_render_defaults"]["prefer_unlocker"] is True
    assert payload["local_browser_render_defaults"]["applied_env_keys"] == [
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
    ]
    assert "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED" not in smoke.os.environ
    assert "--local-browser-render-defaults --prefer-unlocker" in payload["smoke_command"]
    assert provider.clear_count >= 2


def test_company_filing_render_smoke_main_prints_provider_contract_json(capsys) -> None:
    assert smoke.main(["--provider-contract", "--json"]) == 0
    output = capsys.readouterr().out
    assert '"provider_count": 5' in output
    assert '"status": "ready"' in output
