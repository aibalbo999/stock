from __future__ import annotations

import asyncio
from datetime import date
from hashlib import sha1
import importlib
from ipaddress import ip_address
from io import BytesIO
from pathlib import Path
import re
import socket
from urllib.parse import parse_qs, quote, quote_plus, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.core.config import get_settings
from app.core.time import utc_now_naive
from app.data_sources.news import NewsFetcher
from app.models.schemas import CompanyFilingDocument, NewsDocument, Source
from app.services.company_filing_cache import RedisCompanyFilingCache


DOCUMENT_QUERY_TEMPLATES = (
    "{ticker} {name} 年報 法說會 公開說明書 filetype:pdf",
    "{ticker} {name} investor presentation annual report filetype:pdf",
    "{ticker} {name} 公開資訊觀測站 年報 site:mops.twse.com.tw",
    "{ticker} {name} 股東會年報 site:doc.twse.com.tw",
    "{ticker} {name} 法人說明會 site:mops.twse.com.tw",
    "{ticker} {name} 法說會 簡報 site:doc.twse.com.tw",
    "{ticker} {name} investor relations presentation",
    "{ticker} {name} IR annual report investor relations",
)

DOCUMENT_TYPE_KEYWORDS = {
    "annual_report": ("年報", "annual report", "股東會年報"),
    "investor_presentation": ("法說", "法人說明", "investor presentation", "earnings presentation"),
    "prospectus": ("公開說明書", "prospectus", "募集", "增資"),
    "material_information": ("重大訊息", "material information", "mops"),
}
DISCLOSURE_TERMS = tuple(
    keyword
    for keywords in DOCUMENT_TYPE_KEYWORDS.values()
    for keyword in keywords
)
OFFICIAL_SOURCE_DOMAINS = (
    "mops.twse.com.tw",
    "mopsov.twse.com.tw",
    "doc.twse.com.tw",
    "twse.com.tw",
    "tpex.org.tw",
)
IR_SOURCE_HINTS = (
    "ir.",
    "/ir",
    "investor",
    "investors",
    "investor-relations",
    "investor_relations",
)
HIGH_QUALITY_FILING_SCORE = 70
MIN_FETCHED_DOCUMENT_CHARS = 120
MAX_FETCHED_DOCUMENT_CHARS = 500_000
MAX_FETCHED_DOCUMENT_BYTES = 20_000_000
OFFICIAL_WEBSITE_FETCH_TIMEOUT_SECONDS = 8
COMPANY_FILING_RETRYABLE_HTTP_STATUSES = {403, 429, 500, 502, 503, 504}
BROWSER_RENDER_PROVIDERS = {"browserless", "generic", "flaresolverr", "scrapingbee", "brightdata"}
PDF_PARSER_PROVENANCE_PREFIX = "[PDF 解析資訊]"
RETRYABLE_COMPANY_FILING_ERROR_CATEGORIES = {
    "blocked_or_forbidden",
    "blocked_or_placeholder",
    "browser_render_failed",
    "network_error",
    "rate_limited",
    "timeout",
    "upstream_retryable",
}
BLOCKED_OR_PLACEHOLDER_PAGE_PATTERNS = (
    "access denied",
    "captcha",
    "cloudflare",
    "enable javascript",
    "forbidden",
    "javascript is disabled",
    "request blocked",
    "too many requests",
    "請先登入",
    "請啟用 javascript",
    "登入後查看",
    "機器人驗證",
    "驗證碼",
)
DEFAULT_COMPANY_FILING_USER_AGENTS = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
)
PDF_IMPORT_MISSING_PYPDF_MESSAGE = "PDF 匯入需要安裝 pypdf，請先完成系統相依套件安裝後再重試。"
PDF_IMPORT_MISSING_PDFPLUMBER_MESSAGE = "PDF 匯入設定為 pdfplumber，但尚未安裝 pdfplumber；請安裝 PDF 額外相依套件後再重試。"
PDF_IMPORT_MISSING_UNSTRUCTURED_MESSAGE = "PDF 匯入設定為 unstructured，但尚未安裝 unstructured[pdf]；請安裝 PDF 額外相依套件後再重試。"
PDF_IMPORT_PARSE_ERROR_MESSAGE = "PDF 公司文件無法解析，可能是檔案加密、損毀或格式不支援；請改用官方 HTML 頁面，或人工貼上文字版內容。"
PDF_IMPORT_NO_TEXT_MESSAGE = "PDF 公司文件沒有可抽取文字，可能是掃描圖檔；請先 OCR 成文字後再貼上，或改用官方 HTML/文字版文件。"
REQUIRED_CORE_DOCUMENT_TYPES = ("annual_report",)
RECOMMENDED_DOCUMENT_TYPES = ("investor_presentation",)
MAX_PDF_TABLES_PER_DOCUMENT = 80
MAX_HTML_TABLES_PER_DOCUMENT = 80
MAX_PDF_TABLE_ROWS = 120
MAX_PDF_TABLE_COLUMNS = 14
MAX_PDF_TABLE_CELL_CHARS = 160
_BROWSER_RENDER_SEMAPHORES: dict[tuple[int, int], asyncio.Semaphore] = {}


def _split_config_values(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[\n,]+", value or "") if item.strip()]


def _stable_config_choice(
    values: list[str] | tuple[str, ...],
    key: str,
    attempt: int = 0,
) -> str:
    if not values:
        return ""
    digest = sha1(key.encode("utf-8")).hexdigest()
    offset = max(0, int(attempt))
    return values[(int(digest[:8], 16) + offset) % len(values)]


def company_filing_user_agents() -> list[str]:
    configured = _split_config_values(get_settings().company_filing_user_agents)
    return configured or list(DEFAULT_COMPANY_FILING_USER_AGENTS)


def company_filing_proxy_urls() -> list[str]:
    return _split_config_values(get_settings().company_filing_proxy_urls)


def company_filing_identity_for_url(url: str, attempt: int = 0) -> dict:
    user_agents = company_filing_user_agents()
    proxy_urls = company_filing_proxy_urls()
    return {
        "attempt": max(0, int(attempt)),
        "user_agent": _stable_config_choice(user_agents, url, attempt),
        "proxy": _stable_config_choice(proxy_urls, url, attempt) or None,
        "user_agent_count": len(user_agents),
        "proxy_count": len(proxy_urls),
    }


def company_filing_user_agent_for_url(url: str, attempt: int = 0) -> str:
    return str(company_filing_identity_for_url(url, attempt).get("user_agent") or "")


def company_filing_proxy_for_url(url: str, attempt: int = 0) -> str | None:
    proxy = company_filing_identity_for_url(url, attempt).get("proxy")
    return str(proxy) if proxy else None


def company_filing_browser_render_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.company_filing_browser_render_enabled
        and settings.company_filing_browser_render_url.strip()
        and company_filing_browser_render_provider() in BROWSER_RENDER_PROVIDERS
    )


def company_filing_browser_render_provider() -> str:
    provider = str(getattr(get_settings(), "company_filing_browser_render_provider", "browserless") or "")
    provider = provider.strip().lower().replace("-", "_")
    return provider or "browserless"


def company_filing_browser_render_status(
    *,
    enabled: bool | None = None,
    endpoint: str | None = None,
    timeout_seconds: float | None = None,
) -> dict:
    settings = get_settings()
    render_enabled = (
        settings.company_filing_browser_render_enabled
        if enabled is None
        else bool(enabled)
    )
    render_endpoint = str(
        settings.company_filing_browser_render_url if endpoint is None else endpoint
    ).strip()
    configured_timeout = (
        settings.company_filing_browser_render_timeout_seconds
        if timeout_seconds is None
        else timeout_seconds
    )
    timeout = max(
        0.2,
        min(5.0, float(configured_timeout)),
    )
    status = {
        "enabled": bool(render_enabled),
        "provider": company_filing_browser_render_provider(),
        "supported_providers": sorted(BROWSER_RENDER_PROVIDERS),
        "url_configured": bool(render_endpoint),
        "endpoint": render_endpoint,
        "connection_checked": False,
        "endpoint_reachable": False,
        "runtime_available": False,
        "smoke_cli": ".venv/bin/python scripts/company_filing_render_smoke.py --url https://example.com/ --json",
        "fallback_reason": None,
    }
    if not render_enabled:
        status["fallback_reason"] = "browser_render_disabled"
        return status
    if status["provider"] not in BROWSER_RENDER_PROVIDERS:
        status["fallback_reason"] = "unsupported_browser_render_provider"
        return status
    if not render_endpoint:
        status["fallback_reason"] = "missing_browser_render_url"
        return status

    parsed = urlparse(render_endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        status["fallback_reason"] = "invalid_browser_render_url"
        return status
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=timeout):
            pass
    except OSError as exc:
        status["connection_checked"] = True
        status["fallback_reason"] = f"browser_render_endpoint_unreachable:{exc.__class__.__name__}"
        return status

    status["connection_checked"] = True
    status["endpoint_reachable"] = True
    status["runtime_available"] = True
    return status


def company_filing_browser_render_concurrency() -> int:
    return max(1, int(get_settings().company_filing_browser_render_concurrency))


def company_filing_browser_render_limiter() -> asyncio.Semaphore:
    limit = company_filing_browser_render_concurrency()
    loop = asyncio.get_running_loop()
    key = (id(loop), limit)
    semaphore = _BROWSER_RENDER_SEMAPHORES.get(key)
    if semaphore is None:
        semaphore = asyncio.Semaphore(limit)
        _BROWSER_RENDER_SEMAPHORES[key] = semaphore
    return semaphore


def company_filing_browser_render_request(
    *,
    provider: str,
    endpoint: str,
    target_url: str,
    headers: dict[str, str],
    token: str,
    timeout_seconds: float,
) -> tuple[str, str, dict]:
    provider = (provider or "browserless").strip().lower().replace("-", "_")
    rendered_url = endpoint
    if "{url}" in endpoint:
        return endpoint.format(url=quote(target_url, safe="")), "GET", {"headers": headers}
    if provider == "flaresolverr":
        return (
            rendered_url,
            "POST",
            {
                "headers": {**headers, "Content-Type": "application/json"},
                "json": {
                    "cmd": "request.get",
                    "url": target_url,
                    "maxTimeout": int(max(1.0, timeout_seconds) * 1000),
                },
            },
        )
    if provider == "scrapingbee":
        params = {"url": target_url, "render_js": "true"}
        if token:
            params["api_key"] = token
        return rendered_url, "GET", {"headers": headers, "params": params}
    if provider == "brightdata":
        request_headers = dict(headers)
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        return (
            rendered_url,
            "POST",
            {
                "headers": request_headers,
                "json": {"url": target_url, "format": "raw"},
            },
        )

    request_headers = dict(headers)
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    return (
        rendered_url,
        "POST",
        {
            "headers": request_headers,
            "json": {"url": target_url, "waitUntil": "networkidle0"},
        },
    )


def company_filing_browser_render_response_text(
    response: httpx.Response,
    *,
    provider: str,
    target_url: str,
) -> tuple[str, str]:
    provider = (provider or "browserless").strip().lower().replace("-", "_")
    if provider == "flaresolverr":
        payload = response.json()
        solution = payload.get("solution") if isinstance(payload, dict) else {}
        if not isinstance(solution, dict):
            solution = {}
        html = str(solution.get("response") or "")
        final_url = str(solution.get("url") or target_url)
        if not html:
            raise ValueError("FlareSolverr response did not include solution.response")
        return html, final_url
    return response.text, target_url


def company_filing_playwright_render_enabled() -> bool:
    return bool(get_settings().company_filing_playwright_render_enabled)


def company_filing_playwright_available() -> bool:
    try:
        return importlib.util.find_spec("playwright.async_api") is not None
    except (ImportError, ValueError):
        return False


def company_filing_playwright_browser_status(browser_name: str | None = None) -> dict:
    browser = (
        str(browser_name or get_settings().company_filing_playwright_browser or "chromium")
        .strip()
        .lower()
    )
    dependency_available = company_filing_playwright_available()
    status = {
        "browser": browser,
        "dependency_available": dependency_available,
        "browser_available": False,
        "browser_executable_exists": False,
        "executable_path": None,
        "smoke_cli": ".venv/bin/python scripts/company_filing_render_smoke.py --url https://example.com/ --json",
        "fallback_reason": None,
    }
    if not dependency_available:
        status["fallback_reason"] = "missing_dependency:playwright"
        return status
    try:
        playwright_sync_api = importlib.import_module("playwright.sync_api")
        sync_playwright = getattr(playwright_sync_api, "sync_playwright", None)
        if sync_playwright is None:
            status["fallback_reason"] = "missing_dependency:playwright.sync_api"
            return status
        with sync_playwright() as playwright:
            launcher = getattr(playwright, browser, None)
            if launcher is None:
                status["fallback_reason"] = f"unsupported_browser:{browser}"
                return status
            executable_path = getattr(launcher, "executable_path", None)
    except Exception as exc:
        status["fallback_reason"] = f"browser_runtime_check_failed:{exc.__class__.__name__}"
        return status

    if not executable_path:
        status["fallback_reason"] = f"missing_browser_executable_path:{browser}"
        return status
    status["executable_path"] = str(executable_path)
    executable_exists = Path(str(executable_path)).exists()
    status["browser_executable_exists"] = executable_exists
    status["browser_available"] = executable_exists
    if not executable_exists:
        status["fallback_reason"] = (
            f"missing_browser_binary:{browser}; run python -m playwright install {browser}"
        )
    return status


def company_filing_render_fallback_configured() -> bool:
    return company_filing_browser_render_configured() or (
        company_filing_playwright_render_enabled() and company_filing_playwright_available()
    )


def company_filing_structured_api_configured() -> bool:
    settings = get_settings()
    return bool(
        str(settings.company_filing_structured_api_provider or "").strip()
        and str(settings.company_filing_structured_api_url or "").strip()
    )


def company_filing_structured_api_status() -> dict:
    settings = get_settings()
    provider = str(settings.company_filing_structured_api_provider or "").strip().lower()
    endpoint = str(settings.company_filing_structured_api_url or "").strip()
    configured = bool(provider and endpoint)
    parsed = urlparse(endpoint)
    return {
        "configured": configured,
        "provider": provider or None,
        "supported_provider_examples": ["tej", "scrapingbee_dataset", "brightdata_dataset", "custom"],
        "url_configured": bool(endpoint),
        "token_configured": bool(str(settings.company_filing_structured_api_token or "").strip()),
        "timeout_seconds": max(1.0, float(settings.company_filing_structured_api_timeout_seconds)),
        "contract": "GET JSON with documents/data rows: title, text, url, publisher, published_at, document_type",
        "smoke_cli": (
            ".venv/bin/python scripts/structured_company_filing_smoke.py "
            "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
        ),
        "fallback_reason": None
        if configured and parsed.scheme in {"http", "https"} and parsed.hostname
        else "missing_structured_api_provider_or_url"
        if not configured
        else "invalid_structured_api_url",
    }


def company_filing_client_options(
    url: str,
    timeout: int | float = 20,
    follow_redirects: bool = True,
    identity_attempt: int = 0,
) -> dict:
    options: dict = {
        "timeout": timeout,
        "follow_redirects": follow_redirects,
        "headers": company_filing_identity_headers_for_url(url, identity_attempt),
    }
    proxy_url = company_filing_proxy_for_url(url, identity_attempt)
    if proxy_url:
        options["proxy"] = proxy_url
    return options


def company_filing_identity_headers_for_url(url: str, attempt: int = 0) -> dict:
    return {
        "User-Agent": company_filing_user_agent_for_url(url, attempt),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    }


def _company_filing_request_kwargs_with_identity(
    kwargs: dict,
    identity_url: str,
    attempt: int,
) -> dict:
    request_kwargs = dict(kwargs)
    headers = dict(request_kwargs.get("headers") or {})
    identity_headers = company_filing_identity_headers_for_url(identity_url, attempt)
    headers.setdefault("Accept", identity_headers["Accept"])
    headers.setdefault("Accept-Language", identity_headers["Accept-Language"])
    headers["User-Agent"] = identity_headers["User-Agent"]
    request_kwargs["headers"] = headers
    return request_kwargs


def company_filing_request_attempts() -> int:
    return max(0, int(get_settings().company_filing_http_retries)) + 1


async def company_filing_request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    identity_url: str | None = None,
    rotate_identity: bool = True,
    **kwargs,
) -> httpx.Response:
    attempts = company_filing_request_attempts()
    last_error: httpx.HTTPError | None = None
    identity_key = identity_url or url
    for attempt in range(attempts):
        identity_attempt = attempt if rotate_identity else 0
        request_kwargs = _company_filing_request_kwargs_with_identity(
            kwargs,
            identity_key,
            identity_attempt,
        )
        try:
            response = await client.request(method, url, **request_kwargs)
            if (
                response.status_code in COMPANY_FILING_RETRYABLE_HTTP_STATUSES
                and attempt < attempts - 1
            ):
                await company_filing_sleep_before_retry(response, attempt)
                continue
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt >= attempts - 1:
                raise
            response = getattr(exc, "response", None)
            if (
                isinstance(response, httpx.Response)
                and response.status_code not in COMPANY_FILING_RETRYABLE_HTTP_STATUSES
            ):
                raise
            await company_filing_sleep_before_retry(
                response if isinstance(response, httpx.Response) else None,
                attempt,
            )
    if last_error:
        raise last_error
    raise httpx.HTTPError("company filing request failed without a response")


async def company_filing_fetch_response_with_retries(
    method: str,
    url: str,
    *,
    timeout: int | float = 20,
    follow_redirects: bool = True,
    identity_url: str | None = None,
    **kwargs,
) -> httpx.Response:
    attempts = company_filing_request_attempts()
    last_error: httpx.HTTPError | None = None
    identity_key = identity_url or url
    for attempt in range(attempts):
        request_kwargs = _company_filing_request_kwargs_with_identity(
            kwargs,
            identity_key,
            attempt,
        )
        try:
            async with httpx.AsyncClient(
                **company_filing_client_options(
                    url,
                    timeout=timeout,
                    follow_redirects=follow_redirects,
                    identity_attempt=attempt,
                )
            ) as client:
                response = await client.request(method, url, **request_kwargs)
            if (
                response.status_code in COMPANY_FILING_RETRYABLE_HTTP_STATUSES
                and attempt < attempts - 1
            ):
                await company_filing_sleep_before_retry(response, attempt)
                continue
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt >= attempts - 1:
                raise
            response = getattr(exc, "response", None)
            if (
                isinstance(response, httpx.Response)
                and response.status_code not in COMPANY_FILING_RETRYABLE_HTTP_STATUSES
            ):
                raise
            await company_filing_sleep_before_retry(
                response if isinstance(response, httpx.Response) else None,
                attempt,
            )
    if last_error:
        raise last_error
    raise httpx.HTTPError("company filing request failed without a response")


async def company_filing_sleep_before_retry(response: httpx.Response | None, attempt: int) -> None:
    await asyncio.sleep(company_filing_retry_delay_seconds(response, attempt))


def company_filing_retry_delay_seconds(response: httpx.Response | None, attempt: int) -> float:
    settings = get_settings()
    max_delay = max(0.0, float(settings.company_filing_max_retry_delay_seconds))
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(max_delay, max(0.0, float(retry_after)))
            except ValueError:
                pass
    base_delay = max(0.0, float(settings.company_filing_base_retry_delay_seconds))
    return min(max_delay, base_delay * (2**attempt))


def company_filing_error(source: str, error: Exception | str, stage: str = "") -> dict:
    category = categorize_company_filing_error(error)
    if isinstance(error, Exception):
        message = str(error) or error.__class__.__name__
    else:
        message = str(error)
    payload = {
        "source": source,
        "error": message,
        "category": category,
        "retryable": is_retryable_company_filing_error_category(category),
    }
    if stage:
        payload["stage"] = stage
    return payload


def categorize_company_filing_error(error: Exception | str) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        return _company_filing_http_status_category(error.response.status_code)
    if isinstance(error, httpx.TimeoutException) or isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, httpx.TransportError):
        return "network_error"

    message = str(error or "")
    lowered = message.lower()
    status_match = re.search(r"\b(403|404|429|500|502|503|504)\b", lowered)
    if status_match and ("http" in lowered or "error" in lowered or "client" in lowered or "server" in lowered):
        return _company_filing_http_status_category(int(status_match.group(1)))
    if "timeout" in lowered or "timed out" in lowered or "逾時" in message:
        return "timeout"
    if "rate limit" in lowered or "too many requests" in lowered:
        return "rate_limited"
    if "network" in lowered or "connection error" in lowered or "connection reset" in lowered:
        return "network_error"
    if "ocr" in lowered or "extractable text" in lowered or "掃描" in message:
        return "pdf_no_text"
    if "render fallback failed" in lowered:
        return "browser_render_failed"
    if "browser render url is not configured" in lowered or "playwright render dependency is not installed" in lowered:
        return "browser_render_not_configured"
    if "company website not found" in lowered:
        return "website_not_found"
    if "mops did not return a pdf download link" in lowered:
        return "missing_pdf_link"
    if "content is too short" in lowered:
        return "too_short"
    if "content is too large" in lowered:
        return "too_large"
    if "blocked, login, or placeholder" in lowered or looks_like_blocked_or_placeholder_filing_page(lowered):
        return "blocked_or_placeholder"
    if "does not mention the target company" in lowered:
        return "company_mismatch"
    if "does not match the selected document type" in lowered:
        return "document_type_mismatch"
    if "pdf 匯入需要安裝" in message or "尚未安裝 pdfplumber" in message or "尚未安裝 unstructured" in message:
        return "missing_pdf_dependency"
    if "使用加密格式" in message:
        return "encrypted_pdf"
    if PDF_IMPORT_PARSE_ERROR_MESSAGE in message:
        return "pdf_parse_error"
    if PDF_IMPORT_NO_TEXT_MESSAGE in message:
        return "pdf_no_text"
    if "unsupported company filing pdf parser" in lowered:
        return "unsupported_pdf_parser"
    if "company filing url cannot target" in lowered or "company filing url must" in lowered:
        return "unsafe_url"
    return "unknown"


def _company_filing_http_status_category(status_code: int) -> str:
    if status_code == 403:
        return "blocked_or_forbidden"
    if status_code == 429:
        return "rate_limited"
    if status_code == 404:
        return "http_not_found"
    if status_code in {500, 502, 503, 504}:
        return "upstream_retryable"
    return "http_error"


def is_retryable_company_filing_error_category(category: str) -> bool:
    return category in RETRYABLE_COMPANY_FILING_ERROR_CATEGORIES


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
        headers = {"Accept": "application/json"}
        token = str(settings.company_filing_structured_api_token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        params = {
            "ticker": ticker,
            "company_name": company_name,
            "limit": max(1, int(limit)),
        }
        if document_types:
            params["document_types"] = ",".join(document_types)
        try:
            response = await company_filing_fetch_response_with_retries(
                "GET",
                endpoint,
                timeout=max(1.0, float(settings.company_filing_structured_api_timeout_seconds)),
                follow_redirects=True,
                headers=headers,
                params=params,
            )
            rows = structured_api_document_rows(response.json())
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
        title = str(row.get("title") or row.get("name") or "").strip()
        text = str(row.get("text") or row.get("content") or row.get("summary") or "").strip()
        url = str(row.get("url") or row.get("source_url") or "").strip() or None
        document_type = str(row.get("document_type") or infer_document_type(f"{title}\n{text}\n{url or ''}"))
        if document_types and document_type not in set(document_types):
            return None
        if not title or not text:
            return None
        publisher = str(row.get("publisher") or provider or "structured company filing API")
        source = Source(
            title=title,
            url=url,
            publisher=publisher,
            published_at=parse_structured_api_date(row.get("published_at") or row.get("date")),
            fetched_at=utc_now_naive(),
        )
        news_document = NewsDocument(
            id=sha1(f"structured-api:{ticker}:{document_type}:{url or title}".encode("utf-8")).hexdigest(),
            title=title,
            text=text,
            source=source,
        )
        if not is_document_text_relevant(news_document, ticker, company_name, document_types):
            return None
        return self.from_news_document(news_document, ticker, company_name, document_type=document_type)

    async def fetch_web_search_documents(
        self,
        ticker: str,
        company_name: str = "",
        limit_per_query: int = 5,
        document_types: list[str] | tuple[str, ...] | None = None,
    ) -> tuple[list[CompanyFilingDocument], list[dict]]:
        documents: list[CompanyFilingDocument] = []
        errors = []
        seen_urls: set[str] = set()
        for query_text in self.official_search_queries(ticker, company_name, document_types=document_types):
            try:
                results = await self._duckduckgo_search(query_text, limit_per_query)
            except Exception as exc:
                errors.append(company_filing_error(query_text, exc, stage="web_search_query"))
                continue
            for result in results:
                url = result.get("url") or ""
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                preview = NewsDocument(
                    id=sha1(url.encode("utf-8")).hexdigest(),
                    title=result.get("title") or url,
                    text=result.get("snippet") or "",
                    source=Source(title=result.get("title") or url, url=url, publisher=result.get("publisher")),
                )
                if not is_relevant_company_filing_result(preview, ticker, company_name):
                    continue
                try:
                    document_type = infer_document_type(f"{preview.title}\n{preview.text}\n{url}")
                    document = await self.fetch_url_document(
                        url,
                        ticker=ticker,
                        company_name=company_name,
                        document_type=document_type,
                        publisher=preview.source.publisher or "web company filing discovery",
                    )
                except Exception as exc:
                    errors.append(company_filing_error(url, exc, stage="web_search_fetch"))
                    continue
                documents.append(document)
        return documents, errors

    async def fetch_mops_annual_report_documents(
        self,
        ticker: str,
        company_name: str = "",
        years: int = 3,
    ) -> tuple[list[CompanyFilingDocument], list[dict]]:
        documents: list[CompanyFilingDocument] = []
        errors = []
        current_roc_year = date.today().year - 1911
        for roc_year in range(current_roc_year, current_roc_year - years, -1):
            query_url = (
                "https://doc.twse.com.tw/server-java/t57sb01"
                f"?step=1&colorchg=1&co_id={ticker}&year={roc_year}&mtype=F&isnew=false"
            )
            try:
                html = await self._fetch_url_text(query_url, encoding="big5")
                rows = parse_mops_annual_report_rows(html)
            except Exception as exc:
                errors.append(company_filing_error(query_url, exc, stage="mops_query"))
                continue
            for row in rows:
                filename = row.get("filename") or ""
                if not filename:
                    continue
                try:
                    pdf_url, content = await self._download_mops_pdf(ticker, filename, "F")
                    text = extract_pdf_text(content)
                    title = row.get("description") or filename
                    published_at = parse_mops_roc_datetime(row.get("uploaded_at") or "")
                    document = self.from_manual_text(
                        ticker=ticker,
                        company_name=company_name,
                        document_type="annual_report",
                        title=title,
                        text=text,
                        publisher="公開資訊觀測站 MOPS",
                        published_at=published_at,
                        url=pdf_url,
                    )
                    validate_fetched_company_filing_document(document, ticker, company_name, "annual_report")
                except Exception as exc:
                    errors.append(company_filing_error(filename, exc, stage="mops_pdf"))
                    continue
                documents.append(document)
            if documents:
                break
        return documents, errors

    @staticmethod
    async def _download_mops_pdf(ticker: str, filename: str, kind: str) -> tuple[str, bytes]:
        entry_url = "https://doc.twse.com.tw/server-java/t57sb01"
        async with httpx.AsyncClient(**company_filing_client_options(entry_url, timeout=30, follow_redirects=True)) as client:
            response = await company_filing_request_with_retries(
                client,
                "POST",
                entry_url,
                data={
                    "step": "9",
                    "kind": kind,
                    "co_id": ticker,
                    "filename": filename,
                    "colorchg": "1",
                },
            )
            response.encoding = "big5"
            soup = BeautifulSoup(response.text, "html.parser")
            link = soup.find("a", href=True)
            if not link:
                raise ValueError("MOPS did not return a PDF download link")
            pdf_url = urljoin("https://doc.twse.com.tw", link["href"])
            pdf_response = await company_filing_request_with_retries(client, "GET", pdf_url)
        if len(pdf_response.content) > MAX_FETCHED_DOCUMENT_BYTES:
            raise ValueError("company filing content is too large to import")
        return pdf_url, pdf_response.content

    async def fetch_official_website_documents(
        self,
        ticker: str,
        company_name: str = "",
        limit: int = 12,
        document_types: list[str] | tuple[str, ...] | None = None,
    ) -> tuple[list[CompanyFilingDocument], list[dict]]:
        profile = await self.twse_company_profile(ticker)
        profile_name = (profile or {}).get("公司簡稱") or (profile or {}).get("公司名稱") or ""
        website = normalize_company_website((profile or {}).get("網址") or "")
        company_name = company_name or profile_name
        if not website:
            return [], [
                company_filing_error(
                    "TWSE company profile",
                    "company website not found",
                    stage="official_profile",
                )
            ]

        urls_to_scan = official_website_seed_urls(website)
        candidate_links: list[dict] = []
        errors = []
        for page_url in urls_to_scan:
            try:
                page_html, final_page_url = await self._fetch_url_text_with_final_url(
                    page_url,
                    timeout=OFFICIAL_WEBSITE_FETCH_TIMEOUT_SECONDS,
                )
                soup = BeautifulSoup(page_html, "html.parser")
                page = NewsDocument(
                    id=sha1(final_page_url.encode("utf-8")).hexdigest(),
                    title=NewsFetcher._title(soup) or final_page_url,
                    text=NewsFetcher._article_text(soup),
                    source=Source(
                        title=NewsFetcher._title(soup) or final_page_url,
                        url=final_page_url,
                        publisher="TWSE company profile website",
                        published_at=NewsFetcher._published_date(soup),
                        fetched_at=utc_now_naive(),
                    ),
                )
            except Exception as exc:
                errors.append(company_filing_error(page_url, exc, stage="official_seed_page"))
                continue
            candidate_links.extend(extract_company_filing_links(page_html, final_page_url))
            if is_document_text_relevant(page, ticker, company_name, document_types):
                candidate_links.append(
                    {
                        "url": page.source.url or page_url,
                        "title": page.title,
                        "publisher": page.source.publisher,
                    }
                )
            if len(candidate_links) >= limit:
                break

        documents: list[CompanyFilingDocument] = []
        seen_urls: set[str] = set()
        for link in candidate_links:
            url = link.get("url") or ""
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            preview_text = f"{link.get('title') or ''}\n{url}"
            document_type = infer_document_type(preview_text)
            if document_types and document_type not in set(document_types):
                continue
            try:
                document = await self.fetch_url_document(
                    url,
                    ticker=ticker,
                    company_name=company_name,
                    document_type=document_type,
                    publisher=link.get("publisher") or "official company website",
                )
            except Exception as exc:
                errors.append(company_filing_error(url, exc, stage="official_document_fetch"))
                continue
            documents.append(document)
            if len(documents) >= limit:
                break
        return documents, errors

    @staticmethod
    async def _fetch_url_text(
        url: str,
        encoding: str | None = None,
        timeout: int = 20,
    ) -> str:
        text, _ = await CompanyFilingFetcher._fetch_url_text_with_final_url(
            url,
            encoding=encoding,
            timeout=timeout,
        )
        return text

    @staticmethod
    async def _fetch_url_text_with_final_url(
        url: str,
        encoding: str | None = None,
        timeout: int = 20,
        max_html_redirects: int = 2,
    ) -> tuple[str, str]:
        current_url = url
        visited = set()
        for _ in range(max_html_redirects + 1):
            response = await company_filing_fetch_response_with_retries(
                "GET",
                current_url,
                timeout=timeout,
                follow_redirects=True,
            )
            content_length = int(response.headers.get("content-length") or 0)
            if content_length > MAX_FETCHED_DOCUMENT_BYTES or len(response.content) > MAX_FETCHED_DOCUMENT_BYTES:
                raise ValueError("company filing content is too large to import")
            if encoding:
                response.encoding = encoding
            final_url = str(response.url)
            text = response.text
            redirect_url = extract_html_redirect_url(text, final_url)
            if not redirect_url or redirect_url in visited:
                return text, final_url
            visited.add(final_url)
            current_url = redirect_url
        return text, final_url

    @classmethod
    async def twse_company_profile(cls, ticker: str) -> dict:
        if cls._twse_profile_cache is None:
            url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
            response = await company_filing_fetch_response_with_retries(
                "GET",
                url,
                timeout=20,
                follow_redirects=True,
            )
            cls._twse_profile_cache = response.json()
        twse_row = next((row for row in cls._twse_profile_cache if str(row.get("公司代號") or "") == ticker), None)
        if twse_row:
            return twse_row
        if cls._tpex_profile_cache is None:
            url = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
            response = await company_filing_fetch_response_with_retries(
                "GET",
                url,
                timeout=20,
                follow_redirects=True,
            )
            cls._tpex_profile_cache = response.json()
        tpex_row = next(
            (
                row
                for row in cls._tpex_profile_cache
                if str(row.get("SecuritiesCompanyCode") or "") == ticker
            ),
            None,
        )
        return normalize_tpex_company_profile(tpex_row) if tpex_row else {}

    @staticmethod
    async def _duckduckgo_search(query_text: str, limit: int = 5) -> list[dict]:
        url = f"https://duckduckgo.com/html/?q={quote_plus(query_text)}"
        response = await company_filing_fetch_response_with_retries(
            "GET",
            url,
            timeout=20,
            follow_redirects=True,
        )
        soup = BeautifulSoup(response.text, "html.parser")
        results = []
        for result in soup.select(".result"):
            link = result.select_one("a.result__a")
            if not link:
                continue
            href = normalize_search_result_url(link.get("href") or "")
            if not href:
                continue
            snippet_node = result.select_one(".result__snippet")
            parsed = urlparse(href)
            results.append(
                {
                    "title": link.get_text(" ", strip=True),
                    "url": href,
                    "snippet": snippet_node.get_text(" ", strip=True) if snippet_node else "",
                    "publisher": parsed.netloc,
                }
            )
            if len(results) >= limit:
                break
        return results


def filing_source_tier(document: CompanyFilingDocument | NewsDocument) -> str:
    url = (document.source.url or "").lower()
    publisher = (document.source.publisher or "").lower()
    if any(domain in url or domain in publisher for domain in OFFICIAL_SOURCE_DOMAINS):
        return "official_disclosure"
    if any(hint in url or hint in publisher for hint in IR_SOURCE_HINTS):
        return "company_ir"
    return "third_party"


def validate_public_document_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("company filing URL must use http or https")
    if not parsed.hostname:
        raise ValueError("company filing URL must include a hostname")
    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "127.0.0.1", "::1"} or hostname.endswith(".local"):
        raise ValueError("company filing URL cannot target localhost or local domains")
    try:
        address = ip_address(hostname)
    except ValueError:
        return
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise ValueError("company filing URL cannot target private or reserved IP addresses")


def is_pdf_response(url: str, content_type: str) -> bool:
    return "application/pdf" in content_type or urlparse(url).path.lower().endswith(".pdf")


def parse_mops_annual_report_rows(html: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    rows = []
    for table_row in soup.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in table_row.find_all("td")]
        if len(cells) < 10:
            continue
        description = cells[5]
        filename = cells[7]
        if "股東會年報" not in description or "英文版" in description or "前十大股東" in description:
            continue
        rows.append(
            {
                "ticker": cells[0],
                "data_year": cells[1],
                "description": description,
                "filename": filename,
                "uploaded_at": cells[9],
            }
        )
    return rows


def parse_mops_roc_datetime(value: str) -> date | None:
    value = (value or "").strip()
    if not value or "/" not in value:
        return None
    date_part = value.split()[0]
    parts = date_part.split("/")
    if len(parts) != 3:
        return None
    try:
        year = int(parts[0]) + 1911
        return date(year, int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def normalize_search_result_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(target)
    if url.startswith("//"):
        return "https:" + url
    return url


def normalize_company_website(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


def normalize_tpex_company_profile(row: dict | None) -> dict:
    if not row:
        return {}
    return {
        "公司代號": row.get("SecuritiesCompanyCode") or "",
        "公司名稱": row.get("CompanyName") or "",
        "公司簡稱": row.get("CompanyAbbreviation") or "",
        "網址": row.get("WebAddress") or "",
        "電子郵件信箱": row.get("EmailAddress") or "",
    }


def extract_html_redirect_url(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    meta_refresh = soup.find("meta", attrs={"http-equiv": lambda value: value and value.lower() == "refresh"})
    if meta_refresh:
        content = meta_refresh.get("content") or ""
        match = re.search(r"url\s*=\s*['\"]?([^;'\"\s]+)", content, flags=re.IGNORECASE)
        if match:
            return urljoin(base_url, match.group(1))
    match = re.search(
        r"(?:window\.)?location(?:\.href)?\s*=\s*['\"]([^'\"]+)['\"]",
        html or "",
        flags=re.IGNORECASE,
    )
    if match:
        return urljoin(base_url, match.group(1))
    return ""


def extract_company_filing_html_text(soup: BeautifulSoup) -> str:
    article_text = NewsFetcher._article_text(soup).strip()
    if not get_settings().company_filing_html_extract_tables:
        return article_text
    table_blocks = _format_html_tables(soup)
    if not table_blocks:
        return article_text
    parts = [article_text] if article_text else []
    parts.extend(table_blocks)
    return "\n\n".join(parts)


def official_website_seed_urls(website: str) -> list[str]:
    parsed = urlparse(website)
    root = f"{parsed.scheme}://{parsed.netloc}"
    paths = [
        "",
        "/investor",
        "/investors",
        "/ir",
        "/investor-relations",
        "/investor/financial-reports",
        "/investor/financials",
        "/investor/shareholder-services",
        "/investor-service",
        "/annual-reports",
        "/annual-report",
        "/zh-TW/investor",
        "/zh-TW/investor-relations",
        "/zh-TW/ir",
        "/zh-Hant/investor",
        "/zh-Hant/investor-relations",
        "/chinese/investor",
        "/chinese/ir",
        "/chinese/annual-reports",
    ]
    urls = [website, *[root + path for path in paths if root + path != website]]
    return list(dict.fromkeys(urls))


def extract_company_filing_links(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    links = []
    for anchor in soup.find_all("a"):
        href = anchor.get("href") or ""
        text = anchor.get_text(" ", strip=True)
        target = urljoin(base_url, href)
        haystack = f"{text}\n{target}".lower()
        if not any(term.lower() in haystack for term in DISCLOSURE_TERMS):
            continue
        if not target.startswith(("http://", "https://")):
            continue
        links.append({"url": target, "title": text or target, "publisher": urlparse(target).netloc})
    return links


def is_document_text_relevant(
    document: NewsDocument,
    ticker: str,
    company_name: str,
    document_types: list[str] | tuple[str, ...] | None,
) -> bool:
    text = f"{document.title}\n{document.text}\n{document.source.url or ''}"
    if document_types and infer_document_type(text) not in set(document_types):
        return False
    return is_relevant_company_filing_result(document, ticker, company_name)


def structured_api_document_rows(payload: object) -> list[dict]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("documents") or payload.get("data") or payload.get("results") or []
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


def parse_structured_api_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def pdf_title_from_url(url: str) -> str:
    name = urlparse(url).path.rsplit("/", 1)[-1]
    return name or url


def extract_pdf_text(content: bytes) -> str:
    parser = get_settings().company_filing_pdf_parser.strip().lower() or "auto"
    try:
        if parser == "auto":
            text = _extract_pdf_text_auto(content)
            return _maybe_augment_pdf_text_with_visual_rag(content, text)
        if parser == "pdfplumber":
            text = _with_pdf_parser_provenance(
                _extract_pdf_text_with_pdfplumber(content),
                parser="pdfplumber",
            )
            return _maybe_augment_pdf_text_with_visual_rag(content, text)
        if parser == "unstructured":
            text = _with_pdf_parser_provenance(
                _extract_pdf_text_with_unstructured(content),
                parser="unstructured",
            )
            return _maybe_augment_pdf_text_with_visual_rag(content, text)
        if parser == "pypdf":
            text = _with_pdf_parser_provenance(
                _extract_pdf_text_with_pypdf(content),
                parser="pypdf",
            )
            return _maybe_augment_pdf_text_with_visual_rag(content, text)
    except ImportError as exc:
        raise ValueError(str(exc)) from exc
    except ValueError as exc:
        visual_text = _extract_pdf_text_with_visual_rag_fallback(content, exc)
        if visual_text:
            return visual_text
        raise
    raise ValueError(f"unsupported company filing PDF parser: {parser}")


def _extract_pdf_text_auto(content: bytes) -> str:
    last_error: ValueError | None = None
    for parser_name, extractor in (
        ("pdfplumber", _extract_pdf_text_with_pdfplumber),
        ("unstructured", _extract_pdf_text_with_unstructured),
        ("pypdf", _extract_pdf_text_with_pypdf),
    ):
        try:
            return _with_pdf_parser_provenance(
                extractor(content),
                parser=parser_name,
                auto=True,
            )
        except ImportError:
            continue
        except ValueError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise ValueError(PDF_IMPORT_MISSING_PYPDF_MESSAGE)


def _extract_pdf_text_with_visual_rag_fallback(content: bytes, error: ValueError) -> str:
    if not _should_try_visual_rag_pdf_fallback(error):
        return ""
    from app.services.visual_rag import extract_visual_pdf_text

    try:
        return extract_visual_pdf_text(content, reason=str(error))
    except Exception:
        return ""


def _maybe_augment_pdf_text_with_visual_rag(content: bytes, text: str) -> str:
    from app.services.visual_rag import maybe_augment_pdf_text_with_visual_rag

    return maybe_augment_pdf_text_with_visual_rag(content, text)


def _should_try_visual_rag_pdf_fallback(error: ValueError) -> bool:
    from app.services.visual_rag import visual_rag_fallback_enabled

    if not visual_rag_fallback_enabled():
        return False
    message = str(error)
    return (
        PDF_IMPORT_NO_TEXT_MESSAGE in message
        or PDF_IMPORT_PARSE_ERROR_MESSAGE in message
        or "沒有可抽取文字" in message
        or "掃描" in message
    )


def _with_pdf_parser_provenance(text: str, parser: str, auto: bool = False) -> str:
    extract_tables = get_settings().company_filing_pdf_extract_tables
    mode = "auto" if auto else "configured"
    marker = (
        f"{PDF_PARSER_PROVENANCE_PREFIX} parser={parser}; mode={mode}; "
        f"extract_tables={str(bool(extract_tables)).lower()}"
    )
    if text.startswith(PDF_PARSER_PROVENANCE_PREFIX):
        return text
    return f"{marker}\n{text}"


def _extract_pdf_text_with_pypdf(content: bytes) -> str:
    try:
        from pypdf import PdfReader
        from pypdf.errors import DependencyError
    except ImportError as exc:
        raise ValueError(PDF_IMPORT_MISSING_PYPDF_MESSAGE) from exc
    try:
        reader = PdfReader(BytesIO(content))
        if getattr(reader, "is_encrypted", False):
            reader.decrypt("")
        pages = [page.extract_text() or "" for page in reader.pages]
    except DependencyError as exc:
        raise ValueError("PDF 公司文件使用加密格式，請安裝 cryptography 後再重試解析。") from exc
    except Exception as exc:
        raise ValueError(PDF_IMPORT_PARSE_ERROR_MESSAGE) from exc
    text = "\n".join(page.strip() for page in pages if page.strip())
    if not text.strip():
        raise ValueError(PDF_IMPORT_NO_TEXT_MESSAGE)
    return text


def _extract_pdf_text_with_pdfplumber(content: bytes) -> str:
    try:
        pdfplumber = importlib.import_module("pdfplumber")
    except ImportError as exc:
        raise ImportError(PDF_IMPORT_MISSING_PDFPLUMBER_MESSAGE) from exc

    try:
        parts: list[str] = []
        table_count = 0
        table_limit_reached = False
        with pdfplumber.open(BytesIO(content)) as pdf:
            for page_index, page in enumerate(pdf.pages, start=1):
                page_text = (page.extract_text() or "").strip()
                if page_text:
                    parts.append(page_text)
                if get_settings().company_filing_pdf_extract_tables:
                    for table_index, table in enumerate(page.extract_tables() or [], start=1):
                        if table_count >= MAX_PDF_TABLES_PER_DOCUMENT:
                            table_limit_reached = True
                            continue
                        table_text = _format_pdf_table(table, page_index, table_index)
                        if table_text:
                            table_count += 1
                            parts.append(table_text)
        if table_limit_reached:
            parts.append(
                f"[PDF 表格抽取限制] 表格超過 {MAX_PDF_TABLES_PER_DOCUMENT} 個，"
                "僅保留前段可檢索表格文字。"
            )
    except Exception as exc:
        raise ValueError(PDF_IMPORT_PARSE_ERROR_MESSAGE) from exc

    return _validated_pdf_text("\n\n".join(parts))


def _extract_pdf_text_with_unstructured(content: bytes) -> str:
    try:
        partition_pdf = importlib.import_module("unstructured.partition.pdf").partition_pdf
    except ImportError as exc:
        raise ImportError(PDF_IMPORT_MISSING_UNSTRUCTURED_MESSAGE) from exc

    extract_tables = get_settings().company_filing_pdf_extract_tables
    try:
        elements = partition_pdf(file=BytesIO(content), infer_table_structure=extract_tables)
    except Exception as exc:
        raise ValueError(PDF_IMPORT_PARSE_ERROR_MESSAGE) from exc

    parts = []
    table_count = 0
    table_limit_reached = False
    for element in elements:
        text = str(element).strip()
        category = str(getattr(element, "category", "") or element.__class__.__name__).lower()
        metadata = getattr(element, "metadata", None)
        table_html = str(getattr(metadata, "text_as_html", "") or "")
        if "table" in category:
            if extract_tables:
                if table_count >= MAX_PDF_TABLES_PER_DOCUMENT:
                    table_limit_reached = True
                    continue
                table_text = _format_unstructured_pdf_table(text, table_html, metadata, table_count + 1)
                if table_text:
                    table_count += 1
                    parts.append(table_text)
                    continue
            elif text:
                parts.append(text)
                continue
        if text:
            parts.append(text)
    if table_limit_reached:
        parts.append(
            f"[PDF 表格抽取限制] 表格超過 {MAX_PDF_TABLES_PER_DOCUMENT} 個，"
            "僅保留前段可檢索表格文字。"
        )
    return _validated_pdf_text("\n\n".join(parts))


def _validated_pdf_text(text: str) -> str:
    text = text.strip()
    if not text:
        raise ValueError(PDF_IMPORT_NO_TEXT_MESSAGE)
    return text


def _format_pdf_table(table: list[list[object]], page_index: int, table_index: int) -> str:
    rows = []
    for row in table or []:
        cells = [_clean_pdf_table_cell(cell) for cell in (row or [])]
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""
    raw_row_count = len(rows)
    raw_column_count = max(len(row) for row in rows)
    max_columns = min(raw_column_count, MAX_PDF_TABLE_COLUMNS)
    truncated_rows = rows[:MAX_PDF_TABLE_ROWS]
    normalized = [
        (row[:max_columns] + [""] * (max_columns - len(row[:max_columns])))
        for row in truncated_rows
    ]
    lines = [f"[PDF 表格抽取 p.{page_index} #{table_index}]"]
    lines.append(f"表格尺寸：{raw_row_count} 列 x {raw_column_count} 欄")
    if raw_row_count > MAX_PDF_TABLE_ROWS or raw_column_count > MAX_PDF_TABLE_COLUMNS:
        lines.append(
            f"表格已截斷：保留前 {min(raw_row_count, MAX_PDF_TABLE_ROWS)} 列、"
            f"前 {min(raw_column_count, MAX_PDF_TABLE_COLUMNS)} 欄。"
        )
    lines.extend(" | ".join(row).strip() for row in normalized)
    return "\n".join(line for line in lines if line.strip())


def _format_unstructured_pdf_table(
    text: str,
    table_html: str,
    metadata: object,
    table_index: int,
) -> str:
    table_text = _html_table_to_text(table_html) if table_html else text.strip()
    if not table_text:
        return ""
    page_number = getattr(metadata, "page_number", None)
    page_label = f" p.{page_number}" if page_number else ""
    return f"[PDF 表格抽取{page_label} #{table_index}]\n{table_text}"


def _html_table_to_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    rows = []
    for table_row in soup.find_all("tr"):
        cells = [
            cell.get_text(" ", strip=True)
            for cell in table_row.find_all(["th", "td"])
        ]
        if any(cells):
            rows.append(" | ".join(cells))
    if rows:
        return "\n".join(rows)
    return soup.get_text(" ", strip=True)


def _format_html_tables(soup: BeautifulSoup) -> list[str]:
    blocks = []
    limit_reached = False
    for table in soup.find_all("table"):
        if len(blocks) >= MAX_HTML_TABLES_PER_DOCUMENT:
            limit_reached = True
            break
        block = _format_html_table(table, len(blocks) + 1)
        if block:
            blocks.append(block)
    if limit_reached:
        blocks.append(
            f"[HTML 表格抽取限制] 表格超過 {MAX_HTML_TABLES_PER_DOCUMENT} 個，"
            "僅保留前段可檢索表格文字。"
        )
    return blocks


def _format_html_table(table: object, table_index: int) -> str:
    rows = []
    for table_row in table.find_all("tr"):
        cells = [
            _clean_pdf_table_cell(cell.get_text(" ", strip=True))
            for cell in table_row.find_all(["th", "td"])
        ]
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""
    raw_row_count = len(rows)
    raw_column_count = max(len(row) for row in rows)
    max_columns = min(raw_column_count, MAX_PDF_TABLE_COLUMNS)
    truncated_rows = rows[:MAX_PDF_TABLE_ROWS]
    normalized = [
        row[:max_columns] + [""] * (max_columns - len(row[:max_columns]))
        for row in truncated_rows
    ]
    lines = [f"[HTML 表格抽取 #{table_index}]"]
    lines.append(f"表格尺寸：{raw_row_count} 列 x {raw_column_count} 欄")
    if raw_row_count > MAX_PDF_TABLE_ROWS or raw_column_count > MAX_PDF_TABLE_COLUMNS:
        lines.append(
            f"表格已截斷：保留前 {min(raw_row_count, MAX_PDF_TABLE_ROWS)} 列、"
            f"前 {min(raw_column_count, MAX_PDF_TABLE_COLUMNS)} 欄。"
        )
    lines.extend(" | ".join(row).strip() for row in normalized)
    return "\n".join(line for line in lines if line.strip())


def _clean_pdf_table_cell(value: object) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").replace("\n", " ")).strip()
    if len(cleaned) > MAX_PDF_TABLE_CELL_CHARS:
        return cleaned[: MAX_PDF_TABLE_CELL_CHARS - 3] + "..."
    return cleaned


def validate_fetched_company_filing_document(
    document: NewsDocument,
    ticker: str,
    company_name: str = "",
    document_type: str = "company_disclosure",
) -> None:
    text = f"{document.title}\n{document.text}".strip()
    if len(text) < MIN_FETCHED_DOCUMENT_CHARS:
        raise ValueError("company filing content is too short to audit")
    if len(text) > MAX_FETCHED_DOCUMENT_CHARS:
        raise ValueError("company filing content is too large to import")

    lowered = text.lower()
    if looks_like_blocked_or_placeholder_filing_page(lowered):
        raise ValueError("company filing content looks like a blocked, login, or placeholder page")
    company_terms = [ticker.lower()]
    if company_name:
        company_terms.append(company_name.lower())
    if not any(term and term in lowered for term in company_terms):
        raise ValueError("company filing content does not mention the target company")

    if document_type != "company_disclosure":
        keywords = DOCUMENT_TYPE_KEYWORDS.get(document_type, ())
        if keywords and not any(keyword.lower() in lowered for keyword in keywords):
            raise ValueError("company filing content does not match the selected document type")


def looks_like_blocked_or_placeholder_filing_page(text: str) -> bool:
    lowered = (text or "").lower()
    return any(pattern in lowered for pattern in BLOCKED_OR_PLACEHOLDER_PAGE_PATTERNS)


def filing_quality_score(document: CompanyFilingDocument | NewsDocument, ticker: str = "", company_name: str = "") -> int:
    text = f"{document.title}\n{getattr(document, 'text', '')}".lower()
    url = (document.source.url or "").lower()
    score = 0
    tier = filing_source_tier(document)
    if tier == "official_disclosure":
        score += 55
    elif tier == "company_ir":
        score += 45
    else:
        score += 15
    if ticker and ticker.lower() in text:
        score += 10
    if company_name and company_name.lower() in text:
        score += 10
    if any(term.lower() in text for term in DISCLOSURE_TERMS):
        score += 15
    if ".pdf" in url or "filetype:pdf" in url:
        score += 10
    if document.source.published_at:
        score += 5
    return min(score, 100)


def is_high_quality_company_filing(document: CompanyFilingDocument | NewsDocument, ticker: str = "", company_name: str = "") -> bool:
    return filing_quality_score(document, ticker, company_name) >= HIGH_QUALITY_FILING_SCORE


def infer_document_type(text: str) -> str:
    lowered = text.lower()
    for document_type, keywords in DOCUMENT_TYPE_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            return document_type
    return "company_disclosure"


def is_relevant_company_filing_result(document: NewsDocument, ticker: str, company_name: str = "") -> bool:
    text = f"{document.title}\n{document.text}".lower()
    company_terms = [ticker.lower()]
    if company_name:
        company_terms.append(company_name.lower())
    has_company = any(term and term in text for term in company_terms)
    has_disclosure = any(term.lower() in text for term in DISCLOSURE_TERMS)
    if not has_company or not has_disclosure:
        return False
    return filing_quality_score(document, ticker, company_name) >= 40


def document_query_templates(document_types: list[str] | tuple[str, ...] | None = None) -> tuple[str, ...]:
    if not document_types:
        return DOCUMENT_QUERY_TEMPLATES
    templates = []
    wanted = set(document_types)
    if "annual_report" in wanted:
        templates.extend(
            [
                "{ticker} {name} 年報 filetype:pdf",
                "{ticker} {name} annual report filetype:pdf",
                "{ticker} {name} 公開資訊觀測站 年報 site:mops.twse.com.tw",
                "{ticker} {name} 股東會年報 site:doc.twse.com.tw",
                "{ticker} {name} IR 年報",
            ]
        )
    if "investor_presentation" in wanted:
        templates.extend(
            [
                "{ticker} {name} 法人說明會 filetype:pdf",
                "{ticker} {name} investor presentation filetype:pdf",
                "{ticker} {name} 法人說明會 site:mops.twse.com.tw",
                "{ticker} {name} 法說會 簡報 site:doc.twse.com.tw",
                "{ticker} {name} IR presentation",
            ]
        )
    if "prospectus" in wanted:
        templates.extend(
            [
                "{ticker} {name} 公開說明書 filetype:pdf",
                "{ticker} {name} prospectus filetype:pdf",
                "{ticker} {name} 公開說明書 site:mops.twse.com.tw",
            ]
        )
    if "material_information" in wanted:
        templates.extend(
            [
                "{ticker} {name} 重大訊息 site:mops.twse.com.tw",
                "{ticker} {name} material information",
            ]
        )
    return tuple(dict.fromkeys(templates)) or DOCUMENT_QUERY_TEMPLATES
