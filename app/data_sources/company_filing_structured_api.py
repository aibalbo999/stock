from __future__ import annotations

import json
from pathlib import Path

from app.core.config import get_settings
from app.data_sources.company_filing_structured_api_documents import (
    parse_structured_api_date as parse_structured_api_date,
    structured_api_document_rows,
    structured_api_document_type as structured_api_document_type,
    structured_api_enriched_text as structured_api_enriched_text,
    structured_api_payload_contract_diagnostics,
    structured_api_row_text as structured_api_row_text,
    structured_api_row_to_company_filing_document,
    structured_api_row_to_news_document as structured_api_row_to_news_document,
    structured_api_row_value as structured_api_row_value,
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
from app.models.schemas import CompanyFilingDocument


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
