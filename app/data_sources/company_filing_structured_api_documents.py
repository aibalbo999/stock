from __future__ import annotations

from datetime import date
from hashlib import sha1

from app.core.time import utc_now_naive
from app.data_sources.company_filing_discovery import (
    DOCUMENT_TYPE_KEYWORDS,
    infer_document_type,
    is_document_text_relevant,
)
from app.data_sources.company_filing_structured_api_profiles import (
    STRUCTURED_API_REQUIRED_DOCUMENT_FIELDS,
    STRUCTURED_API_RESPONSE_ROW_ALIASES,
)
from app.models.schemas import CompanyFilingDocument, NewsDocument, Source


def structured_api_document_rows(payload: object) -> list[dict]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = (
            payload.get("documents")
            or payload.get("data")
            or payload.get("results")
            or payload.get("items")
            or payload.get("records")
            or payload.get("list")
            or []
        )
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


def structured_api_payload_contract_diagnostics(
    payload: object,
    *,
    ticker: str,
    company_name: str = "",
    document_types: list[str] | tuple[str, ...] | None = None,
    documents: list[object] | tuple[object, ...] | None = None,
    row_errors: list[dict] | tuple[dict, ...] | None = None,
) -> dict:
    raw_rows, row_container = _structured_api_payload_rows_and_container(payload)
    object_rows = [row for row in raw_rows if isinstance(row, dict)]
    requested_types = tuple(document_types or ())
    object_row_count = len(object_rows)
    convertible_document_count = len(documents or [])
    field_coverage = _structured_api_field_coverage(
        object_rows,
        ticker=ticker,
        company_name=company_name,
        document_types=requested_types,
    )
    return {
        "row_container": row_container,
        "accepted_row_containers": ["root_list", *STRUCTURED_API_RESPONSE_ROW_ALIASES],
        "raw_row_count": len(raw_rows),
        "object_row_count": object_row_count,
        "non_object_row_count": max(0, len(raw_rows) - object_row_count),
        "convertible_document_count": convertible_document_count,
        "row_error_count": len(row_errors or []),
        "conversion_ratio": (
            round(convertible_document_count / object_row_count, 4)
            if object_row_count
            else 0.0
        ),
        "field_coverage": field_coverage,
        "required_document_fields": list(STRUCTURED_API_REQUIRED_DOCUMENT_FIELDS),
        "requested_document_types": list(requested_types),
    }


def structured_api_row_value(row: dict, *keys: str) -> object:
    for key in keys:
        current: object = row
        for part in str(key).split("."):
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current.get(part)
        if current not in (None, ""):
            return current
    return None


def structured_api_row_text(row: dict, *keys: str) -> str:
    value = structured_api_row_value(row, *keys)
    if isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value or "").strip()


def structured_api_enriched_text(
    text: str,
    row: dict,
    *,
    ticker: str,
    company_name: str,
    document_type: str,
) -> str:
    metadata_terms = [
        ticker,
        company_name,
        document_type,
        document_type.replace("_", " "),
        structured_api_row_text(
            row,
            "document_type",
            "documentType",
            "doc_type",
            "filing_type",
            "category",
            "type",
        ),
        structured_api_row_text(
            row, "ticker", "stock_id", "stockId", "stock_no", "stockNo", "company_id"
        ),
        structured_api_row_text(row, "company", "company_name", "companyName", "company_full_name"),
    ]
    metadata = " ".join(term for term in metadata_terms if term)
    return f"[Structured API metadata] {metadata}\n{text}" if metadata else text


def structured_api_document_type(row: dict, *, title: str, text: str, url: str | None) -> str:
    raw_type = structured_api_row_text(
        row,
        "document_type",
        "documentType",
        "doc_type",
        "filing_type",
        "category",
        "type",
    )
    if raw_type in DOCUMENT_TYPE_KEYWORDS:
        return raw_type
    return infer_document_type(f"{raw_type}\n{title}\n{text}\n{url or ''}")


def structured_api_row_to_news_document(
    row: dict,
    *,
    ticker: str,
    company_name: str,
    provider: str,
    document_types: list[str] | tuple[str, ...] | None = None,
) -> tuple[NewsDocument, str] | None:
    title = structured_api_row_text(
        row,
        "title",
        "name",
        "headline",
        "subject",
        "doc_title",
        "document_title",
        "report_title",
    )
    text = structured_api_row_text(
        row,
        "text",
        "content",
        "summary",
        "body",
        "abstract",
        "description",
        "plain_text",
        "ocr_text",
    )
    url = (
        structured_api_row_text(
            row,
            "url",
            "source_url",
            "file_url",
            "download_url",
            "document_url",
            "documentUrl",
            "pdf_url",
            "source.url",
            "file.url",
            "document.url",
        )
        or None
    )
    document_type = structured_api_document_type(row, title=title, text=text, url=url)
    if document_types and document_type not in set(document_types):
        return None
    if not title or not text:
        return None
    text = structured_api_enriched_text(
        text,
        row,
        ticker=ticker,
        company_name=company_name,
        document_type=document_type,
    )
    publisher = (
        structured_api_row_text(
            row,
            "publisher",
            "source_name",
            "provider",
            "source.publisher",
            "metadata.publisher",
        )
        or provider
        or "structured company filing API"
    )
    source = Source(
        title=title,
        url=url,
        publisher=publisher,
        published_at=parse_structured_api_date(
            structured_api_row_value(
                row,
                "published_at",
                "date",
                "publish_date",
                "publishedDate",
                "report_date",
                "filing_date",
                "announcement_date",
                "updated_at",
            )
        ),
        fetched_at=utc_now_naive(),
    )
    document = NewsDocument(
        id=sha1(
            f"structured-api:{ticker}:{document_type}:{url or title}".encode("utf-8")
        ).hexdigest(),
        title=title,
        text=text,
        source=source,
    )
    if not is_document_text_relevant(document, ticker, company_name, document_types):
        return None
    return document, document_type


def structured_api_row_to_company_filing_document(
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
    digest = sha1(
        f"{ticker}:{document_type}:{news_document.source.url or news_document.id}".encode("utf-8")
    ).hexdigest()
    return CompanyFilingDocument(
        id=digest,
        ticker=ticker,
        company_name=company_name or None,
        document_type=document_type,
        title=news_document.title,
        text=news_document.text,
        source=news_document.source,
    )


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


def _structured_api_payload_rows_and_container(payload: object) -> tuple[list[object], str | None]:
    if isinstance(payload, list):
        return list(payload), "root_list"
    if not isinstance(payload, dict):
        return [], None
    for key in STRUCTURED_API_RESPONSE_ROW_ALIASES:
        if key not in payload:
            continue
        value = payload.get(key)
        return (list(value), key) if isinstance(value, list) else ([], f"{key}:non_list")
    return [], None


def _structured_api_field_coverage(
    rows: list[dict],
    *,
    ticker: str,
    company_name: str,
    document_types: list[str] | tuple[str, ...],
) -> dict:
    coverage = {
        "title": 0,
        "text": 0,
        "url": 0,
        "publisher": 0,
        "published_at": 0,
        "ticker_or_company_mention": 0,
        "requested_document_type_match": 0,
    }
    requested_types = set(document_types or [])
    for row in rows:
        title = structured_api_row_text(
            row,
            "title",
            "name",
            "headline",
            "subject",
            "doc_title",
            "document_title",
            "report_title",
        )
        text = structured_api_row_text(
            row,
            "text",
            "content",
            "summary",
            "body",
            "abstract",
            "description",
            "plain_text",
            "ocr_text",
        )
        url = structured_api_row_text(
            row,
            "url",
            "source_url",
            "file_url",
            "download_url",
            "document_url",
            "documentUrl",
            "pdf_url",
            "source.url",
            "file.url",
            "document.url",
        )
        publisher = structured_api_row_text(
            row,
            "publisher",
            "source_name",
            "provider",
            "source.publisher",
            "metadata.publisher",
        )
        raw_date = structured_api_row_value(
            row,
            "published_at",
            "date",
            "publish_date",
            "publishedDate",
            "report_date",
            "filing_date",
            "announcement_date",
            "updated_at",
        )
        document_type = structured_api_document_type(row, title=title, text=text, url=url or None)
        mention_text = structured_api_enriched_text(
            f"{title}\n{text}",
            row,
            ticker=ticker,
            company_name=company_name,
            document_type=document_type,
        )
        coverage["title"] += int(bool(title))
        coverage["text"] += int(bool(text))
        coverage["url"] += int(bool(url))
        coverage["publisher"] += int(bool(publisher))
        coverage["published_at"] += int(raw_date not in (None, ""))
        coverage["ticker_or_company_mention"] += int(
            bool(ticker and ticker in mention_text)
            or bool(company_name and company_name in mention_text)
        )
        coverage["requested_document_type_match"] += int(
            not requested_types or document_type in requested_types
        )
    return coverage
