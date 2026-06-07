from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from app.data_sources.company_filings import (
    CompanyFilingFetcher,
    company_filing_structured_api_status,
)


DEFAULT_TICKER = "2330"
DEFAULT_COMPANY_NAME = "台積電"
DEFAULT_DOCUMENT_TYPES = ("investor_presentation",)
SMOKE_COMMAND = (
    ".venv/bin/python scripts/structured_company_filing_smoke.py "
    "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
)


async def structured_company_filing_smoke_report(
    *,
    ticker: str = DEFAULT_TICKER,
    company_name: str = DEFAULT_COMPANY_NAME,
    document_types: list[str] | tuple[str, ...] | None = DEFAULT_DOCUMENT_TYPES,
    limit: int = 3,
    fetcher: CompanyFilingFetcher | None = None,
) -> dict[str, Any]:
    runtime = company_filing_structured_api_status()
    fallback_reason = runtime.get("fallback_reason")
    if not runtime.get("configured"):
        return {
            "status": "not_configured",
            "ready": False,
            "runtime": runtime,
            "smoke_command": SMOKE_COMMAND,
            "remediation": (
                "Configure COMPANY_FILING_STRUCTURED_API_PROVIDER and "
                "COMPANY_FILING_STRUCTURED_API_URL before running the live contract smoke."
            ),
        }
    if fallback_reason:
        return {
            "status": "invalid_configuration",
            "ready": False,
            "runtime": runtime,
            "smoke_command": SMOKE_COMMAND,
            "remediation": str(fallback_reason),
        }

    selected_fetcher = fetcher or CompanyFilingFetcher()
    requested_types = tuple(document_types or ())
    documents, errors = await selected_fetcher.fetch_structured_api_documents(
        ticker=ticker,
        company_name=company_name,
        limit=max(1, int(limit)),
        document_types=requested_types,
    )
    samples = [document_sample(document) for document in documents[:3]]
    status = "ready" if documents and not errors else "failed" if errors else "degraded"
    remediation = None
    if status == "degraded":
        remediation = (
            "The API responded but produced no convertible company filing documents. "
            "Check that rows include title plus text/content/summary and match the requested ticker/company."
        )
    elif status == "failed":
        remediation = "The configured structured API could not be fetched or parsed; inspect errors."
    return {
        "status": status,
        "ready": status == "ready",
        "runtime": runtime,
        "request": {
            "ticker": ticker,
            "company_name": company_name,
            "document_types": list(requested_types),
            "limit": max(1, int(limit)),
        },
        "document_count": len(documents),
        "error_count": len(errors),
        "documents": samples,
        "errors": errors,
        "smoke_command": SMOKE_COMMAND,
        "remediation": remediation,
    }


def document_sample(document: Any) -> dict[str, Any]:
    source = getattr(document, "source", None)
    published_at = getattr(source, "published_at", None)
    return {
        "id": getattr(document, "id", None),
        "ticker": getattr(document, "ticker", None),
        "document_type": getattr(document, "document_type", None),
        "title": getattr(document, "title", None),
        "publisher": getattr(source, "publisher", None),
        "published_at": published_at.isoformat() if published_at else None,
        "url": getattr(source, "url", None),
        "text_length": len(str(getattr(document, "text", "") or "")),
    }


def format_structured_company_filing_smoke(report: dict[str, Any]) -> str:
    lines = [
        f"Structured company filing API smoke: {report['status']}",
        f"- ready: {str(bool(report.get('ready'))).lower()}",
    ]
    runtime = report.get("runtime") or {}
    lines.append(f"- provider: {runtime.get('provider') or '-'}")
    lines.append(f"- url configured: {str(bool(runtime.get('url_configured'))).lower()}")
    if "document_count" in report:
        lines.append(f"- documents: {report.get('document_count', 0)}")
        lines.append(f"- errors: {report.get('error_count', 0)}")
    if report.get("remediation"):
        lines.append(f"- remediation: {report['remediation']}")
    if report.get("smoke_command"):
        lines.append(f"- command: {report['smoke_command']}")
    return "\n".join(lines)


def smoke_exit_code(report: dict[str, Any], *, strict: bool = False) -> int:
    if report.get("ready"):
        return 0
    if strict:
        return 1
    return 0 if report.get("status") == "not_configured" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test the configured structured company filing API contract."
    )
    parser.add_argument("--ticker", default=DEFAULT_TICKER, help="Ticker to query.")
    parser.add_argument("--company-name", default=DEFAULT_COMPANY_NAME, help="Company name to query.")
    parser.add_argument(
        "--document-type",
        dest="document_types",
        action="append",
        help="Requested document type. Can be repeated.",
    )
    parser.add_argument("--limit", type=int, default=3, help="Maximum documents to request.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when not ready.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    report = asyncio.run(
        structured_company_filing_smoke_report(
            ticker=args.ticker,
            company_name=args.company_name,
            document_types=args.document_types or list(DEFAULT_DOCUMENT_TYPES),
            limit=args.limit,
        )
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_structured_company_filing_smoke(report))
    return smoke_exit_code(report, strict=bool(args.strict))


if __name__ == "__main__":
    raise SystemExit(main())
