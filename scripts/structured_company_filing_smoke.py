from __future__ import annotations

import argparse
import asyncio
import json
import shlex
from pathlib import Path
from typing import Any

from app.data_sources.company_filing_structured_api import (
    structured_api_document_rows,
    structured_api_payload_contract_diagnostics,
)
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
    sample_json_path: str | Path | None = None,
    fetcher: CompanyFilingFetcher | None = None,
) -> dict[str, Any]:
    runtime = company_filing_structured_api_status()
    if sample_json_path:
        return structured_company_filing_sample_report(
            sample_json_path=sample_json_path,
            ticker=ticker,
            company_name=company_name,
            document_types=document_types,
            limit=limit,
            runtime=runtime,
            fetcher=fetcher,
        )
    fallback_reason = runtime.get("fallback_reason")
    if not runtime.get("configured"):
        return {
            "status": "not_configured",
            "ready": False,
            "runtime": runtime,
            "smoke_command": SMOKE_COMMAND,
            "remediation": (
                "執行正式 API 檢查前，請先設定 COMPANY_FILING_STRUCTURED_API_PROVIDER "
                "與 COMPANY_FILING_STRUCTURED_API_URL。"
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
    contract_diagnostics = getattr(
        selected_fetcher,
        "last_structured_api_contract_diagnostics",
        {},
    ) or {}
    samples = [document_sample(document) for document in documents[:3]]
    status = "ready" if documents and not errors else "failed" if errors else "degraded"
    remediation = None
    if status == "degraded":
        remediation = (
            "API 有回應，但沒有可轉成公司文件的資料。請確認資料列包含 title "
            "以及 text/content/summary，且符合查詢的股票或公司。"
        )
    elif status == "failed":
        remediation = "已設定的結構化 API 無法抓取或解析；請檢查錯誤明細。"
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
        "contract_diagnostics": contract_diagnostics,
        "documents": samples,
        "errors": errors,
        "smoke_command": SMOKE_COMMAND,
        "remediation": remediation,
    }


def structured_company_filing_sample_report(
    *,
    sample_json_path: str | Path,
    ticker: str = DEFAULT_TICKER,
    company_name: str = DEFAULT_COMPANY_NAME,
    document_types: list[str] | tuple[str, ...] | None = DEFAULT_DOCUMENT_TYPES,
    limit: int = 3,
    runtime: dict[str, Any] | None = None,
    fetcher: CompanyFilingFetcher | None = None,
) -> dict[str, Any]:
    path = Path(sample_json_path)
    runtime = runtime or company_filing_structured_api_status()
    requested_types = tuple(document_types or ())
    smoke_command = structured_company_filing_sample_smoke_command(
        path,
        ticker=ticker,
        company_name=company_name,
        document_types=requested_types,
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return structured_company_filing_sample_error_report(
            path,
            runtime,
            "sample_json_unreadable",
            str(exc),
            smoke_command,
        )
    except json.JSONDecodeError as exc:
        return structured_company_filing_sample_error_report(
            path,
            runtime,
            "sample_json_invalid",
            str(exc),
            smoke_command,
        )

    rows = structured_api_document_rows(payload)
    parser = fetcher or CompanyFilingFetcher()
    provider = str(runtime.get("provider") or "sample")
    documents = []
    row_errors = []
    for index, row in enumerate(rows):
        document = parser._structured_api_row_to_document(
            row,
            ticker=ticker,
            company_name=company_name,
            provider=provider,
            document_types=requested_types,
        )
        if document:
            documents.append(document)
        else:
            row_errors.append(
                {
                    "row_index": index,
                    "category": "row_not_convertible",
                    "required_fields": [
                        "title/name",
                        "text/content/summary",
                        "ticker_or_company_mention",
                        "document_type_match",
                    ],
                }
            )

    if documents:
        status = "ready"
        remediation = None
    elif rows:
        status = "degraded"
        remediation = (
            "Sample JSON 資料列可讀，但無法轉成公司文件。請檢查 title/text 欄位、"
            "股票或公司名稱是否出現，以及 document_type 篩選是否正確。"
        )
    else:
        status = "failed"
        remediation = "Sample JSON 未包含 documents/data/results 資料列。"
    contract_diagnostics = structured_api_payload_contract_diagnostics(
        payload,
        ticker=ticker,
        company_name=company_name,
        document_types=requested_types,
        documents=documents,
        row_errors=row_errors,
    )

    return {
        "status": status,
        "ready": status == "ready",
        "mode": "sample_json_contract",
        "runtime": runtime,
        "sample_path": str(path),
        "request": {
            "ticker": ticker,
            "company_name": company_name,
            "document_types": list(requested_types),
            "limit": max(1, int(limit)),
        },
        "raw_row_count": len(rows),
        "document_count": len(documents),
        "error_count": len(row_errors),
        "contract_diagnostics": contract_diagnostics,
        "documents": [document_sample(document) for document in documents[: max(1, int(limit))]],
        "errors": row_errors[:10],
        "smoke_command": smoke_command,
        "remediation": remediation,
    }


def structured_company_filing_sample_error_report(
    path: Path,
    runtime: dict[str, Any],
    category: str,
    message: str,
    smoke_command: str,
) -> dict[str, Any]:
    return {
        "status": "failed",
        "ready": False,
        "mode": "sample_json_contract",
        "runtime": runtime,
        "sample_path": str(path),
        "document_count": 0,
        "error_count": 1,
        "documents": [],
        "errors": [{"category": category, "message": message}],
        "smoke_command": smoke_command,
        "remediation": "請提供可讀取、且格式為 documents/data/results 資料列的 JSON 檔案。",
    }


def structured_company_filing_sample_smoke_command(
    path: Path,
    *,
    ticker: str,
    company_name: str,
    document_types: list[str] | tuple[str, ...],
) -> str:
    parts = [
        ".venv/bin/python",
        "scripts/structured_company_filing_smoke.py",
        "--sample-json",
        str(path),
        "--ticker",
        ticker,
        "--company-name",
        company_name,
    ]
    for document_type in document_types:
        parts.extend(["--document-type", str(document_type)])
    parts.append("--json")
    return " ".join(shlex.quote(part) for part in parts if str(part).strip())


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
        f"公司文件結構化 API 檢查: {report['status']}",
        f"- 就緒: {_yes_no(report.get('ready'))}",
    ]
    runtime = report.get("runtime") or {}
    if report.get("mode"):
        lines.append(f"- 模式: {report['mode']}")
    if report.get("sample_path"):
        lines.append(f"- 樣本: {report['sample_path']}")
    lines.append(f"- 提供者: {runtime.get('provider') or '-'}")
    lines.append(f"- URL 已設定: {_yes_no(runtime.get('url_configured'))}")
    if "raw_row_count" in report:
        lines.append(f"- 原始列數: {report.get('raw_row_count', 0)}")
    if "document_count" in report:
        lines.append(f"- 文件數: {report.get('document_count', 0)}")
        lines.append(f"- 錯誤數: {report.get('error_count', 0)}")
    diagnostics = report.get("contract_diagnostics") or {}
    if diagnostics:
        lines.append(f"- 資料列容器: {diagnostics.get('row_container') or '-'}")
        lines.append(f"- 轉換比例: {diagnostics.get('conversion_ratio', 0)}")
        field_coverage = diagnostics.get("field_coverage") or {}
        if field_coverage:
            lines.append(
                "- 欄位覆蓋: "
                + ", ".join(f"{key}={value}" for key, value in field_coverage.items())
            )
    if report.get("remediation"):
        lines.append(f"- 修復建議: {report['remediation']}")
    if report.get("smoke_command"):
        lines.append(f"- 驗證指令: {report['smoke_command']}")
    return "\n".join(lines)


def _yes_no(value: object) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    return str(value if value is not None else "-")


def smoke_exit_code(report: dict[str, Any], *, strict: bool = False) -> int:
    if report.get("ready"):
        return 0
    if strict:
        return 1
    return 0 if report.get("status") == "not_configured" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="檢查已設定的公司文件結構化 API 回應格式。"
    )
    parser.add_argument("--ticker", default=DEFAULT_TICKER, help="要查詢的股票代號。")
    parser.add_argument("--company-name", default=DEFAULT_COMPANY_NAME, help="要查詢的公司名稱。")
    parser.add_argument(
        "--document-type",
        dest="document_types",
        action="append",
        help="要查詢的文件類型，可重複指定。",
    )
    parser.add_argument("--limit", type=int, default=3, help="最多查詢的文件數。")
    parser.add_argument(
        "--sample-json",
        help="驗證本機 sample JSON 回應格式，不需要正式外部 API。",
    )
    parser.add_argument("--strict", action="store_true", help="未就緒時回傳非 0 結束碼。")
    parser.add_argument("--json", action="store_true", help="輸出 JSON，方便工具讀取。")
    args = parser.parse_args(argv)

    report = asyncio.run(
        structured_company_filing_smoke_report(
            ticker=args.ticker,
            company_name=args.company_name,
            document_types=args.document_types or list(DEFAULT_DOCUMENT_TYPES),
            limit=args.limit,
            sample_json_path=args.sample_json,
        )
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_structured_company_filing_smoke(report))
    return smoke_exit_code(report, strict=bool(args.strict))


if __name__ == "__main__":
    raise SystemExit(main())
