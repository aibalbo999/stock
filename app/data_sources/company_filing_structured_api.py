from __future__ import annotations

from datetime import date
from hashlib import sha1
import json
from pathlib import Path

from app.core.config import get_settings
from app.core.time import utc_now_naive
from app.data_sources.company_filing_discovery import (
    DOCUMENT_TYPE_KEYWORDS,
    infer_document_type,
    is_document_text_relevant,
)
from app.data_sources.company_filing_structured_api_profiles import (
    STRUCTURED_API_PROVIDER_PROFILES,
    STRUCTURED_API_RECOMMENDED_PAID_PROVIDER,
    STRUCTURED_API_REQUIRED_DOCUMENT_FIELDS,
    STRUCTURED_API_RESPONSE_ROW_ALIASES,
    structured_api_configuration_check,
    structured_api_provider_decision_matrix,
    structured_api_provider_profile,
    structured_api_provider_setup_preview,
    structured_api_request_contract as structured_api_request_contract,
)
from app.models.schemas import CompanyFilingDocument, NewsDocument, Source


STRUCTURED_API_SAMPLE_CONTRACT_PATH = Path("examples/structured_company_filing_sample.json")
STRUCTURED_API_LOCAL_FIXTURE_HOST = "127.0.0.1"
STRUCTURED_API_LOCAL_FIXTURE_PORT = 8794
STRUCTURED_API_LOCAL_FIXTURE_PATH = "/filings"
STRUCTURED_API_LOCAL_FIXTURE_URL = (
    f"http://{STRUCTURED_API_LOCAL_FIXTURE_HOST}:"
    f"{STRUCTURED_API_LOCAL_FIXTURE_PORT}{STRUCTURED_API_LOCAL_FIXTURE_PATH}"
)
STRUCTURED_API_LOCAL_FIXTURE_SERVE_CLI = (
    ".venv/bin/python scripts/local_structured_company_filing_api.py "
    "--sample-json examples/structured_company_filing_sample.json "
    f"--host {STRUCTURED_API_LOCAL_FIXTURE_HOST} "
    f"--port {STRUCTURED_API_LOCAL_FIXTURE_PORT}"
)
STRUCTURED_API_LOCAL_FIXTURE_SMOKE_CLI = (
    "COMPANY_FILING_STRUCTURED_API_PROVIDER=custom "
    f"COMPANY_FILING_STRUCTURED_API_URL={STRUCTURED_API_LOCAL_FIXTURE_URL} "
    ".venv/bin/python scripts/structured_company_filing_smoke.py "
    "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
)
STRUCTURED_API_LOCAL_FIXTURE_HTTP_SMOKE_CLI = (
    ".venv/bin/python scripts/structured_company_filing_fixture_smoke.py --json --strict"
)
STRUCTURED_API_LOCAL_PROVIDER_PROFILE_SMOKE_CLI = (
    ".venv/bin/python scripts/structured_company_filing_fixture_smoke.py "
    f"--provider-profile {STRUCTURED_API_RECOMMENDED_PAID_PROVIDER} --json --strict"
)


def company_filing_structured_api_configured() -> bool:
    settings = get_settings()
    return bool(
        str(settings.company_filing_structured_api_provider or "").strip()
        and str(settings.company_filing_structured_api_url or "").strip()
    )


def company_filing_structured_api_status_payload(
    settings,
    *,
    retry_policy: dict,
    sample_contract: dict,
) -> dict:
    provider = str(settings.company_filing_structured_api_provider or "").strip().lower()
    endpoint = str(settings.company_filing_structured_api_url or "").strip()
    token = str(settings.company_filing_structured_api_token or "").strip()
    configured = bool(provider and endpoint)
    profile = structured_api_provider_profile(provider)
    configuration_check = structured_api_configuration_check(
        provider=provider,
        endpoint=endpoint,
        token=token,
        profile=profile,
    )
    return {
        "configured": configured,
        "configuration_ready": bool(configuration_check["ready"]),
        "configuration_check": configuration_check,
        "provider": provider or None,
        "provider_profile": profile,
        "provider_profile_key": profile["profile_key"],
        "supported_provider_examples": list(STRUCTURED_API_PROVIDER_PROFILES),
        "supported_provider_profiles": {
            key: {
                "label": value["label"],
                "auth_mode": value["auth_mode"],
                "token_location": value["token_location"],
                "document_type_param": value["document_type_param"],
                "request_param_keys": value["request_param_keys"],
            }
            for key, value in STRUCTURED_API_PROVIDER_PROFILES.items()
        },
        "provider_decision_matrix": structured_api_provider_decision_matrix(),
        "provider_selection_hint": (
            "免費版先用 custom local fixture 驗證 HTTP/JSON contract；"
            "若需要穩定法說會/重大訊息資料，再優先評估 TEJ；"
            "若需求是反爬資料集或 managed scraping，再評估 ScrapingBee/BrightData。"
        ),
        "url_configured": bool(endpoint),
        "token_configured": bool(token),
        "token_required": bool(configuration_check["token_required"]),
        "timeout_seconds": max(1.0, float(settings.company_filing_structured_api_timeout_seconds)),
        "retry_policy": retry_policy,
        "response_row_aliases": list(STRUCTURED_API_RESPONSE_ROW_ALIASES),
        "required_document_fields": list(STRUCTURED_API_REQUIRED_DOCUMENT_FIELDS),
        "request_contract": {
            "method": "GET",
            "auth_mode": profile["auth_mode"],
            "token_location": profile["token_location"],
            "query_param_keys": profile["request_param_keys"],
            "document_type_param": profile["document_type_param"],
            "response_rows": list(STRUCTURED_API_RESPONSE_ROW_ALIASES),
            "required_document_fields": list(STRUCTURED_API_REQUIRED_DOCUMENT_FIELDS),
        },
        "provider_setup_preview": structured_api_provider_setup_preview(
            provider=provider,
            endpoint=endpoint,
            token=token,
            ticker="2330",
            company_name="台積電",
            document_types=("investor_presentation",),
        ),
        "contract": (
            "GET JSON with documents/data/results/items/records/list rows; supported aliases include "
            "title/headline/doc_title, text/content/body/abstract, url/file_url/download_url, "
            "publisher/source_name, published_at/publish_date/report_date, document_type/doc_type/category."
        ),
        "smoke_cli": (
            ".venv/bin/python scripts/structured_company_filing_smoke.py "
            "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
        ),
        "sample_contract_cli": (
            ".venv/bin/python scripts/structured_company_filing_smoke.py "
            "--sample-json examples/structured_company_filing_sample.json "
            "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
        ),
        "local_fixture_api": {
            "mode": "local_http_sample_contract",
            "provider": "custom",
            "url": STRUCTURED_API_LOCAL_FIXTURE_URL,
            "token_required": False,
            "sample_json": str(STRUCTURED_API_SAMPLE_CONTRACT_PATH),
            "serve_cli": STRUCTURED_API_LOCAL_FIXTURE_SERVE_CLI,
            "smoke_cli": STRUCTURED_API_LOCAL_FIXTURE_SMOKE_CLI,
            "http_smoke_cli": STRUCTURED_API_LOCAL_FIXTURE_HTTP_SMOKE_CLI,
            "provider_profile_smoke_cli": STRUCTURED_API_LOCAL_PROVIDER_PROFILE_SMOKE_CLI,
            "provider_profile": STRUCTURED_API_RECOMMENDED_PAID_PROVIDER,
            "purpose": (
                "Run the existing live HTTP fetch path against the bundled sample contract "
                "before a paid TEJ/professional API is configured; the provider-profile smoke "
                "also validates TEJ auth and document_type request mapping with a local dummy token."
            ),
        },
        "local_fixture_start_cli": STRUCTURED_API_LOCAL_FIXTURE_SERVE_CLI,
        "local_fixture_smoke_cli": STRUCTURED_API_LOCAL_FIXTURE_SMOKE_CLI,
        "local_fixture_http_smoke_cli": STRUCTURED_API_LOCAL_FIXTURE_HTTP_SMOKE_CLI,
        "local_fixture_provider_profile_smoke_cli": STRUCTURED_API_LOCAL_PROVIDER_PROFILE_SMOKE_CLI,
        "free_validation": {
            "status": "ready" if sample_contract.get("ready") else "degraded",
            "sample_contract_ready": bool(sample_contract.get("ready")),
            "local_fixture_available": True,
            "provider_profile_fixture_available": True,
            "provider_profile": STRUCTURED_API_RECOMMENDED_PAID_PROVIDER,
            "live_paid_provider_configured": bool(configuration_check["ready"]),
            "local_fixture_url": STRUCTURED_API_LOCAL_FIXTURE_URL,
            "sample_contract_cli": (
                ".venv/bin/python scripts/structured_company_filing_smoke.py "
                "--sample-json examples/structured_company_filing_sample.json "
                "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
            ),
            "local_fixture_start_cli": STRUCTURED_API_LOCAL_FIXTURE_SERVE_CLI,
            "local_fixture_smoke_cli": STRUCTURED_API_LOCAL_FIXTURE_SMOKE_CLI,
            "local_fixture_http_smoke_cli": STRUCTURED_API_LOCAL_FIXTURE_HTTP_SMOKE_CLI,
            "local_fixture_provider_profile_smoke_cli": (
                STRUCTURED_API_LOCAL_PROVIDER_PROFILE_SMOKE_CLI
            ),
            "purpose": (
                "Free-tier validation covers JSON mapping plus the live HTTP fetch path "
                "against a local fixture, including a TEJ profile auth/parameter smoke with "
                "a local dummy token; paid/provider credentials are required only for production "
                "TEJ or professional data feeds."
            ),
        },
        "sample_contract": sample_contract,
        "sample_contract_ready": bool(sample_contract.get("ready")),
        "fallback_reason": configuration_check["fallback_reason"],
    }


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
    documents: list[CompanyFilingDocument] = []
    errors: list[dict] = []
    for index, row in enumerate(rows):
        document = structured_api_row_to_company_filing_document(
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
    contract_diagnostics = structured_api_payload_contract_diagnostics(
        payload,
        ticker="2330",
        company_name="台積電",
        document_types=("investor_presentation",),
        documents=documents,
        row_errors=errors,
    )
    return {
        "status": status,
        "ready": status == "ready",
        "mode": "sample_json_contract",
        "sample_path": str(path),
        "raw_row_count": len(rows),
        "document_count": len(documents),
        "error_count": len(errors),
        "errors": errors[:10],
        "contract_diagnostics": contract_diagnostics,
        "smoke_cli": smoke_cli,
    }


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
