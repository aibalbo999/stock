from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from hashlib import sha1

from bs4 import BeautifulSoup

from app.core.time import utc_now_naive
from app.data_sources.company_filing_discovery import (
    extract_company_filing_links,
    infer_document_type,
    is_document_text_relevant,
    is_relevant_company_filing_result,
    normalize_company_website,
    official_website_seed_urls,
    parse_mops_annual_report_rows,
    parse_mops_roc_datetime,
    validate_fetched_company_filing_document,
)
from app.data_sources.company_filing_http import company_filing_error
from app.data_sources.company_filing_parsers import extract_pdf_text
from app.data_sources.company_filing_sources import OFFICIAL_WEBSITE_FETCH_TIMEOUT_SECONDS
from app.data_sources.news import NewsFetcher
from app.models.schemas import CompanyFilingDocument, NewsDocument, Source


FetchUrlDocument = Callable[..., Awaitable[CompanyFilingDocument]]
BuildManualDocument = Callable[..., CompanyFilingDocument]
FetchText = Callable[..., Awaitable[str]]
FetchTextWithFinalUrl = Callable[..., Awaitable[tuple[str, str]]]
DownloadMopsPdf = Callable[[str, str, str], Awaitable[tuple[str, bytes]]]
SearchCompanyFilings = Callable[[str, int], Awaitable[list[dict]]]
CompanyProfileLookup = Callable[[str], Awaitable[dict]]


async def fetch_web_search_company_filing_documents(
    *,
    ticker: str,
    company_name: str = "",
    queries: list[str] | tuple[str, ...],
    limit_per_query: int = 5,
    document_types: list[str] | tuple[str, ...] | None = None,
    search_func: SearchCompanyFilings,
    fetch_url_document_func: FetchUrlDocument,
) -> tuple[list[CompanyFilingDocument], list[dict]]:
    documents: list[CompanyFilingDocument] = []
    errors = []
    seen_urls: set[str] = set()
    for query_text in queries:
        try:
            results = await search_func(query_text, limit_per_query)
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
                document = await fetch_url_document_func(
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


async def fetch_mops_annual_report_company_filing_documents(
    *,
    ticker: str,
    company_name: str = "",
    years: int = 3,
    fetch_url_text_func: FetchText,
    download_mops_pdf_func: DownloadMopsPdf,
    build_manual_document_func: BuildManualDocument,
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
            html = await fetch_url_text_func(query_url, encoding="big5")
            rows = parse_mops_annual_report_rows(html)
        except Exception as exc:
            errors.append(company_filing_error(query_url, exc, stage="mops_query"))
            continue
        for row in rows:
            filename = row.get("filename") or ""
            if not filename:
                continue
            try:
                pdf_url, content = await download_mops_pdf_func(ticker, filename, "F")
                text = extract_pdf_text(content)
                title = row.get("description") or filename
                published_at = parse_mops_roc_datetime(row.get("uploaded_at") or "")
                document = build_manual_document_func(
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


async def fetch_official_website_company_filing_documents(
    *,
    ticker: str,
    company_name: str = "",
    limit: int = 12,
    document_types: list[str] | tuple[str, ...] | None = None,
    profile_func: CompanyProfileLookup,
    fetch_url_text_with_final_url_func: FetchTextWithFinalUrl,
    fetch_url_document_func: FetchUrlDocument,
) -> tuple[list[CompanyFilingDocument], list[dict]]:
    profile = await profile_func(ticker)
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
            page_html, final_page_url = await fetch_url_text_with_final_url_func(
                page_url,
                timeout=OFFICIAL_WEBSITE_FETCH_TIMEOUT_SECONDS,
            )
            soup = BeautifulSoup(page_html, "html.parser")
            title = NewsFetcher._title(soup) or final_page_url
            page = NewsDocument(
                id=sha1(final_page_url.encode("utf-8")).hexdigest(),
                title=title,
                text=NewsFetcher._article_text(soup),
                source=Source(
                    title=title,
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
            document = await fetch_url_document_func(
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
