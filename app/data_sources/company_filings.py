from __future__ import annotations

from datetime import date
from hashlib import sha1
import importlib
import json
from pathlib import Path
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from app.core.config import get_settings
from app.core.time import utc_now_naive
from app.data_sources.company_filing_discovery import (
    BLOCKED_OR_PLACEHOLDER_PAGE_PATTERNS as BLOCKED_OR_PLACEHOLDER_PAGE_PATTERNS,
    DISCLOSURE_TERMS as DISCLOSURE_TERMS,
    DOCUMENT_QUERY_TEMPLATES as DOCUMENT_QUERY_TEMPLATES,
    DOCUMENT_TYPE_KEYWORDS as DOCUMENT_TYPE_KEYWORDS,
    HIGH_QUALITY_FILING_SCORE as HIGH_QUALITY_FILING_SCORE,
    IR_SOURCE_HINTS as IR_SOURCE_HINTS,
    MAX_FETCHED_DOCUMENT_CHARS as MAX_FETCHED_DOCUMENT_CHARS,
    MIN_FETCHED_DOCUMENT_CHARS as MIN_FETCHED_DOCUMENT_CHARS,
    OFFICIAL_SOURCE_DOMAINS as OFFICIAL_SOURCE_DOMAINS,
    RECOMMENDED_DOCUMENT_TYPES as RECOMMENDED_DOCUMENT_TYPES,
    REQUIRED_CORE_DOCUMENT_TYPES as REQUIRED_CORE_DOCUMENT_TYPES,
    document_query_templates as document_query_templates,
    extract_company_filing_links as extract_company_filing_links,
    extract_html_redirect_url as extract_html_redirect_url,
    filing_quality_score as filing_quality_score,
    filing_source_tier as filing_source_tier,
    infer_document_type as infer_document_type,
    is_document_text_relevant as is_document_text_relevant,
    is_high_quality_company_filing as is_high_quality_company_filing,
    is_relevant_company_filing_result as is_relevant_company_filing_result,
    looks_like_blocked_or_placeholder_filing_page as looks_like_blocked_or_placeholder_filing_page,
    normalize_company_website as normalize_company_website,
    normalize_search_result_url as normalize_search_result_url,
    normalize_tpex_company_profile as normalize_tpex_company_profile,
    official_website_seed_urls as official_website_seed_urls,
    parse_mops_annual_report_rows as parse_mops_annual_report_rows,
    parse_mops_roc_datetime as parse_mops_roc_datetime,
    validate_fetched_company_filing_document as validate_fetched_company_filing_document,
    validate_public_document_url as validate_public_document_url,
)
from app.data_sources.company_filing_http import (
    COMPANY_FILING_RETRYABLE_HTTP_STATUSES as COMPANY_FILING_RETRYABLE_HTTP_STATUSES,
    RETRYABLE_COMPANY_FILING_ERROR_CATEGORIES as RETRYABLE_COMPANY_FILING_ERROR_CATEGORIES,
    categorize_company_filing_error as categorize_company_filing_error,
    company_filing_client_options as company_filing_client_options,
    company_filing_error as company_filing_error,
    company_filing_fetch_response_with_retries as company_filing_fetch_response_with_retries,
    company_filing_identity_headers_for_url as company_filing_identity_headers_for_url,
    company_filing_request_attempts as company_filing_request_attempts,
    company_filing_request_with_retries as company_filing_request_with_retries,
    company_filing_retry_delay_seconds as company_filing_retry_delay_seconds,
    company_filing_sleep_before_retry as company_filing_sleep_before_retry,
    is_retryable_company_filing_error_category as is_retryable_company_filing_error_category,
)
from app.data_sources.company_filing_parsers import (
    MAX_HTML_TABLES_PER_DOCUMENT as MAX_HTML_TABLES_PER_DOCUMENT,
    MAX_PDF_TABLES_PER_DOCUMENT as MAX_PDF_TABLES_PER_DOCUMENT,
    MAX_PDF_TABLE_CELL_CHARS as MAX_PDF_TABLE_CELL_CHARS,
    MAX_PDF_TABLE_COLUMNS as MAX_PDF_TABLE_COLUMNS,
    MAX_PDF_TABLE_ROWS as MAX_PDF_TABLE_ROWS,
    PDF_IMPORT_MISSING_PDFPLUMBER_MESSAGE as PDF_IMPORT_MISSING_PDFPLUMBER_MESSAGE,
    PDF_IMPORT_MISSING_PYPDF_MESSAGE as PDF_IMPORT_MISSING_PYPDF_MESSAGE,
    PDF_IMPORT_MISSING_UNSTRUCTURED_MESSAGE as PDF_IMPORT_MISSING_UNSTRUCTURED_MESSAGE,
    PDF_IMPORT_NO_TEXT_MESSAGE as PDF_IMPORT_NO_TEXT_MESSAGE,
    PDF_IMPORT_PARSE_ERROR_MESSAGE as PDF_IMPORT_PARSE_ERROR_MESSAGE,
    PDF_PARSER_PROVENANCE_PREFIX as PDF_PARSER_PROVENANCE_PREFIX,
    extract_company_filing_html_text as extract_company_filing_html_text,
    extract_pdf_text as extract_pdf_text,
    is_pdf_response as is_pdf_response,
    pdf_title_from_url as pdf_title_from_url,
)
from app.data_sources.company_filing_providers import (
    fetch_mops_annual_report_company_filing_documents as fetch_mops_annual_report_company_filing_documents,
    fetch_official_website_company_filing_documents as fetch_official_website_company_filing_documents,
    fetch_web_search_company_filing_documents as fetch_web_search_company_filing_documents,
)
from app.data_sources.company_filing_render import (
    BROWSER_RENDER_PROVIDERS as BROWSER_RENDER_PROVIDERS,
    BROWSER_RENDER_PROVIDER_CAPABILITIES as BROWSER_RENDER_PROVIDER_CAPABILITIES,
    BROWSER_RENDER_PROVIDER_CONTRACT_SMOKE_CLI as BROWSER_RENDER_PROVIDER_CONTRACT_SMOKE_CLI,
    DEFAULT_COMPANY_FILING_USER_AGENTS as DEFAULT_COMPANY_FILING_USER_AGENTS,
    HIGH_RISK_COMPANY_FILING_SOURCE_DOMAINS as HIGH_RISK_COMPANY_FILING_SOURCE_DOMAINS,
    UNLOCKER_BROWSER_RENDER_PROVIDERS as UNLOCKER_BROWSER_RENDER_PROVIDERS,
    company_filing_browser_render_configured as company_filing_browser_render_configured,
    company_filing_browser_render_limiter as company_filing_browser_render_limiter,
    company_filing_browser_render_provider as company_filing_browser_render_provider,
    company_filing_browser_render_provider_capability as company_filing_browser_render_provider_capability,
    company_filing_browser_render_provider_contract_status as company_filing_browser_render_provider_contract_status,
    company_filing_browser_render_request as company_filing_browser_render_request,
    company_filing_browser_render_response_text as company_filing_browser_render_response_text,
    company_filing_browser_render_status as company_filing_browser_render_status,
    company_filing_identity_for_url as company_filing_identity_for_url,
    company_filing_playwright_available as company_filing_playwright_available,
    company_filing_playwright_browser_status as company_filing_playwright_browser_status,
    company_filing_playwright_render_enabled as company_filing_playwright_render_enabled,
    company_filing_proxy_for_url as company_filing_proxy_for_url,
    company_filing_proxy_urls as company_filing_proxy_urls,
    company_filing_render_fallback_configured as company_filing_render_fallback_configured,
    company_filing_user_agent_for_url as company_filing_user_agent_for_url,
    company_filing_user_agents as company_filing_user_agents,
)
from app.data_sources.company_filing_sources import (
    MAX_FETCHED_DOCUMENT_BYTES as MAX_FETCHED_DOCUMENT_BYTES,
    OFFICIAL_WEBSITE_FETCH_TIMEOUT_SECONDS as OFFICIAL_WEBSITE_FETCH_TIMEOUT_SECONDS,
    company_profile_from_rows as company_profile_from_rows,
    download_mops_pdf as download_mops_pdf,
    duckduckgo_company_filing_search as duckduckgo_company_filing_search,
    fetch_company_filing_url_text as fetch_company_filing_url_text,
    fetch_company_filing_url_text_with_final_url as fetch_company_filing_url_text_with_final_url,
    fetch_tpex_company_profiles as fetch_tpex_company_profiles,
    fetch_twse_company_profiles as fetch_twse_company_profiles,
)
from app.data_sources.company_filing_structured_api import (
    STRUCTURED_API_PROVIDER_PROFILES as STRUCTURED_API_PROVIDER_PROFILES,
    STRUCTURED_API_REQUIRED_DOCUMENT_FIELDS as STRUCTURED_API_REQUIRED_DOCUMENT_FIELDS,
    STRUCTURED_API_RESPONSE_ROW_ALIASES as STRUCTURED_API_RESPONSE_ROW_ALIASES,
    STRUCTURED_API_SAMPLE_CONTRACT_PATH as STRUCTURED_API_SAMPLE_CONTRACT_PATH,
    company_filing_structured_api_configured as company_filing_structured_api_configured,
    company_filing_structured_api_status_payload,
    parse_structured_api_date as parse_structured_api_date,
    structured_api_document_type as structured_api_document_type,
    structured_api_document_rows as structured_api_document_rows,
    structured_api_enriched_text as structured_api_enriched_text,
    structured_api_provider_profile as structured_api_provider_profile,
    structured_api_request_contract as structured_api_request_contract,
    structured_api_row_to_news_document as structured_api_row_to_news_document,
    structured_api_row_text as structured_api_row_text,
    structured_api_row_value as structured_api_row_value,
)
from app.data_sources.news import NewsFetcher
from app.models.schemas import CompanyFilingDocument, NewsDocument, Source
from app.services.company_filing_cache import RedisCompanyFilingCache


def company_filing_structured_api_status() -> dict:
    settings = get_settings()
    return company_filing_structured_api_status_payload(
        settings,
        retry_policy={
            "attempts": company_filing_request_attempts(),
            "retryable_http_statuses": sorted(COMPANY_FILING_RETRYABLE_HTTP_STATUSES),
            "base_retry_delay_seconds": max(
                0.0,
                float(settings.company_filing_base_retry_delay_seconds),
            ),
            "max_retry_delay_seconds": max(
                0.0,
                float(settings.company_filing_max_retry_delay_seconds),
            ),
        },
        sample_contract=structured_api_sample_contract_status(),
    )


def structured_api_sample_contract_status(sample_path: Path | None = None) -> dict:
    path = sample_path or Path(__file__).resolve().parents[2] / STRUCTURED_API_SAMPLE_CONTRACT_PATH
    smoke_cli = (
        ".venv/bin/python scripts/structured_company_filing_smoke.py "
        "--sample-json examples/structured_company_filing_sample.json "
        "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return {
            "status": "failed",
            "ready": False,
            "mode": "sample_json_contract",
            "sample_path": str(path),
            "raw_row_count": 0,
            "document_count": 0,
            "error_count": 1,
            "errors": [{"category": "sample_json_unreadable", "message": str(exc)}],
            "smoke_cli": smoke_cli,
        }
    except json.JSONDecodeError as exc:
        return {
            "status": "failed",
            "ready": False,
            "mode": "sample_json_contract",
            "sample_path": str(path),
            "raw_row_count": 0,
            "document_count": 0,
            "error_count": 1,
            "errors": [{"category": "sample_json_invalid", "message": str(exc)}],
            "smoke_cli": smoke_cli,
        }

    rows = structured_api_document_rows(payload)
    parser = CompanyFilingFetcher()
    documents: list[CompanyFilingDocument] = []
    errors: list[dict] = []
    for index, row in enumerate(rows):
        document = parser._structured_api_row_to_document(
            row,
            ticker="2330",
            company_name="台積電",
            provider="sample",
            document_types=("investor_presentation",),
        )
        if document:
            documents.append(document)
        else:
            errors.append(
                {
                    "row_index": index,
                    "category": "row_not_convertible",
                    "required_fields": list(STRUCTURED_API_REQUIRED_DOCUMENT_FIELDS),
                }
            )
    if documents:
        status = "ready"
    elif rows:
        status = "degraded"
    else:
        status = "failed"
    return {
        "status": status,
        "ready": status == "ready",
        "mode": "sample_json_contract",
        "sample_path": str(path),
        "raw_row_count": len(rows),
        "document_count": len(documents),
        "error_count": len(errors),
        "errors": errors[:10],
        "smoke_cli": smoke_cli,
    }


class CompanyFilingFetcher:
    _twse_profile_cache: list[dict] | None = None
    _tpex_profile_cache: list[dict] | None = None

    def __init__(self, cache: RedisCompanyFilingCache | None = None) -> None:
        self.news_fetcher = NewsFetcher()
        self.cache = cache or RedisCompanyFilingCache()

    @staticmethod
    def official_search_queries(
        ticker: str,
        name: str = "",
        limit: int | None = None,
        document_types: list[str] | tuple[str, ...] | None = None,
    ) -> list[str]:
        templates = document_query_templates(document_types)
        templates = templates if limit is None else templates[:limit]
        return [template.format(ticker=ticker, name=name).strip() for template in templates]

    @classmethod
    def google_news_urls(
        cls,
        ticker: str,
        name: str = "",
        limit: int | None = None,
        document_types: list[str] | tuple[str, ...] | None = None,
    ) -> list[str]:
        urls = []
        for query_text in cls.official_search_queries(ticker, name, limit, document_types):
            query = quote_plus(query_text)
            urls.append(f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
        return urls

    @classmethod
    def official_search_plan(
        cls,
        ticker: str,
        name: str = "",
        document_types: list[str] | tuple[str, ...] | None = None,
    ) -> dict:
        queries = cls.official_search_queries(ticker, name, document_types=document_types)
        return {
            "ticker": ticker,
            "company_name": name,
            "document_types": list(document_types or []),
            "queries": queries,
            "google_news_urls": cls.google_news_urls(ticker, name, document_types=document_types),
            "official_portals": [
                {
                    "name": "公開資訊觀測站",
                    "url": "https://mops.twse.com.tw/mops/web/index",
                    "purpose": "年報、公開說明書、法人說明會與重大訊息原始揭露。",
                },
                {
                    "name": "臺灣證券交易所",
                    "url": "https://www.twse.com.tw/",
                    "purpose": "上市公司基本資料、重大訊息與市場公告交叉核對。",
                },
                {
                    "name": "櫃買中心",
                    "url": "https://www.tpex.org.tw/",
                    "purpose": "上櫃公司公告、財報與重大訊息交叉核對。",
                },
            ],
        }

    @staticmethod
    def from_news_document(
        document: NewsDocument,
        ticker: str,
        company_name: str = "",
        document_type: str | None = None,
    ) -> CompanyFilingDocument:
        inferred_type = document_type or infer_document_type(f"{document.title}\n{document.text}")
        digest = sha1(f"{ticker}:{inferred_type}:{document.source.url or document.id}".encode("utf-8")).hexdigest()
        return CompanyFilingDocument(
            id=digest,
            ticker=ticker,
            company_name=company_name or None,
            document_type=inferred_type,
            title=document.title,
            text=document.text,
            source=document.source,
        )

    @staticmethod
    def from_manual_text(
        ticker: str,
        title: str,
        text: str,
        company_name: str = "",
        document_type: str = "company_disclosure",
        publisher: str = "manual company filing",
        published_at: date | None = None,
        url: str | None = None,
    ) -> CompanyFilingDocument:
        digest = sha1(f"{ticker}:{document_type}:{url or title}:{text[:80]}".encode("utf-8")).hexdigest()
        return CompanyFilingDocument(
            id=digest,
            ticker=ticker,
            company_name=company_name or None,
            document_type=document_type,
            title=title,
            text=text,
            source=Source(
                title=title,
                url=url,
                publisher=publisher,
                published_at=published_at,
                fetched_at=utc_now_naive(),
            ),
        )

    async def fetch_url_document(
        self,
        url: str,
        ticker: str,
        company_name: str = "",
        document_type: str = "company_disclosure",
        publisher: str | None = None,
        published_at: date | None = None,
    ) -> CompanyFilingDocument:
        validate_public_document_url(url)
        document = self._cached_url_document(url)
        if document is None:
            document = await self._fetch_valid_url_as_document(
                url,
                ticker=ticker,
                company_name=company_name,
                document_type=document_type,
                publisher=publisher,
            )
            self._store_cached_url_document(url, document)
        else:
            try:
                validate_fetched_company_filing_document(document, ticker, company_name, document_type)
            except ValueError:
                document = await self._fetch_valid_url_as_document(
                    url,
                    ticker=ticker,
                    company_name=company_name,
                    document_type=document_type,
                    publisher=publisher,
                )
                self._store_cached_url_document(url, document)
        return self.from_manual_text(
            ticker=ticker,
            company_name=company_name,
            document_type=document_type,
            title=document.title,
            text=document.text,
            publisher=publisher or document.source.publisher or "company filing url",
            published_at=published_at or document.source.published_at,
            url=document.source.url or url,
        )

    async def _fetch_valid_url_as_document(
        self,
        url: str,
        ticker: str,
        company_name: str,
        document_type: str,
        publisher: str | None = None,
    ) -> NewsDocument:
        direct_error: Exception | None = None
        try:
            document = await self._fetch_url_as_document(url, publisher=publisher)
            validate_fetched_company_filing_document(document, ticker, company_name, document_type)
            return document
        except Exception as exc:
            direct_error = exc

        if not company_filing_render_fallback_configured():
            raise direct_error

        render_errors: list[str] = []
        last_render_error: Exception | None = None

        if company_filing_browser_render_configured():
            try:
                rendered_document = await self._fetch_browser_rendered_url_as_document(
                    url,
                    publisher=publisher,
                )
                validate_fetched_company_filing_document(
                    rendered_document,
                    ticker,
                    company_name,
                    document_type,
                )
                return rendered_document
            except Exception as render_error:
                last_render_error = render_error
                render_errors.append(f"browser render error: {render_error}")

        if company_filing_playwright_render_enabled():
            try:
                rendered_document = await self._fetch_playwright_rendered_url_as_document(
                    url,
                    publisher=publisher,
                )
                validate_fetched_company_filing_document(
                    rendered_document,
                    ticker,
                    company_name,
                    document_type,
                )
                return rendered_document
            except Exception as render_error:
                last_render_error = render_error
                render_errors.append(f"playwright render error: {render_error}")

        raise ValueError(
            "company filing render fallback failed after direct fetch issue: "
            f"{direct_error}; {'; '.join(render_errors) if render_errors else 'no render fallback attempted'}"
        ) from last_render_error

    def _cached_url_document(self, url: str) -> NewsDocument | None:
        settings = get_settings()
        return self.cache.get_url_document(
            url,
            parser=settings.company_filing_pdf_parser,
            extract_tables=settings.company_filing_pdf_extract_tables,
            html_extract_tables=settings.company_filing_html_extract_tables,
        )

    def _store_cached_url_document(self, url: str, document: NewsDocument) -> None:
        settings = get_settings()
        self.cache.set_url_document(
            url,
            document,
            parser=settings.company_filing_pdf_parser,
            extract_tables=settings.company_filing_pdf_extract_tables,
            html_extract_tables=settings.company_filing_html_extract_tables,
        )

    async def _fetch_url_as_document(self, url: str, publisher: str | None = None) -> NewsDocument:
        response = await company_filing_fetch_response_with_retries(
            "GET",
            url,
            timeout=20,
            follow_redirects=True,
        )
        content_length = int(response.headers.get("content-length") or 0)
        if content_length > MAX_FETCHED_DOCUMENT_BYTES or len(response.content) > MAX_FETCHED_DOCUMENT_BYTES:
            raise ValueError("company filing content is too large to import")
        content_type = response.headers.get("content-type", "").lower()
        if is_pdf_response(url, content_type):
            return self._pdf_response_to_document(url, response.content, publisher)
        soup = BeautifulSoup(response.text, "html.parser")
        title = NewsFetcher._title(soup) or url
        text = extract_company_filing_html_text(soup)
        return NewsDocument(
            id=sha1(url.encode("utf-8")).hexdigest(),
            title=title,
            text=text,
            source=Source(
                title=title,
                url=url,
                publisher=publisher,
                published_at=NewsFetcher._published_date(soup),
                fetched_at=utc_now_naive(),
            ),
        )

    async def _fetch_browser_rendered_url_as_document(
        self,
        url: str,
        publisher: str | None = None,
    ) -> NewsDocument:
        settings = get_settings()
        endpoint = settings.company_filing_browser_render_url.strip()
        if not endpoint:
            raise ValueError("company filing browser render URL is not configured")
        validate_public_document_url(url)
        provider = company_filing_browser_render_provider()
        if provider not in BROWSER_RENDER_PROVIDERS:
            raise ValueError(f"unsupported company filing browser render provider: {provider}")
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": company_filing_user_agent_for_url(url),
        }
        token = settings.company_filing_browser_render_token.strip()
        timeout = max(1.0, float(settings.company_filing_browser_render_timeout_seconds))
        rendered_url, method, request_kwargs = company_filing_browser_render_request(
            provider=provider,
            endpoint=endpoint,
            target_url=url,
            headers=headers,
            token=token,
            timeout_seconds=timeout,
        )
        async with company_filing_browser_render_limiter():
            response = await company_filing_fetch_response_with_retries(
                method,
                rendered_url,
                timeout=timeout,
                follow_redirects=True,
                identity_url=url,
                **request_kwargs,
            )
        content_length = int(response.headers.get("content-length") or 0)
        if content_length > MAX_FETCHED_DOCUMENT_BYTES or len(response.content) > MAX_FETCHED_DOCUMENT_BYTES:
            raise ValueError("company filing browser-rendered content is too large to import")
        content_type = response.headers.get("content-type", "").lower()
        if "application/pdf" in content_type:
            return self._pdf_response_to_document(url, response.content, publisher)
        html, final_url = company_filing_browser_render_response_text(
            response,
            provider=provider,
            target_url=url,
        )
        soup = BeautifulSoup(html, "html.parser")
        title = NewsFetcher._title(soup) or final_url
        text = extract_company_filing_html_text(soup)
        return NewsDocument(
            id=sha1(f"browser-rendered:{url}".encode("utf-8")).hexdigest(),
            title=title,
            text=text,
            source=Source(
                title=title,
                url=final_url,
                publisher=publisher,
                published_at=NewsFetcher._published_date(soup),
                fetched_at=utc_now_naive(),
            ),
        )

    async def _fetch_playwright_rendered_url_as_document(
        self,
        url: str,
        publisher: str | None = None,
    ) -> NewsDocument:
        settings = get_settings()
        validate_public_document_url(url)
        try:
            playwright_api = importlib.import_module("playwright.async_api")
        except Exception as exc:
            raise ValueError("company filing Playwright render dependency is not installed") from exc

        async_playwright = getattr(playwright_api, "async_playwright", None)
        if async_playwright is None:
            raise ValueError("company filing Playwright render dependency is not installed")

        browser_name = str(settings.company_filing_playwright_browser or "chromium").strip().lower()
        wait_until = str(settings.company_filing_playwright_wait_until or "networkidle").strip()
        timeout_ms = int(max(1.0, float(settings.company_filing_playwright_timeout_seconds)) * 1000)
        html = ""
        final_url = url

        async with async_playwright() as playwright:
            launcher = getattr(playwright, browser_name, None)
            if launcher is None:
                raise ValueError(f"unsupported company filing Playwright browser: {browser_name}")
            browser = await launcher.launch(headless=True)
            try:
                page = await browser.new_page(
                    user_agent=company_filing_user_agent_for_url(url),
                    locale="zh-TW",
                )
                await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
                html = await page.content()
                final_url = str(getattr(page, "url", "") or url)
            finally:
                await browser.close()

        if len(html.encode("utf-8")) > MAX_FETCHED_DOCUMENT_BYTES:
            raise ValueError("company filing Playwright-rendered content is too large to import")
        soup = BeautifulSoup(html, "html.parser")
        title = NewsFetcher._title(soup) or final_url
        text = extract_company_filing_html_text(soup)
        return NewsDocument(
            id=sha1(f"playwright-rendered:{url}".encode("utf-8")).hexdigest(),
            title=title,
            text=text,
            source=Source(
                title=title,
                url=final_url,
                publisher=publisher,
                published_at=NewsFetcher._published_date(soup),
                fetched_at=utc_now_naive(),
            ),
        )

    @staticmethod
    def _pdf_response_to_document(
        url: str,
        content: bytes,
        publisher: str | None = None,
    ) -> NewsDocument:
        text = extract_pdf_text(content)
        title = pdf_title_from_url(url)
        return NewsDocument(
            id=sha1(url.encode("utf-8")).hexdigest(),
            title=title,
            text=text,
            source=Source(
                title=title,
                url=url,
                publisher=publisher,
                fetched_at=utc_now_naive(),
            ),
        )

    async def fetch_discovery_documents(
        self,
        ticker: str,
        company_name: str = "",
        limit_per_query: int = 3,
        document_types: list[str] | tuple[str, ...] | None = None,
    ) -> tuple[list[CompanyFilingDocument], list[dict]]:
        documents: list[CompanyFilingDocument] = []
        errors = []
        structured_documents, structured_errors = await self.fetch_structured_api_documents(
            ticker,
            company_name,
            limit=limit_per_query,
            document_types=document_types,
        )
        documents.extend(structured_documents)
        errors.extend(structured_errors)
        for url in self.google_news_urls(ticker, company_name, document_types=document_types):
            try:
                feed_documents = await self.news_fetcher.fetch_feed(
                    url,
                    publisher="Google News company filings",
                    limit=limit_per_query,
                )
            except Exception as exc:
                errors.append(company_filing_error(url, exc, stage="discovery_feed"))
                continue
            for document in feed_documents:
                if not is_relevant_company_filing_result(document, ticker, company_name):
                    continue
                documents.append(self.from_news_document(document, ticker, company_name))
        return documents, errors

    async def fetch_structured_api_documents(
        self,
        ticker: str,
        company_name: str = "",
        limit: int = 3,
        document_types: list[str] | tuple[str, ...] | None = None,
    ) -> tuple[list[CompanyFilingDocument], list[dict]]:
        if not company_filing_structured_api_configured():
            return [], []
        settings = get_settings()
        endpoint = str(settings.company_filing_structured_api_url or "").strip()
        provider = str(settings.company_filing_structured_api_provider or "").strip().lower()
        token = str(settings.company_filing_structured_api_token or "").strip()
        request_contract = structured_api_request_contract(
            provider=provider,
            endpoint=endpoint,
            token=token,
            ticker=ticker,
            company_name=company_name,
            limit=limit,
            document_types=document_types,
        )
        try:
            response = await company_filing_fetch_response_with_retries(
                request_contract["method"],
                request_contract["endpoint"],
                timeout=max(1.0, float(settings.company_filing_structured_api_timeout_seconds)),
                follow_redirects=True,
                headers=request_contract["headers"],
                params=request_contract["params"],
            )
            rows = structured_api_document_rows(response.json())
            if not rows:
                return [], [
                    company_filing_error(
                        endpoint,
                        (
                            "structured API response did not contain document rows; "
                            f"expected one of {', '.join(STRUCTURED_API_RESPONSE_ROW_ALIASES)}"
                        ),
                        stage="structured_api",
                    )
                ]
            documents = [
                document
                for row in rows
                if (
                    document := self._structured_api_row_to_document(
                        row,
                        ticker=ticker,
                        company_name=company_name,
                        provider=provider,
                        document_types=document_types,
                    )
                )
            ]
            if rows and not documents:
                return [], [
                    company_filing_error(
                        endpoint,
                        (
                            "structured API rows were not convertible; required fields are "
                            f"{', '.join(STRUCTURED_API_REQUIRED_DOCUMENT_FIELDS)}"
                        ),
                        stage="structured_api",
                    )
                ]
            return documents[: max(1, int(limit))], []
        except Exception as exc:
            return [], [company_filing_error(endpoint, exc, stage="structured_api")]

    def _structured_api_row_to_document(
        self,
        row: dict,
        *,
        ticker: str,
        company_name: str,
        provider: str,
        document_types: list[str] | tuple[str, ...] | None = None,
    ) -> CompanyFilingDocument | None:
        parsed = structured_api_row_to_news_document(
            row,
            ticker=ticker,
            company_name=company_name,
            provider=provider,
            document_types=document_types,
        )
        if not parsed:
            return None
        news_document, document_type = parsed
        return self.from_news_document(news_document, ticker, company_name, document_type=document_type)

    async def fetch_web_search_documents(
        self,
        ticker: str,
        company_name: str = "",
        limit_per_query: int = 5,
        document_types: list[str] | tuple[str, ...] | None = None,
    ) -> tuple[list[CompanyFilingDocument], list[dict]]:
        return await fetch_web_search_company_filing_documents(
            ticker=ticker,
            company_name=company_name,
            queries=self.official_search_queries(ticker, company_name, document_types=document_types),
            limit_per_query=limit_per_query,
            document_types=document_types,
            search_func=self._duckduckgo_search,
            fetch_url_document_func=self.fetch_url_document,
        )

    async def fetch_mops_annual_report_documents(
        self,
        ticker: str,
        company_name: str = "",
        years: int = 3,
    ) -> tuple[list[CompanyFilingDocument], list[dict]]:
        return await fetch_mops_annual_report_company_filing_documents(
            ticker=ticker,
            company_name=company_name,
            years=years,
            fetch_url_text_func=self._fetch_url_text,
            download_mops_pdf_func=self._download_mops_pdf,
            build_manual_document_func=self.from_manual_text,
        )

    @staticmethod
    async def _download_mops_pdf(ticker: str, filename: str, kind: str) -> tuple[str, bytes]:
        return await download_mops_pdf(ticker, filename, kind)

    async def fetch_official_website_documents(
        self,
        ticker: str,
        company_name: str = "",
        limit: int = 12,
        document_types: list[str] | tuple[str, ...] | None = None,
    ) -> tuple[list[CompanyFilingDocument], list[dict]]:
        return await fetch_official_website_company_filing_documents(
            ticker=ticker,
            company_name=company_name,
            limit=limit,
            document_types=document_types,
            profile_func=self.twse_company_profile,
            fetch_url_text_with_final_url_func=self._fetch_url_text_with_final_url,
            fetch_url_document_func=self.fetch_url_document,
        )

    @staticmethod
    async def _fetch_url_text(
        url: str,
        encoding: str | None = None,
        timeout: int = 20,
    ) -> str:
        return await fetch_company_filing_url_text(
            url,
            encoding=encoding,
            timeout=timeout,
        )

    @staticmethod
    async def _fetch_url_text_with_final_url(
        url: str,
        encoding: str | None = None,
        timeout: int = 20,
        max_html_redirects: int = 2,
    ) -> tuple[str, str]:
        return await fetch_company_filing_url_text_with_final_url(
            url,
            encoding=encoding,
            timeout=timeout,
            max_html_redirects=max_html_redirects,
        )

    @classmethod
    async def twse_company_profile(cls, ticker: str) -> dict:
        if cls._twse_profile_cache is None:
            cls._twse_profile_cache = await fetch_twse_company_profiles()
        profile = company_profile_from_rows(
            ticker,
            twse_rows=cls._twse_profile_cache,
            tpex_rows=[],
        )
        if profile:
            return profile
        if cls._tpex_profile_cache is None:
            cls._tpex_profile_cache = await fetch_tpex_company_profiles()
        return company_profile_from_rows(
            ticker,
            twse_rows=[],
            tpex_rows=cls._tpex_profile_cache,
        )

    @staticmethod
    async def _duckduckgo_search(query_text: str, limit: int = 5) -> list[dict]:
        return await duckduckgo_company_filing_search(query_text, limit)
