from __future__ import annotations

from collections.abc import Awaitable, Callable
from hashlib import sha1
import importlib
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.core.config import get_settings
from app.core.time import utc_now_naive
from app.data_sources.company_filing_discovery import validate_public_document_url
from app.data_sources.company_filing_http import company_filing_fetch_response_with_retries
from app.data_sources.company_filing_parsers import (
    extract_company_filing_html_text,
    extract_pdf_text,
    is_pdf_response,
    pdf_title_from_url,
)
from app.data_sources.company_filing_render import (
    BROWSER_RENDER_PROVIDERS,
    company_filing_browser_render_limiter,
    company_filing_browser_render_provider,
    company_filing_browser_render_request,
    company_filing_browser_render_response_text,
    company_filing_user_agent_for_url,
)
from app.data_sources.company_filing_sources import MAX_FETCHED_DOCUMENT_BYTES
from app.data_sources.news import NewsFetcher
from app.models.schemas import NewsDocument, Source


FetchResponse = Callable[..., Awaitable[httpx.Response]]
PdfResponseToDocument = Callable[[str, bytes, str | None], NewsDocument]
BrowserRenderRequest = Callable[..., tuple[str, str, dict]]
BrowserRenderResponseText = Callable[..., tuple[str, str]]
BrowserRenderLimiter = Callable[[], Any]


async def fetch_url_as_company_filing_document(
    url: str,
    publisher: str | None = None,
    *,
    fetch_response_func: FetchResponse = company_filing_fetch_response_with_retries,
    pdf_response_to_document_func: PdfResponseToDocument | None = None,
) -> NewsDocument:
    response = await fetch_response_func(
        "GET",
        url,
        timeout=20,
        follow_redirects=True,
    )
    _validate_company_filing_response_size(response)
    content_type = response.headers.get("content-type", "").lower()
    pdf_response_to_document_func = pdf_response_to_document_func or pdf_response_to_company_filing_document
    if is_pdf_response(url, content_type):
        return pdf_response_to_document_func(url, response.content, publisher)
    return html_to_company_filing_document(
        html=response.text,
        url=url,
        publisher=publisher,
        id_seed=url,
    )


async def fetch_browser_rendered_company_filing_document(
    url: str,
    publisher: str | None = None,
    *,
    fetch_response_func: FetchResponse = company_filing_fetch_response_with_retries,
    pdf_response_to_document_func: PdfResponseToDocument | None = None,
    browser_render_provider_func: Callable[[], str] = company_filing_browser_render_provider,
    browser_render_request_func: BrowserRenderRequest = company_filing_browser_render_request,
    browser_render_response_text_func: BrowserRenderResponseText = company_filing_browser_render_response_text,
    browser_render_limiter_func: BrowserRenderLimiter = company_filing_browser_render_limiter,
    user_agent_func: Callable[[str], str] = company_filing_user_agent_for_url,
) -> NewsDocument:
    settings = get_settings()
    endpoint = settings.company_filing_browser_render_url.strip()
    if not endpoint:
        raise ValueError("company filing browser render URL is not configured")
    validate_public_document_url(url)
    provider = browser_render_provider_func()
    if provider not in BROWSER_RENDER_PROVIDERS:
        raise ValueError(f"unsupported company filing browser render provider: {provider}")
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "User-Agent": user_agent_func(url),
    }
    token = settings.company_filing_browser_render_token.strip()
    timeout = max(1.0, float(settings.company_filing_browser_render_timeout_seconds))
    rendered_url, method, request_kwargs = browser_render_request_func(
        provider=provider,
        endpoint=endpoint,
        target_url=url,
        headers=headers,
        token=token,
        timeout_seconds=timeout,
    )
    async with browser_render_limiter_func():
        response = await fetch_response_func(
            method,
            rendered_url,
            timeout=timeout,
            follow_redirects=True,
            identity_url=url,
            **request_kwargs,
        )
    _validate_company_filing_response_size(
        response,
        error_message="company filing browser-rendered content is too large to import",
    )
    content_type = response.headers.get("content-type", "").lower()
    pdf_response_to_document_func = pdf_response_to_document_func or pdf_response_to_company_filing_document
    if "application/pdf" in content_type:
        return pdf_response_to_document_func(url, response.content, publisher)
    html, final_url = browser_render_response_text_func(
        response,
        provider=provider,
        target_url=url,
    )
    return html_to_company_filing_document(
        html=html,
        url=final_url,
        publisher=publisher,
        id_seed=f"browser-rendered:{url}",
    )


async def fetch_playwright_rendered_company_filing_document(
    url: str,
    publisher: str | None = None,
    *,
    import_module_func: Callable[[str], object] = importlib.import_module,
    user_agent_func: Callable[[str], str] = company_filing_user_agent_for_url,
) -> NewsDocument:
    settings = get_settings()
    validate_public_document_url(url)
    try:
        playwright_api = import_module_func("playwright.async_api")
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
                user_agent=user_agent_func(url),
                locale="zh-TW",
            )
            await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            html = await page.content()
            final_url = str(getattr(page, "url", "") or url)
        finally:
            await browser.close()

    if len(html.encode("utf-8")) > MAX_FETCHED_DOCUMENT_BYTES:
        raise ValueError("company filing Playwright-rendered content is too large to import")
    return html_to_company_filing_document(
        html=html,
        url=final_url,
        publisher=publisher,
        id_seed=f"playwright-rendered:{url}",
    )


def pdf_response_to_company_filing_document(
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


def html_to_company_filing_document(
    *,
    html: str,
    url: str,
    publisher: str | None = None,
    id_seed: str | None = None,
) -> NewsDocument:
    soup = BeautifulSoup(html, "html.parser")
    title = NewsFetcher._title(soup) or url
    text = extract_company_filing_html_text(soup)
    return NewsDocument(
        id=sha1((id_seed or url).encode("utf-8")).hexdigest(),
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


def _validate_company_filing_response_size(
    response: httpx.Response,
    *,
    error_message: str = "company filing content is too large to import",
) -> None:
    content_length = int(response.headers.get("content-length") or 0)
    if content_length > MAX_FETCHED_DOCUMENT_BYTES or len(response.content) > MAX_FETCHED_DOCUMENT_BYTES:
        raise ValueError(error_message)
