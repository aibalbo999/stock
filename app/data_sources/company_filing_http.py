from __future__ import annotations

import asyncio
import re

import httpx

from app.core.config import get_settings
from app.data_sources.company_filing_discovery import looks_like_blocked_or_placeholder_filing_page
from app.data_sources.company_filing_parsers import (
    PDF_IMPORT_NO_TEXT_MESSAGE,
    PDF_IMPORT_PARSE_ERROR_MESSAGE,
)
from app.data_sources.company_filing_render import (
    company_filing_proxy_for_url,
    company_filing_user_agent_for_url,
)


COMPANY_FILING_RETRYABLE_HTTP_STATUSES = {403, 429, 500, 502, 503, 504}
RETRYABLE_COMPANY_FILING_ERROR_CATEGORIES = {
    "blocked_or_forbidden",
    "blocked_or_placeholder",
    "browser_render_failed",
    "network_error",
    "rate_limited",
    "timeout",
    "upstream_retryable",
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
    raise httpx.HTTPError("公司文件請求失敗且沒有回應內容")


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
    raise httpx.HTTPError("公司文件請求失敗且沒有回應內容")


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
    visual_rag_category = _company_filing_visual_rag_error_category(message, lowered)
    if visual_rag_category:
        return visual_rag_category
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
    if "structured api response did not contain document rows" in lowered:
        return "structured_api_no_rows"
    if "structured api rows were not convertible" in lowered:
        return "structured_api_no_convertible_rows"
    if (
        "missing_structured_api_provider_or_url" in lowered
        or "missing_structured_api_token" in lowered
        or "invalid_structured_api_url" in lowered
    ):
        return "structured_api_not_configured"
    return "unknown"


def is_retryable_company_filing_error_category(category: str) -> bool:
    return category in RETRYABLE_COMPANY_FILING_ERROR_CATEGORIES


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


def _company_filing_visual_rag_error_category(message: str, lowered: str) -> str | None:
    if "visual rag" not in lowered and "Visual RAG" not in message:
        return None
    if "pymupdf" in lowered or "fitz" in lowered or "missing_dependency:pymupdf" in lowered:
        return "visual_rag_missing_dependency"
    if "resource_exhausted" in lowered or "quota" in lowered or "daily limit" in lowered or "429" in lowered:
        return "visual_rag_quota"
    if (
        "api key" in lowered
        or "gateway" in lowered
        or "missing_vision_llm_key_or_gateway" in lowered
        or "尚未配置" in message
        or "尚未啟用" in message
        or "不支援" in message
        or "unsupported_visual_rag" in lowered
        or "需要支援圖片輸入" in message
    ):
        return "visual_rag_not_configured"
    return "visual_rag_failed"


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
