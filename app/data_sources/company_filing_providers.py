from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from hashlib import sha1
import re

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
from app.data_sources.company_filing_sources import (
    OFFICIAL_WEBSITE_FETCH_TIMEOUT_SECONDS,
    TPEX_MATERIAL_INFORMATION_URL,
    TWSE_MATERIAL_INFORMATION_URL,
)
from app.data_sources.news import NewsFetcher
from app.models.schemas import CompanyFilingDocument, NewsDocument, Source


FetchUrlDocument = Callable[..., Awaitable[CompanyFilingDocument]]
BuildManualDocument = Callable[..., CompanyFilingDocument]
FetchText = Callable[..., Awaitable[str]]
FetchTextWithFinalUrl = Callable[..., Awaitable[tuple[str, str]]]
DownloadMopsPdf = Callable[[str, str, str], Awaitable[tuple[str, bytes]]]
SearchCompanyFilings = Callable[[str, int], Awaitable[list[dict]]]
CompanyProfileLookup = Callable[[str], Awaitable[dict]]
FetchMaterialInformationRows = Callable[[], Awaitable[list[dict]]]


_MATERIAL_INFORMATION_TICKER_ALIASES = (
    "公司代號",
    "公司代碼",
    "SecuritiesCompanyCode",
    "CompanyCode",
    "ticker",
)
_MATERIAL_INFORMATION_COMPANY_ALIASES = (
    "公司名稱",
    "CompanyName",
    "CompanyAbbreviation",
    "company_name",
)
_MATERIAL_INFORMATION_SUBJECT_ALIASES = ("主旨", "Subject", "headline", "title")
_MATERIAL_INFORMATION_DESCRIPTION_ALIASES = ("說明", "Description", "content", "text")
_MATERIAL_INFORMATION_DATE_ALIASES = (
    "發言日期",
    "Date",
    "出表日期",
    "AnnouncementDate",
    "published_at",
)
_MATERIAL_INFORMATION_TIME_ALIASES = ("發言時間", "Time", "AnnouncementTime")
_MATERIAL_INFORMATION_EVENT_DATE_ALIASES = ("事實發生日", "EventDate")
_MATERIAL_INFORMATION_CLAUSE_ALIASES = ("符合條款", "Clause", "Article")


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


async def fetch_material_information_company_filing_documents(
    *,
    ticker: str,
    company_name: str = "",
    limit: int = 3,
    document_types: list[str] | tuple[str, ...] | None = None,
    fetch_twse_rows_func: FetchMaterialInformationRows,
    fetch_tpex_rows_func: FetchMaterialInformationRows,
    build_manual_document_func: BuildManualDocument,
) -> tuple[list[CompanyFilingDocument], list[dict]]:
    if document_types and "material_information" not in set(document_types):
        return [], []

    documents: list[CompanyFilingDocument] = []
    errors = []
    source_specs = (
        (
            "twse_material_information_openapi",
            "臺灣證券交易所 OpenAPI",
            TWSE_MATERIAL_INFORMATION_URL,
            fetch_twse_rows_func,
        ),
        (
            "tpex_material_information_openapi",
            "櫃買中心 OpenAPI",
            TPEX_MATERIAL_INFORMATION_URL,
            fetch_tpex_rows_func,
        ),
    )
    for stage, publisher, url, fetch_rows in source_specs:
        try:
            rows = await fetch_rows()
        except Exception as exc:
            errors.append(company_filing_error(url, exc, stage=stage))
            continue
        for row in rows:
            if not material_information_row_matches_company(row, ticker, company_name):
                continue
            document = material_information_row_to_company_filing_document(
                row,
                ticker=ticker,
                company_name=company_name,
                publisher=publisher,
                url=url,
                build_manual_document_func=build_manual_document_func,
            )
            if document is None:
                errors.append(
                    company_filing_error(
                        url,
                        "material information row missing subject or description",
                        stage=stage,
                    )
                )
                continue
            documents.append(document)
            if len(documents) >= max(1, int(limit)):
                return _sort_material_information_documents(documents), errors
    return _sort_material_information_documents(documents), errors


def material_information_row_matches_company(
    row: dict,
    ticker: str,
    company_name: str = "",
) -> bool:
    row_ticker = _material_information_row_value(row, _MATERIAL_INFORMATION_TICKER_ALIASES)
    if row_ticker:
        return row_ticker == ticker
    if not company_name:
        return False
    haystack = "\n".join(str(value or "") for value in row.values())
    return company_name in haystack


def material_information_row_to_company_filing_document(
    row: dict,
    *,
    ticker: str,
    company_name: str = "",
    publisher: str,
    url: str,
    build_manual_document_func: BuildManualDocument,
) -> CompanyFilingDocument | None:
    row_ticker = _material_information_row_value(row, _MATERIAL_INFORMATION_TICKER_ALIASES)
    row_company_name = _material_information_row_value(row, _MATERIAL_INFORMATION_COMPANY_ALIASES)
    subject = _material_information_row_value(row, _MATERIAL_INFORMATION_SUBJECT_ALIASES)
    description = _material_information_row_value(row, _MATERIAL_INFORMATION_DESCRIPTION_ALIASES)
    if not subject and not description:
        return None
    speech_date = _material_information_row_value(row, _MATERIAL_INFORMATION_DATE_ALIASES)
    speech_time = _material_information_row_value(row, _MATERIAL_INFORMATION_TIME_ALIASES)
    event_date = _material_information_row_value(row, _MATERIAL_INFORMATION_EVENT_DATE_ALIASES)
    clause = _material_information_row_value(row, _MATERIAL_INFORMATION_CLAUSE_ALIASES)
    effective_company_name = company_name or row_company_name
    title_company = row_company_name or effective_company_name or row_ticker or ticker
    title = f"{row_ticker or ticker} {title_company} 重大訊息"
    if subject:
        title = f"{title}：{subject}"
    text = "\n".join(
        part
        for part in (
            f"股票代號：{row_ticker or ticker}",
            f"公司名稱：{effective_company_name}" if effective_company_name else "",
            "文件類型：重大訊息 material information",
            f"發言日期：{speech_date}" if speech_date else "",
            f"發言時間：{speech_time}" if speech_time else "",
            f"符合條款：{clause}" if clause else "",
            f"事實發生日：{event_date}" if event_date else "",
            f"主旨：{subject}" if subject else "",
            f"說明：{description}" if description else "",
        )
        if part
    )
    return build_manual_document_func(
        ticker=ticker,
        company_name=effective_company_name,
        document_type="material_information",
        title=title,
        text=text,
        publisher=publisher,
        published_at=parse_material_information_date(speech_date),
        url=url,
    )


def parse_material_information_date(value: str) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = (
        raw.replace("民國", "")
        .replace("年", "/")
        .replace("月", "/")
        .replace("日", "")
        .strip()
    )
    parsed = parse_mops_roc_datetime(normalized)
    if parsed:
        return parsed
    digits = re.sub(r"\D", "", raw)
    try:
        if len(digits) == 7:
            return date(int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7]))
        if len(digits) == 8 and int(digits[:4]) >= 1912:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None
    return None


def _material_information_row_value(row: dict, aliases: tuple[str, ...]) -> str:
    normalized_row = {str(key).strip().lower(): value for key, value in row.items()}
    for alias in aliases:
        value = normalized_row.get(alias.strip().lower())
        if value is not None:
            return str(value or "").strip()
    return ""


def _sort_material_information_documents(
    documents: list[CompanyFilingDocument],
) -> list[CompanyFilingDocument]:
    return sorted(
        documents,
        key=lambda document: document.source.published_at or date.min,
        reverse=True,
    )


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
