from __future__ import annotations

from urllib.parse import quote_plus, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.data_sources.company_filing_discovery import (
    extract_html_redirect_url,
    normalize_search_result_url,
    normalize_tpex_company_profile,
)
from app.data_sources.company_filing_http import (
    company_filing_client_options,
    company_filing_fetch_response_with_retries,
    company_filing_request_with_retries,
)


MAX_FETCHED_DOCUMENT_BYTES = 20_000_000
OFFICIAL_WEBSITE_FETCH_TIMEOUT_SECONDS = 8
MOPS_DOCUMENT_ENTRY_URL = "https://doc.twse.com.tw/server-java/t57sb01"
TWSE_COMPANY_PROFILE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_COMPANY_PROFILE_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"


async def fetch_company_filing_url_text(
    url: str,
    encoding: str | None = None,
    timeout: int = 20,
) -> str:
    text, _ = await fetch_company_filing_url_text_with_final_url(
        url,
        encoding=encoding,
        timeout=timeout,
    )
    return text


async def fetch_company_filing_url_text_with_final_url(
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


async def download_mops_pdf(ticker: str, filename: str, kind: str) -> tuple[str, bytes]:
    async with httpx.AsyncClient(
        **company_filing_client_options(
            MOPS_DOCUMENT_ENTRY_URL,
            timeout=30,
            follow_redirects=True,
        )
    ) as client:
        response = await company_filing_request_with_retries(
            client,
            "POST",
            MOPS_DOCUMENT_ENTRY_URL,
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


async def fetch_twse_company_profiles() -> list[dict]:
    response = await company_filing_fetch_response_with_retries(
        "GET",
        TWSE_COMPANY_PROFILE_URL,
        timeout=20,
        follow_redirects=True,
    )
    payload = response.json()
    return payload if isinstance(payload, list) else []


async def fetch_tpex_company_profiles() -> list[dict]:
    response = await company_filing_fetch_response_with_retries(
        "GET",
        TPEX_COMPANY_PROFILE_URL,
        timeout=20,
        follow_redirects=True,
    )
    payload = response.json()
    return payload if isinstance(payload, list) else []


def company_profile_from_rows(ticker: str, *, twse_rows: list[dict], tpex_rows: list[dict]) -> dict:
    twse_row = next((row for row in twse_rows if str(row.get("公司代號") or "") == ticker), None)
    if twse_row:
        return twse_row
    tpex_row = next(
        (
            row
            for row in tpex_rows
            if str(row.get("SecuritiesCompanyCode") or "") == ticker
        ),
        None,
    )
    return normalize_tpex_company_profile(tpex_row) if tpex_row else {}


async def duckduckgo_company_filing_search(query_text: str, limit: int = 5) -> list[dict]:
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
