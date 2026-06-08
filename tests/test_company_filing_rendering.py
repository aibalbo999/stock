import asyncio
from datetime import date
from types import SimpleNamespace

import httpx

from app.core.config import get_settings
from app.data_sources.company_filings import (
    CompanyFilingFetcher,
)
from app.data_sources.news import NewsFetcher


def test_company_filing_fetch_url_document_refreshes_bad_cache_with_browser_render(monkeypatch) -> None:
    cached = NewsFetcher.from_manual_text(
        title="台積電 年報",
        text="台積電 年報 請啟用 JavaScript 後查看文件內容。" * 8,
        publisher="cached publisher",
        url="https://investor.tsmc.com/annual-report",
    )
    stored = {}

    class FakeCache:
        def get_url_document(self, url, *, parser, extract_tables, html_extract_tables):
            return cached

        def set_url_document(self, url, document, *, parser, extract_tables, html_extract_tables):
            stored["url"] = url
            stored["title"] = document.title

    async def blocked_direct_fetch(self, url, publisher=None):
        return cached

    async def fake_browser_render(self, url, publisher=None):
        return NewsFetcher.from_manual_text(
            title="台積電 2026 年報",
            text="台積電 2026 年報 annual report 揭露 AI/HPC 需求與風險因素。" * 8,
            publisher=publisher or "台積電 IR",
            published_at=date(2026, 5, 1),
            url=url,
        )

    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_URL", "https://browserless.example/content")
    get_settings.cache_clear()
    monkeypatch.setattr(CompanyFilingFetcher, "_fetch_url_as_document", blocked_direct_fetch)
    monkeypatch.setattr(CompanyFilingFetcher, "_fetch_browser_rendered_url_as_document", fake_browser_render)

    try:
        document = asyncio.run(
            CompanyFilingFetcher(cache=FakeCache()).fetch_url_document(
                "https://investor.tsmc.com/annual-report",
                ticker="2330",
                company_name="台積電",
                document_type="annual_report",
                publisher="台積電 IR",
            )
        )
    finally:
        get_settings.cache_clear()

    assert document.title == "台積電 2026 年報"
    assert stored == {
        "url": "https://investor.tsmc.com/annual-report",
        "title": "台積電 2026 年報",
    }


def test_company_filing_fetch_url_document_uses_playwright_render_when_browserless_absent(
    monkeypatch,
) -> None:
    cached = NewsFetcher.from_manual_text(
        title="台積電 年報",
        text="台積電 年報 請啟用 JavaScript 後查看文件內容。" * 8,
        publisher="cached publisher",
        url="https://investor.tsmc.com/annual-report",
    )
    stored = {}

    class FakeCache:
        def get_url_document(self, url, *, parser, extract_tables, html_extract_tables):
            return cached

        def set_url_document(self, url, document, *, parser, extract_tables, html_extract_tables):
            stored["url"] = url
            stored["title"] = document.title

    async def blocked_direct_fetch(self, url, publisher=None):
        return cached

    async def fake_playwright_render(self, url, publisher=None):
        return NewsFetcher.from_manual_text(
            title="台積電 2026 年報",
            text="台積電 2026 年報 annual report 揭露 AI/HPC 需求與風險因素。" * 8,
            publisher=publisher or "台積電 IR",
            published_at=date(2026, 5, 1),
            url=url,
        )

    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(CompanyFilingFetcher, "_fetch_url_as_document", blocked_direct_fetch)
    monkeypatch.setattr(CompanyFilingFetcher, "_fetch_playwright_rendered_url_as_document", fake_playwright_render)

    try:
        document = asyncio.run(
            CompanyFilingFetcher(cache=FakeCache()).fetch_url_document(
                "https://investor.tsmc.com/annual-report",
                ticker="2330",
                company_name="台積電",
                document_type="annual_report",
                publisher="台積電 IR",
            )
        )
    finally:
        get_settings.cache_clear()

    assert document.title == "台積電 2026 年報"
    assert stored == {
        "url": "https://investor.tsmc.com/annual-report",
        "title": "台積電 2026 年報",
    }


def test_company_filing_browser_render_posts_to_configured_endpoint(monkeypatch) -> None:
    captured = {}

    class FakeAsyncClient:
        def __init__(self, **options) -> None:
            captured["options"] = options

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def request(self, method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["kwargs"] = kwargs
            request = httpx.Request(method, url)
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "text/html"},
                text=(
                    "<html><head><title>台積電 2026 年報</title></head>"
                    "<body>台積電 2026 annual report 揭露 AI/HPC 需求與風險因素。"
                    "台積電 年報 公司治理 財務 風險。</body></html>"
                ),
            )

    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_URL", "https://browserless.example/content")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_TOKEN", "secret-token")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_TIMEOUT_SECONDS", "12")
    get_settings.cache_clear()
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    try:
        document = asyncio.run(
            CompanyFilingFetcher()._fetch_browser_rendered_url_as_document(
                "https://investor.tsmc.com/annual-report",
                publisher="台積電 IR",
            )
        )
    finally:
        get_settings.cache_clear()

    assert document.title == "台積電 2026 年報"
    assert "AI/HPC" in document.text
    assert captured["method"] == "POST"
    assert captured["url"] == "https://browserless.example/content"
    assert captured["kwargs"]["json"]["url"] == "https://investor.tsmc.com/annual-report"
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["options"]["timeout"] == 12.0


def test_company_filing_browser_render_posts_flaresolverr_payload(monkeypatch) -> None:
    captured = {}

    class FakeAsyncClient:
        def __init__(self, **options) -> None:
            captured["options"] = options

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def request(self, method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["kwargs"] = kwargs
            request = httpx.Request(method, url)
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "application/json"},
                json={
                    "status": "ok",
                    "solution": {
                        "url": "https://investor.tsmc.com/rendered",
                        "response": (
                            "<html><head><title>台積電 2026 年報</title></head>"
                            "<body>台積電 annual report AI/HPC 風險與財務資訊。</body></html>"
                        ),
                    },
                },
            )

    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_PROVIDER", "flaresolverr")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_URL", "http://flaresolverr:8191/v1")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_TIMEOUT_SECONDS", "12")
    get_settings.cache_clear()
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    try:
        document = asyncio.run(
            CompanyFilingFetcher()._fetch_browser_rendered_url_as_document(
                "https://investor.tsmc.com/annual-report",
                publisher="台積電 IR",
            )
        )
    finally:
        get_settings.cache_clear()

    assert document.source.url == "https://investor.tsmc.com/rendered"
    assert "AI/HPC" in document.text
    assert captured["method"] == "POST"
    assert captured["url"] == "http://flaresolverr:8191/v1"
    assert captured["kwargs"]["json"]["cmd"] == "request.get"
    assert captured["kwargs"]["json"]["url"] == "https://investor.tsmc.com/annual-report"
    assert captured["kwargs"]["json"]["maxTimeout"] == 12000


def test_company_filing_browser_render_uses_scrapingbee_params(monkeypatch) -> None:
    captured = {}

    class FakeAsyncClient:
        def __init__(self, **options) -> None:
            captured["options"] = options

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def request(self, method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["kwargs"] = kwargs
            request = httpx.Request(method, url)
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "text/html"},
                text=(
                    "<html><head><title>台積電 2026 年報</title></head>"
                    "<body>台積電 annual report AI/HPC 風險與財務資訊。</body></html>"
                ),
            )

    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_PROVIDER", "scrapingbee")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_URL", "https://app.scrapingbee.com/api/v1")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_TOKEN", "bee-token")
    get_settings.cache_clear()
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    try:
        document = asyncio.run(
            CompanyFilingFetcher()._fetch_browser_rendered_url_as_document(
                "https://investor.tsmc.com/annual-report",
                publisher="台積電 IR",
            )
        )
    finally:
        get_settings.cache_clear()

    assert "AI/HPC" in document.text
    assert captured["method"] == "GET"
    assert captured["url"] == "https://app.scrapingbee.com/api/v1"
    assert captured["kwargs"]["params"] == {
        "url": "https://investor.tsmc.com/annual-report",
        "render_js": "true",
        "api_key": "bee-token",  # pragma: allowlist secret
    }
    assert "Authorization" not in captured["kwargs"]["headers"]


def test_company_filing_browser_render_respects_configured_concurrency(monkeypatch) -> None:
    counters = {"active": 0, "max_active": 0}

    class FakeAsyncClient:
        def __init__(self, **_options) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def request(self, method, url, **kwargs):
            counters["active"] += 1
            counters["max_active"] = max(counters["max_active"], counters["active"])
            await asyncio.sleep(0)
            counters["active"] -= 1
            request = httpx.Request(method, url)
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "text/html"},
                text=(
                    "<html><head><title>台積電 2026 年報</title></head>"
                    "<body>台積電 2026 annual report 揭露 AI/HPC 需求與風險因素。"
                    "台積電 年報 公司治理 財務 風險。</body></html>"
                ),
            )

    async def run_fetches() -> None:
        fetcher = CompanyFilingFetcher()
        await asyncio.gather(
            fetcher._fetch_browser_rendered_url_as_document("https://investor.tsmc.com/a"),
            fetcher._fetch_browser_rendered_url_as_document("https://investor.tsmc.com/b"),
        )

    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_URL", "https://browserless.example/content")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_CONCURRENCY", "1")
    get_settings.cache_clear()
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    try:
        asyncio.run(run_fetches())
    finally:
        get_settings.cache_clear()

    assert counters["max_active"] == 1


def test_company_filing_playwright_render_uses_async_api(monkeypatch) -> None:
    captured = {}

    class FakePage:
        url = "https://investor.tsmc.com/rendered-annual-report"

        async def goto(self, url, *, wait_until, timeout):
            captured["goto_url"] = url
            captured["wait_until"] = wait_until
            captured["timeout"] = timeout

        async def content(self):
            return (
                "<html><head><title>台積電 2026 年報</title></head>"
                "<body>台積電 2026 annual report 揭露 AI/HPC 需求與風險因素。"
                "台積電 年報 公司治理 財務 風險。</body></html>"
            )

    class FakeBrowser:
        async def new_page(self, **kwargs):
            captured["new_page"] = kwargs
            return FakePage()

        async def close(self):
            captured["closed"] = True

    class FakeLauncher:
        async def launch(self, **kwargs):
            captured["launch"] = kwargs
            return FakeBrowser()

    class FakePlaywrightContext:
        async def __aenter__(self):
            return SimpleNamespace(chromium=FakeLauncher())

        async def __aexit__(self, exc_type, exc, traceback):
            return None

    def fake_import_module(name):
        if name == "playwright.async_api":
            return SimpleNamespace(async_playwright=lambda: FakePlaywrightContext())
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_BROWSER", "chromium")
    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_WAIT_UNTIL", "networkidle")
    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_TIMEOUT_SECONDS", "12")
    get_settings.cache_clear()
    monkeypatch.setattr("app.data_sources.company_filings.importlib.import_module", fake_import_module)
    try:
        document = asyncio.run(
            CompanyFilingFetcher()._fetch_playwright_rendered_url_as_document(
                "https://investor.tsmc.com/annual-report",
                publisher="台積電 IR",
            )
        )
    finally:
        get_settings.cache_clear()

    assert document.title == "台積電 2026 年報"
    assert document.source.url == "https://investor.tsmc.com/rendered-annual-report"
    assert "AI/HPC" in document.text
    assert captured["goto_url"] == "https://investor.tsmc.com/annual-report"
    assert captured["wait_until"] == "networkidle"
    assert captured["timeout"] == 12_000
    assert captured["launch"] == {"headless": True}
    assert captured["new_page"]["locale"] == "zh-TW"
    assert captured["new_page"]["user_agent"]
    assert captured["closed"] is True
