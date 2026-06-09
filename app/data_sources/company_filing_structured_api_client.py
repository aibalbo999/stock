from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.data_sources.company_filing_structured_api_documents import (
    structured_api_document_rows,
    structured_api_payload_contract_diagnostics,
    structured_api_row_to_company_filing_document,
)
from app.data_sources.company_filing_structured_api_profiles import (
    STRUCTURED_API_REQUIRED_DOCUMENT_FIELDS,
    STRUCTURED_API_RESPONSE_ROW_ALIASES,
    structured_api_configuration_check,
    structured_api_provider_profile,
    structured_api_request_contract,
)
from app.models.schemas import CompanyFilingDocument


@dataclass(frozen=True)
class StructuredApiFetchResult:
    documents: list[CompanyFilingDocument]
    errors: list[dict]
    contract_diagnostics: dict | None = None


async def fetch_configured_structured_api_documents(
    *,
    settings: object,
    ticker: str,
    company_name: str = "",
    limit: int = 3,
    document_types: list[str] | tuple[str, ...] | None = None,
    fetch_response_func: Callable[..., Awaitable[Any]],
    error_func: Callable[..., dict],
    row_to_document_func: Callable[..., CompanyFilingDocument | None] = (
        structured_api_row_to_company_filing_document
    ),
) -> StructuredApiFetchResult:
    endpoint = str(getattr(settings, "company_filing_structured_api_url", "") or "").strip()
    provider = str(getattr(settings, "company_filing_structured_api_provider", "") or "").strip().lower()
    token = str(getattr(settings, "company_filing_structured_api_token", "") or "").strip()
    if not (provider and endpoint):
        return StructuredApiFetchResult(documents=[], errors=[])

    configuration_check = structured_api_configuration_check(
        provider=provider,
        endpoint=endpoint,
        token=token,
        profile=structured_api_provider_profile(provider),
    )
    if not configuration_check["ready"]:
        reason = str(configuration_check.get("fallback_reason") or "invalid_structured_api_configuration")
        return StructuredApiFetchResult(
            documents=[],
            errors=[
                error_func(
                    endpoint or provider or "structured_api_configuration",
                    reason,
                    stage="structured_api_configuration",
                )
            ],
        )

    request_contract = structured_api_request_contract(
        provider=provider,
        endpoint=endpoint,
        token=token,
        ticker=ticker,
        company_name=company_name,
        limit=limit,
        document_types=document_types,
    )
    try:
        response = await fetch_response_func(
            request_contract["method"],
            request_contract["endpoint"],
            timeout=max(
                1.0,
                float(getattr(settings, "company_filing_structured_api_timeout_seconds", 20.0)),
            ),
            follow_redirects=True,
            headers=request_contract["headers"],
            params=request_contract["params"],
        )
        payload = response.json()
        rows = structured_api_document_rows(payload)
        if not rows:
            diagnostics = structured_api_payload_contract_diagnostics(
                payload,
                ticker=ticker,
                company_name=company_name,
                document_types=document_types,
            )
            return StructuredApiFetchResult(
                documents=[],
                errors=[
                    error_func(
                        endpoint,
                        (
                            "structured API response did not contain document rows; "
                            f"expected one of {', '.join(STRUCTURED_API_RESPONSE_ROW_ALIASES)}"
                        ),
                        stage="structured_api",
                    )
                ],
                contract_diagnostics=diagnostics,
            )

        documents = [
            document
            for row in rows
            if (
                document := row_to_document_func(
                    row,
                    ticker=ticker,
                    company_name=company_name,
                    provider=provider,
                    document_types=document_types,
                )
            )
        ]
        row_errors = []
        if rows and not documents:
            row_errors = [
                {
                    "row_index": index,
                    "category": "row_not_convertible",
                    "required_fields": list(STRUCTURED_API_REQUIRED_DOCUMENT_FIELDS),
                }
                for index, _row in enumerate(rows)
            ]
        diagnostics = structured_api_payload_contract_diagnostics(
            payload,
            ticker=ticker,
            company_name=company_name,
            document_types=document_types,
            documents=documents,
            row_errors=row_errors,
        )
        if rows and not documents:
            return StructuredApiFetchResult(
                documents=[],
                errors=[
                    error_func(
                        endpoint,
                        (
                            "structured API rows were not convertible; required fields are "
                            f"{', '.join(STRUCTURED_API_REQUIRED_DOCUMENT_FIELDS)}"
                        ),
                        stage="structured_api",
                    )
                ],
                contract_diagnostics=diagnostics,
            )
        return StructuredApiFetchResult(
            documents=documents[: max(1, int(limit))],
            errors=[],
            contract_diagnostics=diagnostics,
        )
    except Exception as exc:
        return StructuredApiFetchResult(
            documents=[],
            errors=[error_func(endpoint, exc, stage="structured_api")],
        )
