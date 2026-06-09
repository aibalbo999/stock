from __future__ import annotations

from datetime import date
from hashlib import sha1
import json
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import get_settings
from app.core.time import utc_now_naive
from app.data_sources.company_filing_discovery import (
    DOCUMENT_TYPE_KEYWORDS,
    infer_document_type,
    is_document_text_relevant,
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
STRUCTURED_API_RECOMMENDED_PAID_PROVIDER = "tej"
STRUCTURED_API_LOCAL_PROVIDER_PROFILE_SMOKE_CLI = (
    ".venv/bin/python scripts/structured_company_filing_fixture_smoke.py "
    f"--provider-profile {STRUCTURED_API_RECOMMENDED_PAID_PROVIDER} --json --strict"
)
STRUCTURED_API_PROVIDER_PROFILES = {
    "tej": {
        "label": "TEJ structured company filings",
        "auth_mode": "bearer",
        "token_location": "authorization_header",
        "document_type_param": "document_type",
        "request_param_keys": ["ticker", "company_name", "limit", "document_type"],
    },
    "scrapingbee_dataset": {
        "label": "ScrapingBee dataset/API fallback",
        "auth_mode": "query_param",
        "token_location": "query_param",
        "token_param": "api_key",
        "document_type_param": "document_types",
        "request_param_keys": ["ticker", "company_name", "limit", "document_types", "api_key"],
    },
    "brightdata_dataset": {
        "label": "BrightData dataset/API fallback",
        "auth_mode": "bearer",
        "token_location": "authorization_header",
        "document_type_param": "document_types",
        "request_param_keys": ["ticker", "company_name", "limit", "document_types"],
    },
    "custom": {
        "label": "Custom structured company filing API",
        "auth_mode": "bearer_optional",
        "token_location": "authorization_header",
        "document_type_param": "document_types",
        "request_param_keys": ["ticker", "company_name", "limit", "document_types"],
    },
}
STRUCTURED_API_RESPONSE_ROW_ALIASES = ("documents", "data", "results", "items", "records", "list")
STRUCTURED_API_REQUIRED_DOCUMENT_FIELDS = (
    "title/name/headline/doc_title",
    "text/content/body/abstract/summary",
    "ticker_or_company_mention",
    "document_type_match",
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


def structured_api_configuration_check(
    *,
    provider: str,
    endpoint: str,
    token: str,
    profile: dict,
) -> dict:
    normalized_provider = str(provider or "").strip().lower()
    normalized_endpoint = str(endpoint or "").strip()
    token_configured = bool(str(token or "").strip())
    token_required = _structured_api_token_required(profile)
    required_env_keys = [
        "COMPANY_FILING_STRUCTURED_API_PROVIDER",
        "COMPANY_FILING_STRUCTURED_API_URL",
    ]
    if token_required:
        required_env_keys.append("COMPANY_FILING_STRUCTURED_API_TOKEN")
    configured_env_keys = []
    if normalized_provider:
        configured_env_keys.append("COMPANY_FILING_STRUCTURED_API_PROVIDER")
    if normalized_endpoint:
        configured_env_keys.append("COMPANY_FILING_STRUCTURED_API_URL")
    if token_configured:
        configured_env_keys.append("COMPANY_FILING_STRUCTURED_API_TOKEN")
    missing_env_keys = [key for key in required_env_keys if key not in set(configured_env_keys)]
    parsed = urlparse(normalized_endpoint)
    endpoint_valid = bool(parsed.scheme in {"http", "https"} and parsed.hostname)
    if missing_env_keys:
        fallback_reason = "missing_structured_api_provider_or_url"
        if missing_env_keys == ["COMPANY_FILING_STRUCTURED_API_TOKEN"]:
            fallback_reason = "missing_structured_api_token"
        status = "missing_required_env"
    elif not endpoint_valid:
        fallback_reason = "invalid_structured_api_url"
        status = "invalid_url"
    else:
        fallback_reason = None
        status = "ready"
    return {
        "ready": status == "ready",
        "status": status,
        "fallback_reason": fallback_reason,
        "required_env_keys": required_env_keys,
        "configured_env_keys": configured_env_keys,
        "missing_env_keys": missing_env_keys,
        "token_required": token_required,
        "token_configured": token_configured,
        "endpoint_configured": bool(normalized_endpoint),
        "endpoint_valid": endpoint_valid,
        "endpoint_scheme": parsed.scheme or None,
        "endpoint_host_configured": bool(parsed.hostname),
        "provider_profile_key": str(profile.get("profile_key") or "custom"),
        "auth_mode": str(profile.get("auth_mode") or "bearer_optional"),
        "token_location": str(profile.get("token_location") or "authorization_header"),
    }


def structured_api_provider_decision_matrix() -> list[dict]:
    rows: list[dict] = []
    for provider_key, profile in STRUCTURED_API_PROVIDER_PROFILES.items():
        token_required = _structured_api_token_required(profile)
        query_param_keys = [str(key) for key in profile["request_param_keys"]]
        rows.append(
            {
                "provider": provider_key,
                "label": str(profile["label"]),
                "auth_mode": str(profile["auth_mode"]),
                "token_required": token_required,
                "token_location": str(profile["token_location"]),
                "document_type_param": str(profile["document_type_param"]),
                "request_param_keys": query_param_keys,
                "response_row_aliases": list(STRUCTURED_API_RESPONSE_ROW_ALIASES),
                "required_document_fields": list(STRUCTURED_API_REQUIRED_DOCUMENT_FIELDS),
                "env_keys": _structured_api_provider_env_keys(token_required),
                "recommended_when": _structured_api_provider_recommendation(provider_key),
            }
        )
    return rows


def structured_api_provider_setup_preview(
    *,
    provider: str,
    endpoint: str,
    token: str = "",
    ticker: str,
    company_name: str = "",
    limit: int = 3,
    document_types: list[str] | tuple[str, ...] | None = None,
) -> dict:
    preview_provider = (
        str(provider or "").strip().lower() or STRUCTURED_API_RECOMMENDED_PAID_PROVIDER
    )
    profile = structured_api_provider_profile(preview_provider)
    token_required = _structured_api_token_required(profile)
    preview_endpoint = str(endpoint or "").strip() or "<provider-json-endpoint>"
    preview_token = str(token or "").strip()
    if not preview_token and token_required:
        preview_token = "<token>"
    contract = structured_api_request_contract(
        provider=preview_provider,
        endpoint=preview_endpoint,
        token=preview_token,
        ticker=ticker,
        company_name=company_name,
        limit=limit,
        document_types=document_types,
    )
    headers = dict(contract["headers"])
    params = dict(contract["params"])
    token_redacted = False
    if "Authorization" in headers:
        headers["Authorization"] = "Bearer <redacted>"
        token_redacted = True
    token_param = str(profile.get("token_param") or "api_key")
    if token_param in params:
        params[token_param] = "<redacted>"
        token_redacted = True
    env_template = [
        f"COMPANY_FILING_STRUCTURED_API_PROVIDER={profile['profile_key']}",
        "COMPANY_FILING_STRUCTURED_API_URL=<provider-json-endpoint>",
    ]
    if token_required:
        env_template.append("COMPANY_FILING_STRUCTURED_API_TOKEN=<token>")
    return {
        "recommended_provider": STRUCTURED_API_RECOMMENDED_PAID_PROVIDER,
        "provider": profile["provider"],
        "profile_key": profile["profile_key"],
        "label": profile["label"],
        "env_template": env_template,
        "method": contract["method"],
        "endpoint": contract["endpoint"],
        "headers": headers,
        "params": params,
        "auth_mode": contract["auth_mode"],
        "token_location": contract["token_location"],
        "token_required": token_required,
        "token_redacted": token_redacted,
        "document_type_param": contract["document_type_param"],
    }


def _structured_api_provider_env_keys(token_required: bool) -> list[str]:
    env_keys = [
        "COMPANY_FILING_STRUCTURED_API_PROVIDER",
        "COMPANY_FILING_STRUCTURED_API_URL",
    ]
    if token_required:
        env_keys.append("COMPANY_FILING_STRUCTURED_API_TOKEN")
    return env_keys


def _structured_api_provider_recommendation(provider_key: str) -> str:
    recommendations = {
        "tej": "正式穩定取得台灣法說會、重大訊息或專業財經資料時優先評估。",
        "scrapingbee_dataset": "已有 ScrapingBee dataset/API 或需要 managed scraping pipeline 時使用。",
        "brightdata_dataset": "已有 BrightData dataset/API 或需要商用資料採集 SLA 時使用。",
        "custom": "免費版、本機 fixture、內部資料湖或自行包裝資料商 API 時使用。",
    }
    return recommendations.get(provider_key, "依資料商 contract 設定。")


def _structured_api_token_required(profile: dict) -> bool:
    return str(profile.get("auth_mode") or "").strip().lower() not in {
        "",
        "bearer_optional",
        "none",
    }


def structured_api_provider_profile(provider: str) -> dict:
    provider_key = str(provider or "").strip().lower() or "custom"
    profile_key = provider_key if provider_key in STRUCTURED_API_PROVIDER_PROFILES else "custom"
    profile = dict(STRUCTURED_API_PROVIDER_PROFILES[profile_key])
    profile["provider"] = provider_key
    profile["profile_key"] = profile_key
    profile["profile_supported"] = (
        provider_key in STRUCTURED_API_PROVIDER_PROFILES or profile_key == "custom"
    )
    return profile


def structured_api_request_contract(
    *,
    provider: str,
    endpoint: str,
    token: str = "",
    ticker: str,
    company_name: str = "",
    limit: int = 3,
    document_types: list[str] | tuple[str, ...] | None = None,
) -> dict:
    profile = structured_api_provider_profile(provider)
    headers = {"Accept": "application/json"}
    params: dict[str, object] = {
        "ticker": ticker,
        "company_name": company_name,
        "limit": max(1, int(limit)),
    }
    requested_types = ",".join(document_types or ())
    if requested_types:
        params[str(profile["document_type_param"])] = requested_types
    normalized_token = str(token or "").strip()
    if normalized_token and profile["token_location"] == "authorization_header":
        headers["Authorization"] = f"Bearer {normalized_token}"
    elif normalized_token and profile["token_location"] == "query_param":
        params[str(profile.get("token_param") or "api_key")] = normalized_token
    return {
        "method": "GET",
        "provider": profile["provider"],
        "profile_key": profile["profile_key"],
        "endpoint": endpoint,
        "headers": headers,
        "params": params,
        "auth_mode": profile["auth_mode"],
        "token_location": profile["token_location"],
        "document_type_param": profile["document_type_param"],
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
