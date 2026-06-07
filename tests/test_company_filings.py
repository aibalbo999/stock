import asyncio
from datetime import date
import sys
from types import SimpleNamespace

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.data_sources.company_filings import (
    CompanyFilingFetcher,
    PDF_IMPORT_NO_TEXT_MESSAGE,
    categorize_company_filing_error,
    company_filing_browser_render_configured,
    company_filing_browser_render_provider,
    company_filing_browser_render_status,
    company_filing_playwright_browser_status,
    company_filing_render_fallback_configured,
    company_filing_playwright_render_enabled,
    company_filing_structured_api_configured,
    company_filing_structured_api_status,
    company_filing_client_options,
    company_filing_fetch_response_with_retries,
    company_filing_identity_for_url,
    company_filing_error,
    company_filing_request_with_retries,
    company_filing_retry_delay_seconds,
    extract_html_redirect_url,
    extract_company_filing_html_text,
    extract_pdf_text,
    filing_quality_score,
    filing_source_tier,
    infer_document_type,
    is_retryable_company_filing_error_category,
    is_relevant_company_filing_result,
    normalize_search_result_url,
    normalize_tpex_company_profile,
    parse_mops_annual_report_rows,
    parse_mops_roc_datetime,
    structured_api_document_rows,
    validate_fetched_company_filing_document,
    validate_public_document_url,
)
from app.db.models import Base
from app.data_sources.news import NewsFetcher
from app.services.persistence import CompanyFilingRepository


def test_infer_company_filing_document_type() -> None:
    assert infer_document_type("台積電 2025 年報") == "annual_report"
    assert infer_document_type("Quanta investor presentation") == "investor_presentation"
    assert infer_document_type("公開說明書 募集資金用途") == "prospectus"


def test_company_filing_discovery_filters_generic_results() -> None:
    relevant = NewsFetcher.from_manual_text(
        title="2330 台積電 法說會重點",
        text="台積電 investor presentation 說明 AI/HPC 需求。",
    )
    generic = NewsFetcher.from_manual_text(
        title="台股財報公布時間整理",
        text="說明市場整體財報時間，沒有個別公司公開文件。",
    )

    assert is_relevant_company_filing_result(relevant, "2330", "台積電") is True
    assert is_relevant_company_filing_result(generic, "2330", "台積電") is False


def test_company_filing_quality_prefers_official_sources() -> None:
    official = NewsFetcher.from_manual_text(
        title="2330 台積電 年報",
        text="台積電 年報揭露 AI/HPC 需求與風險因素。",
        publisher="公開資訊觀測站",
        published_at=date(2026, 5, 1),
        url="https://mops.twse.com.tw/server-java/t57sb01?co_id=2330",
    )
    third_party = NewsFetcher.from_manual_text(
        title="2330 台積電 法說會懶人包",
        text="台積電 法說會摘要。",
        publisher="第三方部落格",
        published_at=date(2026, 5, 1),
        url="https://example.com/tsmc-summary",
    )

    assert filing_source_tier(official) == "official_disclosure"
    assert filing_quality_score(official, "2330", "台積電") >= 70
    assert filing_source_tier(third_party) == "third_party"
    assert filing_quality_score(third_party, "2330", "台積電") < 70


def test_company_filing_search_plan_targets_official_sources() -> None:
    plan = CompanyFilingFetcher.official_search_plan("2330", "台積電")

    assert any("site:mops.twse.com.tw" in query for query in plan["queries"])
    assert any("filetype:pdf" in query for query in plan["queries"])
    assert any(portal["name"] == "公開資訊觀測站" for portal in plan["official_portals"])
    assert len(plan["google_news_urls"]) == len(plan["queries"])


def test_company_filing_search_plan_can_target_document_type() -> None:
    plan = CompanyFilingFetcher.official_search_plan(
        "2330",
        "台積電",
        document_types=["annual_report"],
    )

    assert plan["document_types"] == ["annual_report"]
    assert all("年報" in query or "annual report" in query for query in plan["queries"])
    assert not any("法人說明會" in query for query in plan["queries"])


def test_company_filing_client_options_use_configured_identity(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_USER_AGENTS", "UA-A")
    monkeypatch.setenv("COMPANY_FILING_PROXY_URLS", "http://proxy.example:8080")
    get_settings.cache_clear()
    try:
        options = company_filing_client_options(
            "https://doc.twse.com.tw/server-java/t57sb01",
            timeout=11,
            follow_redirects=True,
        )
    finally:
        get_settings.cache_clear()

    assert options["headers"]["User-Agent"] == "UA-A"
    assert options["headers"]["Accept-Language"].startswith("zh-TW")
    assert options["proxy"] == "http://proxy.example:8080"
    assert options["timeout"] == 11
    assert options["follow_redirects"] is True


def test_company_filing_identity_rotates_by_retry_attempt(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_USER_AGENTS", "UA-A,UA-B")
    monkeypatch.setenv("COMPANY_FILING_PROXY_URLS", "http://proxy-a.example:8080,http://proxy-b.example:8080")
    get_settings.cache_clear()
    try:
        first = company_filing_identity_for_url("https://doc.twse.com.tw/server-java/t57sb01", attempt=0)
        second = company_filing_identity_for_url("https://doc.twse.com.tw/server-java/t57sb01", attempt=1)
    finally:
        get_settings.cache_clear()

    assert {first["user_agent"], second["user_agent"]} == {"UA-A", "UA-B"}
    assert {first["proxy"], second["proxy"]} == {
        "http://proxy-a.example:8080",
        "http://proxy-b.example:8080",
    }


def test_company_filing_browser_render_is_explicitly_configured(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_URL", "https://browserless.example/content")
    get_settings.cache_clear()
    try:
        assert company_filing_browser_render_configured() is True
        assert company_filing_browser_render_provider() == "browserless"
    finally:
        get_settings.cache_clear()


def test_company_filing_structured_api_status_requires_provider_and_url(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_PROVIDER", "tej")
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_URL", "https://api.tej.example/filings")
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_TOKEN", "tej-token")
    get_settings.cache_clear()
    try:
        assert company_filing_structured_api_configured() is True
        status = company_filing_structured_api_status()
    finally:
        get_settings.cache_clear()

    assert status["configured"] is True
    assert status["provider"] == "tej"
    assert status["url_configured"] is True
    assert status["token_configured"] is True
    assert status["smoke_cli"].endswith(
        "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
    )
    assert (
        status["sample_contract_cli"].endswith(
            "--sample-json examples/structured_company_filing_sample.json "
            "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
        )
    )
    assert status["fallback_reason"] is None


def test_structured_api_document_rows_accepts_common_payload_shapes() -> None:
    assert structured_api_document_rows({"documents": [{"title": "A"}, "bad"]}) == [{"title": "A"}]
    assert structured_api_document_rows({"data": [{"title": "B"}]}) == [{"title": "B"}]
    assert structured_api_document_rows([{"title": "C"}]) == [{"title": "C"}]


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

    monkeypatch.setattr("app.data_sources.company_filings.socket.create_connection", fake_create_connection)

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

    monkeypatch.setattr("app.data_sources.company_filings.socket.create_connection", fake_create_connection)

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
    monkeypatch.setattr("app.data_sources.company_filings.company_filing_playwright_available", lambda: False)
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

    monkeypatch.setattr("app.data_sources.company_filings.company_filing_playwright_available", lambda: True)
    monkeypatch.setattr("app.data_sources.company_filings.importlib.import_module", fake_import_module)

    status = company_filing_playwright_browser_status("chromium")

    assert status["dependency_available"] is True
    assert status["browser_available"] is True
    assert status["browser_executable_exists"] is True
    assert status["fallback_reason"] is None


def test_company_filing_playwright_browser_status_reports_missing_browser_binary(monkeypatch, tmp_path) -> None:
    missing_executable = tmp_path / "missing-chromium"

    class FakeLauncher:
        executable_path = str(missing_executable)

    class FakePlaywrightContext:
        def __enter__(self):
            return SimpleNamespace(chromium=FakeLauncher())

        def __exit__(self, exc_type, exc, traceback):
            return None

    monkeypatch.setattr("app.data_sources.company_filings.company_filing_playwright_available", lambda: True)
    monkeypatch.setattr(
        "app.data_sources.company_filings.importlib.import_module",
        lambda name: SimpleNamespace(sync_playwright=lambda: FakePlaywrightContext()),
    )

    status = company_filing_playwright_browser_status("chromium")

    assert status["dependency_available"] is True
    assert status["browser_available"] is False
    assert status["fallback_reason"].startswith("missing_browser_binary:chromium")


def test_company_filing_request_retries_retryable_status(monkeypatch) -> None:
    class FakeRetryClient:
        def __init__(self) -> None:
            self.calls = 0
            self.request_headers = []

        async def request(self, method, url, **kwargs):
            self.calls += 1
            self.request_headers.append(kwargs.get("headers") or {})
            request = httpx.Request(method, url)
            status_code = 429 if self.calls == 1 else 200
            return httpx.Response(status_code, request=request, text="ok")

    monkeypatch.setenv("COMPANY_FILING_HTTP_RETRIES", "1")
    monkeypatch.setenv("COMPANY_FILING_BASE_RETRY_DELAY_SECONDS", "0")
    monkeypatch.setenv("COMPANY_FILING_MAX_RETRY_DELAY_SECONDS", "0")
    get_settings.cache_clear()
    client = FakeRetryClient()
    try:
        response = asyncio.run(company_filing_request_with_retries(client, "GET", "https://example.com"))
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert client.calls == 2
    assert len({headers["User-Agent"] for headers in client.request_headers}) == 2


def test_company_filing_fetch_response_recreates_client_with_rotating_proxy(monkeypatch) -> None:
    captured_options = []
    captured_headers = []

    class FakeAsyncClient:
        calls = 0

        def __init__(self, **options) -> None:
            captured_options.append(options)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def request(self, method, url, **kwargs):
            FakeAsyncClient.calls += 1
            captured_headers.append(kwargs.get("headers") or {})
            request = httpx.Request(method, url)
            status_code = 429 if FakeAsyncClient.calls == 1 else 200
            return httpx.Response(status_code, request=request, text="ok")

    monkeypatch.setenv("COMPANY_FILING_USER_AGENTS", "UA-A,UA-B")
    monkeypatch.setenv("COMPANY_FILING_PROXY_URLS", "http://proxy-a.example:8080,http://proxy-b.example:8080")
    monkeypatch.setenv("COMPANY_FILING_HTTP_RETRIES", "1")
    monkeypatch.setenv("COMPANY_FILING_BASE_RETRY_DELAY_SECONDS", "0")
    monkeypatch.setenv("COMPANY_FILING_MAX_RETRY_DELAY_SECONDS", "0")
    get_settings.cache_clear()
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    try:
        response = asyncio.run(
            company_filing_fetch_response_with_retries(
                "GET",
                "https://doc.twse.com.tw/server-java/t57sb01",
                timeout=9,
            )
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert [options["timeout"] for options in captured_options] == [9, 9]
    assert {options["proxy"] for options in captured_options} == {
        "http://proxy-a.example:8080",
        "http://proxy-b.example:8080",
    }
    assert {headers["User-Agent"] for headers in captured_headers} == {"UA-A", "UA-B"}


def test_company_filing_request_does_not_retry_non_retryable_status(monkeypatch) -> None:
    class FakeRetryClient:
        def __init__(self) -> None:
            self.calls = 0

        async def request(self, method, url, **kwargs):
            self.calls += 1
            request = httpx.Request(method, url)
            return httpx.Response(404, request=request, text="not found")

    monkeypatch.setenv("COMPANY_FILING_HTTP_RETRIES", "3")
    monkeypatch.setenv("COMPANY_FILING_BASE_RETRY_DELAY_SECONDS", "0")
    get_settings.cache_clear()
    client = FakeRetryClient()
    try:
        try:
            asyncio.run(company_filing_request_with_retries(client, "GET", "https://example.com/missing"))
        except httpx.HTTPStatusError:
            pass
        else:
            raise AssertionError("404 should be raised without retry")
    finally:
        get_settings.cache_clear()

    assert client.calls == 1


def test_company_filing_retry_delay_uses_retry_after(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_BASE_RETRY_DELAY_SECONDS", "0.5")
    monkeypatch.setenv("COMPANY_FILING_MAX_RETRY_DELAY_SECONDS", "5")
    get_settings.cache_clear()
    try:
        response = httpx.Response(
            429,
            headers={"Retry-After": "3.5"},
            request=httpx.Request("GET", "https://example.com"),
        )

        assert company_filing_retry_delay_seconds(response, attempt=0) == 3.5
    finally:
        get_settings.cache_clear()


def test_company_filing_error_classifies_http_status_and_retryability() -> None:
    request = httpx.Request("GET", "https://mops.twse.com.tw/report")
    rate_limited = httpx.HTTPStatusError(
        "too many requests",
        request=request,
        response=httpx.Response(429, request=request),
    )
    not_found = httpx.HTTPStatusError(
        "not found",
        request=request,
        response=httpx.Response(404, request=request),
    )

    error = company_filing_error("https://mops.twse.com.tw/report", rate_limited, stage="mops_query")

    assert error["category"] == "rate_limited"
    assert error["retryable"] is True
    assert error["stage"] == "mops_query"
    assert categorize_company_filing_error(not_found) == "http_not_found"
    assert is_retryable_company_filing_error_category("http_not_found") is False


def test_company_filing_error_classifies_validation_and_pdf_failures() -> None:
    assert (
        categorize_company_filing_error("company filing content does not mention the target company")
        == "company_mismatch"
    )
    assert (
        categorize_company_filing_error("company filing content looks like a blocked, login, or placeholder page")
        == "blocked_or_placeholder"
    )
    assert categorize_company_filing_error(PDF_IMPORT_NO_TEXT_MESSAGE) == "pdf_no_text"
    assert categorize_company_filing_error("MOPS did not return a PDF download link") == "missing_pdf_link"
    assert categorize_company_filing_error("company website not found") == "website_not_found"
    assert (
        categorize_company_filing_error(
            f"{PDF_IMPORT_NO_TEXT_MESSAGE}；Visual RAG 後援失敗："
            "Visual RAG vision LLM API key 或本地 gateway 尚未配置。"
        )
        == "visual_rag_not_configured"
    )
    assert (
        categorize_company_filing_error("Visual RAG 後援失敗：RESOURCE_EXHAUSTED quota exceeded")
        == "visual_rag_quota"
    )
    assert (
        categorize_company_filing_error("Visual RAG PDF 轉圖需要安裝 PyMuPDF")
        == "visual_rag_missing_dependency"
    )
    assert (
        categorize_company_filing_error("Visual RAG LLM extraction failed: empty response")
        == "visual_rag_failed"
    )


def test_search_result_url_normalizes_duckduckgo_redirect() -> None:
    url = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Finvestor.tsmc.com%2Fannual-report.pdf"

    assert normalize_search_result_url(url) == "https://investor.tsmc.com/annual-report.pdf"


def test_html_redirect_url_extracts_meta_and_location_href() -> None:
    assert (
        extract_html_redirect_url(
            '<meta http-equiv="refresh" content="0.1;url=page/en/index.html">',
            "https://www.qsitw.com/",
        )
        == "https://www.qsitw.com/page/en/index.html"
    )
    assert (
        extract_html_redirect_url(
            'location.href = "https://www.tuc.com.tw/index";',
            "https://www.tuc.com.tw/",
        )
        == "https://www.tuc.com.tw/index"
    )


def test_company_filing_html_text_extracts_structured_tables(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_HTML_EXTRACT_TABLES", "true")
    get_settings.cache_clear()
    soup = BeautifulSoup(
        """
        <html>
          <head><title>台積電 年報</title></head>
          <body>
            <article>
              <p>台積電 年報揭露 AI/HPC 需求與資本支出。</p>
              <table>
                <tr><th>年度</th><th>營收</th><th>毛利率</th></tr>
                <tr><td>2025</td><td>3,000,000</td><td>53%</td></tr>
              </table>
            </article>
          </body>
        </html>
        """,
        "html.parser",
    )

    try:
        text = extract_company_filing_html_text(soup)
    finally:
        get_settings.cache_clear()

    assert "台積電 年報揭露 AI/HPC 需求" in text
    assert "[HTML 表格抽取 #1]" in text
    assert "表格尺寸：2 列 x 3 欄" in text
    assert "年度 | 營收 | 毛利率" in text
    assert "2025 | 3,000,000 | 53%" in text


def test_company_filing_html_text_table_extraction_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_HTML_EXTRACT_TABLES", "false")
    get_settings.cache_clear()
    soup = BeautifulSoup(
        "<html><body><p>台積電 年報。</p><table><tr><td>年度</td><td>營收</td></tr></table></body></html>",
        "html.parser",
    )

    try:
        text = extract_company_filing_html_text(soup)
    finally:
        get_settings.cache_clear()

    assert "[HTML 表格抽取" not in text


def test_tpex_profile_is_normalized_for_official_website_discovery() -> None:
    profile = normalize_tpex_company_profile(
        {
            "SecuritiesCompanyCode": "6188",
            "CompanyName": "廣明光電股份有限公司",
            "CompanyAbbreviation": "廣明",
            "WebAddress": "www.qsitw.com",
            "EmailAddress": "ir@example.com",
        }
    )

    assert profile["公司代號"] == "6188"
    assert profile["公司簡稱"] == "廣明"
    assert profile["網址"] == "www.qsitw.com"


def test_company_profile_falls_back_to_tpex_cache() -> None:
    CompanyFilingFetcher._twse_profile_cache = []
    CompanyFilingFetcher._tpex_profile_cache = [
        {
            "SecuritiesCompanyCode": "6274",
            "CompanyName": "台燿科技股份有限公司",
            "CompanyAbbreviation": "台燿",
            "WebAddress": "www.tuc.com.tw",
        }
    ]
    try:
        profile = asyncio.run(CompanyFilingFetcher.twse_company_profile("6274"))
    finally:
        CompanyFilingFetcher._twse_profile_cache = None
        CompanyFilingFetcher._tpex_profile_cache = None

    assert profile["公司簡稱"] == "台燿"
    assert profile["網址"] == "www.tuc.com.tw"


def test_official_website_missing_profile_error_is_categorized(monkeypatch) -> None:
    async def fake_profile(ticker: str):
        return {"公司簡稱": "台積電", "網址": ""}

    monkeypatch.setattr(CompanyFilingFetcher, "twse_company_profile", staticmethod(fake_profile))

    documents, errors = asyncio.run(
        CompanyFilingFetcher().fetch_official_website_documents("2330", "台積電")
    )

    assert documents == []
    assert errors == [
        {
            "source": "TWSE company profile",
            "error": "company website not found",
            "category": "website_not_found",
            "retryable": False,
            "stage": "official_profile",
        }
    ]


def test_parse_mops_annual_report_rows_keeps_chinese_annual_report() -> None:
    html = """
    <table>
      <tr><td>2330</td><td>113 年</td><td>股東會相關資料</td><td></td><td>常會</td><td>股東會年報(尚未適用永續揭露準則)</td><td></td><td>2024_2330_F04.pdf</td><td>100</td><td>114/05/16 17:43:11</td></tr>
      <tr><td>2330</td><td>113 年</td><td>股東會相關資料</td><td></td><td>常會</td><td>英文版-股東會年報</td><td></td><td>2024_2330_FE4.pdf</td><td>100</td><td>114/05/16 17:43:11</td></tr>
      <tr><td>2330</td><td>113 年</td><td>股東會相關資料</td><td></td><td>常會</td><td>年報前十大股東相互間關係表</td><td></td><td>2024_2330_F17.pdf</td><td>100</td><td>114/05/16 17:43:11</td></tr>
    </table>
    """

    rows = parse_mops_annual_report_rows(html)

    assert rows == [
        {
            "ticker": "2330",
            "data_year": "113 年",
            "description": "股東會年報(尚未適用永續揭露準則)",
            "filename": "2024_2330_F04.pdf",
            "uploaded_at": "114/05/16 17:43:11",
        }
    ]
    assert parse_mops_roc_datetime("114/05/16 17:43:11") == date(2025, 5, 16)


def test_company_filing_web_search_fetches_candidate_documents(monkeypatch) -> None:
    async def fake_search(query_text: str, limit: int = 5):
        return [
            {
                "title": "台積電 2026 年報 PDF",
                "url": "https://investor.tsmc.com/annual-report.pdf",
                "snippet": "2330 台積電 年報 annual report",
                "publisher": "investor.tsmc.com",
            }
        ]

    async def fake_fetch_url_document(
        self,
        url,
        ticker,
        company_name="",
        document_type="company_disclosure",
        publisher=None,
        published_at=None,
    ):
        return CompanyFilingFetcher.from_manual_text(
            ticker=ticker,
            company_name=company_name,
            document_type=document_type,
            title="台積電 2026 年報",
            text="台積電 年報揭露 AI/HPC 需求與風險因素。" * 8,
            publisher=publisher or "investor.tsmc.com",
            published_at=date(2026, 5, 1),
            url=url,
        )

    monkeypatch.setattr(CompanyFilingFetcher, "_duckduckgo_search", staticmethod(fake_search))
    monkeypatch.setattr(CompanyFilingFetcher, "fetch_url_document", fake_fetch_url_document)

    import asyncio

    documents, errors = asyncio.run(
        CompanyFilingFetcher().fetch_web_search_documents(
            "2330",
            "台積電",
            document_types=["annual_report"],
        )
    )

    assert errors == []
    assert documents[0].document_type == "annual_report"
    assert documents[0].source.url == "https://investor.tsmc.com/annual-report.pdf"


def test_company_filing_discovery_uses_structured_api_fallback(monkeypatch) -> None:
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
                json={
                    "documents": [
                        {
                            "title": "台積電 2026 法說會簡報",
                            "text": "2330 台積電 法說會 investor presentation 揭露 AI/HPC 需求與資本支出。" * 4,
                            "url": "https://api.tej.example/documents/2330-presentation",
                            "publisher": "TEJ",
                            "published_at": "2026-05-01",
                            "document_type": "investor_presentation",
                        }
                    ]
                },
            )

    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_PROVIDER", "tej")
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_URL", "https://api.tej.example/filings")
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_TOKEN", "tej-token")
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(CompanyFilingFetcher, "google_news_urls", classmethod(lambda cls, *args, **kwargs: []))
    get_settings.cache_clear()
    try:
        documents, errors = asyncio.run(
            CompanyFilingFetcher().fetch_discovery_documents(
                "2330",
                "台積電",
                document_types=["investor_presentation"],
            )
        )
    finally:
        get_settings.cache_clear()

    assert errors == []
    assert documents[0].document_type == "investor_presentation"
    assert documents[0].source.publisher == "TEJ"
    assert documents[0].source.published_at == date(2026, 5, 1)
    assert captured["method"] == "GET"
    assert captured["url"] == "https://api.tej.example/filings"
    assert captured["kwargs"]["params"]["ticker"] == "2330"
    assert captured["kwargs"]["params"]["document_types"] == "investor_presentation"
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer tej-token"


def test_company_filing_web_search_errors_include_category(monkeypatch) -> None:
    async def fake_search(query_text: str, limit: int = 5):
        return [
            {
                "title": "台積電 2026 年報 PDF",
                "url": "https://investor.tsmc.com/annual-report.pdf",
                "snippet": "2330 台積電 年報 annual report",
                "publisher": "investor.tsmc.com",
            }
        ]

    async def fake_fetch_url_document(
        self,
        url,
        ticker,
        company_name="",
        document_type="company_disclosure",
        publisher=None,
        published_at=None,
    ):
        raise ValueError("company filing content does not mention the target company")

    monkeypatch.setattr(CompanyFilingFetcher, "_duckduckgo_search", staticmethod(fake_search))
    monkeypatch.setattr(CompanyFilingFetcher, "fetch_url_document", fake_fetch_url_document)

    documents, errors = asyncio.run(
        CompanyFilingFetcher().fetch_web_search_documents(
            "2330",
            "台積電",
            document_types=["annual_report"],
        )
    )

    assert documents == []
    assert errors[0]["source"] == "https://investor.tsmc.com/annual-report.pdf"
    assert errors[0]["category"] == "company_mismatch"
    assert errors[0]["retryable"] is False
    assert errors[0]["stage"] == "web_search_fetch"


def test_company_filing_repository_roundtrip() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        document = CompanyFilingFetcher.from_manual_text(
            ticker="2330",
            company_name="台積電",
            document_type="annual_report",
            title="台積電 年報",
            text="年報揭露 AI/HPC 需求、資本支出與風險因素。",
            publisher="台積電 IR",
            published_at=date(2026, 5, 1),
            url="https://example.com/2330-annual-report.pdf",
        )
        repository = CompanyFilingRepository(session)
        repository.upsert_document(document)
        session.commit()

        stored = repository.latest_by_tickers(["2330"])
        stats = repository.stats_by_ticker("2330")
        news_document = CompanyFilingRepository.to_news_document(stored[0])

    assert stored[0].ticker == "2330"
    assert stats["rows"] == 1
    assert stats["document_types"] == ["annual_report"]
    assert news_document.id.startswith("filing-")
    assert "文件類型：annual_report" in news_document.text


def test_company_filing_fetch_url_document_uses_page_text(monkeypatch) -> None:
    async def fake_fetch_url_as_document(self, url, publisher=None):
        return NewsFetcher.from_manual_text(
            title="台積電 2026 年報",
            text="台積電 2026 年報揭露 AI/HPC 需求與風險因素。" * 8,
            publisher=publisher or "公開資訊觀測站",
            published_at=date(2026, 5, 1),
            url=url,
        )

    monkeypatch.setattr(CompanyFilingFetcher, "_fetch_url_as_document", fake_fetch_url_as_document)

    import asyncio

    document = asyncio.run(
        CompanyFilingFetcher().fetch_url_document(
            "https://mops.twse.com.tw/server-java/t57sb01?co_id=2330",
            ticker="2330",
            company_name="台積電",
            document_type="annual_report",
        )
    )

    assert document.ticker == "2330"
    assert document.document_type == "annual_report"
    assert document.title == "台積電 2026 年報"


def test_company_filing_fetch_url_document_uses_parsed_cache(monkeypatch) -> None:
    cached = NewsFetcher.from_manual_text(
        title="台積電 2026 年報",
        text="台積電 2026 年報揭露 AI/HPC 需求與風險因素。" * 8,
        publisher="cached publisher",
        published_at=date(2026, 5, 1),
        url="https://investor.tsmc.com/annual-report.pdf",
    )

    class FakeCache:
        def get_url_document(self, url, *, parser, extract_tables, html_extract_tables):
            return cached

        def set_url_document(self, *args, **kwargs):
            raise AssertionError("cache hit should not write")

    async def fail_fetch(self, url, publisher=None):
        raise AssertionError("cache hit should not fetch network")

    monkeypatch.setattr(CompanyFilingFetcher, "_fetch_url_as_document", fail_fetch)

    import asyncio

    document = asyncio.run(
        CompanyFilingFetcher(cache=FakeCache()).fetch_url_document(
            "https://investor.tsmc.com/annual-report.pdf",
            ticker="2330",
            company_name="台積電",
            document_type="annual_report",
            publisher="台積電 IR",
        )
    )

    assert document.title == "台積電 2026 年報"
    assert document.source.publisher == "台積電 IR"


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


def test_company_filing_fetch_url_document_stores_parsed_cache(monkeypatch) -> None:
    stored = {}

    class FakeCache:
        def get_url_document(self, url, *, parser, extract_tables, html_extract_tables):
            return None

        def set_url_document(self, url, document, *, parser, extract_tables, html_extract_tables):
            stored["url"] = url
            stored["title"] = document.title
            stored["parser"] = parser
            stored["extract_tables"] = extract_tables
            stored["html_extract_tables"] = html_extract_tables

    async def fake_fetch_url_as_document(self, url, publisher=None):
        return NewsFetcher.from_manual_text(
            title="台積電 2026 年報",
            text="台積電 2026 年報揭露 AI/HPC 需求與風險因素。" * 8,
            publisher=publisher or "台積電 IR",
            published_at=date(2026, 5, 1),
            url=url,
        )

    monkeypatch.setattr(CompanyFilingFetcher, "_fetch_url_as_document", fake_fetch_url_as_document)

    import asyncio

    document = asyncio.run(
        CompanyFilingFetcher(cache=FakeCache()).fetch_url_document(
            "https://investor.tsmc.com/annual-report.pdf",
            ticker="2330",
            company_name="台積電",
            document_type="annual_report",
        )
    )

    assert document.title == "台積電 2026 年報"
    assert stored == {
        "url": "https://investor.tsmc.com/annual-report.pdf",
        "title": "台積電 2026 年報",
        "parser": get_settings().company_filing_pdf_parser,
        "extract_tables": get_settings().company_filing_pdf_extract_tables,
        "html_extract_tables": get_settings().company_filing_html_extract_tables,
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
        "api_key": "bee-token",
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


def test_company_filing_pdf_text_extraction(monkeypatch) -> None:
    import pypdf

    class FakePage:
        def __init__(self, text: str) -> None:
            self.text = text

        def extract_text(self) -> str:
            return self.text

    monkeypatch.setattr(
        pypdf,
        "PdfReader",
        lambda _content: SimpleNamespace(
            pages=[
                FakePage("台積電 2026 年報"),
                FakePage("AI/HPC 需求與風險因素"),
            ]
        ),
    )

    assert "台積電 2026 年報" in extract_pdf_text(b"%PDF fake")


def test_company_filing_pdf_parser_extracts_tables_with_pdfplumber(monkeypatch) -> None:
    class FakePdfPage:
        def extract_text(self) -> str:
            return "台積電 2026 年報"

        def extract_tables(self):
            return [[["年度", "營收"], ["2026", "AI/HPC 需求成長"]]]

    class FakePdf:
        pages = [FakePdfPage()]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

    fake_pdfplumber = SimpleNamespace(open=lambda _content: FakePdf())
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)
    monkeypatch.setenv("COMPANY_FILING_PDF_PARSER", "pdfplumber")
    monkeypatch.setenv("COMPANY_FILING_PDF_EXTRACT_TABLES", "true")
    get_settings.cache_clear()
    try:
        text = extract_pdf_text(b"%PDF fake")
    finally:
        get_settings.cache_clear()

    assert "台積電 2026 年報" in text
    assert "[PDF 解析資訊] parser=pdfplumber; mode=configured; extract_tables=true" in text
    assert "[PDF 表格抽取 p.1 #1]" in text
    assert "表格尺寸：2 列 x 2 欄" in text
    assert "年度 | 營收" in text
    assert "2026 | AI/HPC 需求成長" in text


def test_company_filing_pdf_parser_extracts_unstructured_tables_with_provenance(monkeypatch) -> None:
    calls = {}

    class FakeTableElement:
        category = "Table"
        metadata = SimpleNamespace(
            page_number=3,
            text_as_html=(
                "<table>"
                "<tr><th>年度</th><th>營收</th></tr>"
                "<tr><td>2026</td><td>AI/HPC 成長</td></tr>"
                "</table>"
            ),
        )

        def __str__(self) -> str:
            return "fallback table text"

    def fake_partition_pdf(**kwargs):
        calls["kwargs"] = kwargs
        return [FakeTableElement()]

    monkeypatch.setitem(
        sys.modules,
        "unstructured.partition.pdf",
        SimpleNamespace(partition_pdf=fake_partition_pdf),
    )
    monkeypatch.setenv("COMPANY_FILING_PDF_PARSER", "unstructured")
    monkeypatch.setenv("COMPANY_FILING_PDF_EXTRACT_TABLES", "true")
    get_settings.cache_clear()
    try:
        text = extract_pdf_text(b"%PDF fake")
    finally:
        get_settings.cache_clear()

    assert calls["kwargs"]["infer_table_structure"] is True
    assert "[PDF 解析資訊] parser=unstructured; mode=configured; extract_tables=true" in text
    assert "[PDF 表格抽取 p.3 #1]" in text
    assert "年度 | 營收" in text
    assert "2026 | AI/HPC 成長" in text


def test_company_filing_pdf_parser_unstructured_respects_table_toggle(monkeypatch) -> None:
    calls = {}

    class FakeTableElement:
        category = "Table"
        metadata = SimpleNamespace(
            page_number=1,
            text_as_html="<table><tr><td>年度</td><td>營收</td></tr></table>",
        )

        def __str__(self) -> str:
            return "年度 營收 2026 成長"

    def fake_partition_pdf(**kwargs):
        calls["kwargs"] = kwargs
        return [FakeTableElement()]

    monkeypatch.setitem(
        sys.modules,
        "unstructured.partition.pdf",
        SimpleNamespace(partition_pdf=fake_partition_pdf),
    )
    monkeypatch.setenv("COMPANY_FILING_PDF_PARSER", "unstructured")
    monkeypatch.setenv("COMPANY_FILING_PDF_EXTRACT_TABLES", "false")
    get_settings.cache_clear()
    try:
        text = extract_pdf_text(b"%PDF fake")
    finally:
        get_settings.cache_clear()

    assert calls["kwargs"]["infer_table_structure"] is False
    assert "[PDF 解析資訊] parser=unstructured; mode=configured; extract_tables=false" in text
    assert "[PDF 表格抽取" not in text
    assert "年度 營收 2026 成長" in text


def test_company_filing_pdf_without_text_has_actionable_error(monkeypatch) -> None:
    import pypdf

    class BlankPage:
        def extract_text(self) -> str:
            return ""

    monkeypatch.setattr(
        pypdf,
        "PdfReader",
        lambda _content: SimpleNamespace(pages=[BlankPage()]),
    )

    try:
        extract_pdf_text(b"%PDF fake")
    except ValueError as exc:
        assert PDF_IMPORT_NO_TEXT_MESSAGE in str(exc)
        assert "Visual RAG 後援失敗" in str(exc)
        assert "OCR" in str(exc)
        assert "文字版文件" in str(exc)
    else:
        raise AssertionError("PDF without extractable text should provide OCR guidance")


def test_company_filing_pdf_visual_rag_failure_preserves_fallback_reason(monkeypatch) -> None:
    def fake_extract_pypdf(_content: bytes) -> str:
        raise ValueError(PDF_IMPORT_NO_TEXT_MESSAGE)

    def fake_visual_extract(_content: bytes, *, reason: str):
        assert reason == PDF_IMPORT_NO_TEXT_MESSAGE
        raise ValueError("Visual RAG vision LLM API key 或本地 gateway 尚未配置。")

    monkeypatch.setenv("COMPANY_FILING_PDF_PARSER", "pypdf")
    monkeypatch.setenv("COMPANY_FILING_VISUAL_RAG_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_VISUAL_RAG_MODE", "fallback")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.data_sources.company_filings._extract_pdf_text_with_pypdf",
        fake_extract_pypdf,
    )
    monkeypatch.setattr("app.services.visual_rag.extract_visual_pdf_text", fake_visual_extract)
    try:
        extract_pdf_text(b"%PDF fake")
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("failed Visual RAG fallback should preserve diagnostics")
    finally:
        get_settings.cache_clear()

    assert PDF_IMPORT_NO_TEXT_MESSAGE in message
    assert "Visual RAG 後援失敗" in message
    assert "vision LLM API key" in message


def test_company_filing_pdf_without_text_can_use_visual_rag_fallback(monkeypatch) -> None:
    captured = {}

    def fake_extract_pypdf(_content: bytes) -> str:
        raise ValueError(PDF_IMPORT_NO_TEXT_MESSAGE)

    def fake_visual_extract(content: bytes, *, reason: str):
        captured["content"] = content
        captured["reason"] = reason
        return "[Visual RAG 解析資訊] mode=fallback\n營收 | 毛利率\n100 | 42%"

    monkeypatch.setenv("COMPANY_FILING_PDF_PARSER", "pypdf")
    monkeypatch.setenv("COMPANY_FILING_VISUAL_RAG_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_VISUAL_RAG_MODE", "fallback")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.data_sources.company_filings._extract_pdf_text_with_pypdf",
        fake_extract_pypdf,
    )
    monkeypatch.setattr("app.services.visual_rag.extract_visual_pdf_text", fake_visual_extract)
    try:
        text = extract_pdf_text(b"%PDF fake")
    finally:
        get_settings.cache_clear()

    assert captured["content"] == b"%PDF fake"
    assert captured["reason"] == PDF_IMPORT_NO_TEXT_MESSAGE
    assert "Visual RAG" in text
    assert "營收 | 毛利率" in text


def test_company_filing_url_validation_blocks_local_targets() -> None:
    validate_public_document_url("https://mops.twse.com.tw/server-java/t57sb01?co_id=2330")

    for url in [
        "file:///etc/passwd",
        "http://localhost:8000/internal",
        "http://127.0.0.1/internal",
        "http://192.168.1.10/report",
        "http://10.0.0.8/report",
        "http://example.local/report",
    ]:
        try:
            validate_public_document_url(url)
        except ValueError:
            continue
        raise AssertionError(f"unsafe URL should be rejected: {url}")


def test_fetched_company_filing_content_validation() -> None:
    valid = NewsFetcher.from_manual_text(
        title="台積電 2026 年報",
        text="台積電 2026 年報揭露 AI/HPC 需求、資本支出與風險因素。" * 8,
    )
    validate_fetched_company_filing_document(valid, "2330", "台積電", "annual_report")

    cases = [
        NewsFetcher.from_manual_text(title="短頁", text="台積電 年報"),
        NewsFetcher.from_manual_text(title="登入頁", text="請登入後查看文件內容。" * 20),
        NewsFetcher.from_manual_text(title="台積電 年報", text="台積電 年報 請啟用 JavaScript 後查看內容。" * 8),
        NewsFetcher.from_manual_text(title="台積電 新聞", text="台積電 今日股價上漲，市場關注短線表現。" * 8),
    ]
    for document in cases:
        try:
            validate_fetched_company_filing_document(document, "2330", "台積電", "annual_report")
        except ValueError:
            continue
        raise AssertionError(f"invalid fetched document should be rejected: {document.title}")
