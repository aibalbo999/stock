from __future__ import annotations

import argparse
import json
import shlex
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.data_sources.company_filing_structured_api import (
    STRUCTURED_API_RECOMMENDED_PAID_PROVIDER,
    STRUCTURED_API_SAMPLE_CONTRACT_PATH,
    structured_api_document_rows,
    structured_api_document_type,
    structured_api_row_text,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8794
DEFAULT_PATH = "/filings"
DEFAULT_TICKER = "2330"
DEFAULT_COMPANY_NAME = "台積電"
DEFAULT_DOCUMENT_TYPES = ("investor_presentation",)


class LocalStructuredCompanyFilingHTTPServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        if self.allow_reuse_address and hasattr(socket, "SO_REUSEADDR"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if getattr(self, "allow_reuse_port", False) and hasattr(socket, "SO_REUSEPORT"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def load_fixture_payload(sample_json_path: str | Path) -> object:
    return json.loads(Path(sample_json_path).read_text(encoding="utf-8"))


def local_structured_company_filing_response(
    payload: object,
    *,
    ticker: str = "",
    company_name: str = "",
    document_types: list[str] | tuple[str, ...] | None = None,
    limit: int = 3,
    sample_json_path: str | Path | None = None,
) -> dict[str, Any]:
    rows = structured_api_document_rows(payload)
    requested_types = _normalize_document_types(document_types or ())
    matched_rows = [
        row
        for row in rows
        if _row_matches_company(row, ticker=ticker, company_name=company_name)
        and _row_matches_document_types(row, requested_types)
    ]
    capped_limit = max(1, int(limit))
    returned_rows = matched_rows[:capped_limit]
    return {
        "documents": returned_rows,
        "meta": {
            "mode": "local_structured_company_filing_fixture",
            "sample_json": str(sample_json_path) if sample_json_path else None,
            "raw_row_count": len(rows),
            "matched_row_count": len(matched_rows),
            "returned_row_count": len(returned_rows),
            "ticker": ticker,
            "company_name": company_name,
            "document_types": list(requested_types),
            "limit": capped_limit,
        },
    }


def local_fixture_env_lines(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    path: str = DEFAULT_PATH,
) -> list[str]:
    endpoint = f"http://{host}:{int(port)}{_normalized_api_path(path)}"
    return [
        "export COMPANY_FILING_STRUCTURED_API_PROVIDER=custom",
        f"export COMPANY_FILING_STRUCTURED_API_URL={shlex.quote(endpoint)}",
        "unset COMPANY_FILING_STRUCTURED_API_TOKEN",
    ]


def local_fixture_smoke_command(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    path: str = DEFAULT_PATH,
) -> str:
    endpoint = f"http://{host}:{int(port)}{_normalized_api_path(path)}"
    return (
        "COMPANY_FILING_STRUCTURED_API_PROVIDER=custom "
        f"COMPANY_FILING_STRUCTURED_API_URL={shlex.quote(endpoint)} "
        ".venv/bin/python scripts/structured_company_filing_smoke.py "
        "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
    )


def local_fixture_provider_profile_smoke_command(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    path: str = DEFAULT_PATH,
    provider_profile: str = STRUCTURED_API_RECOMMENDED_PAID_PROVIDER,
) -> str:
    return (
        ".venv/bin/python scripts/structured_company_filing_fixture_smoke.py "
        f"--provider-profile {shlex.quote(provider_profile)} "
        f"--host {shlex.quote(host)} --port {int(port)} "
        f"--path {shlex.quote(_normalized_api_path(path))} "
        "--json --strict"
    )


def make_handler(
    *,
    sample_json_path: str | Path,
    api_path: str = DEFAULT_PATH,
    quiet: bool = False,
) -> type[BaseHTTPRequestHandler]:
    normalized_api_path = _normalized_api_path(api_path)
    sample_path = Path(sample_json_path)

    class LocalStructuredCompanyFilingHandler(BaseHTTPRequestHandler):
        server_version = "LocalStructuredCompanyFilingAPI/1.0"

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler hook
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "ready": True,
                        "mode": "local_structured_company_filing_fixture",
                        "sample_json": str(sample_path),
                        "api_path": normalized_api_path,
                    },
                )
                return
            if parsed.path != normalized_api_path:
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    {
                        "status": "not_found",
                        "ready": False,
                        "api_path": normalized_api_path,
                    },
                )
                return
            query = parse_qs(parsed.query, keep_blank_values=False)
            try:
                payload = load_fixture_payload(sample_path)
                response = local_structured_company_filing_response(
                    payload,
                    ticker=_first_query_value(query, "ticker"),
                    company_name=_first_query_value(query, "company_name"),
                    document_types=_query_document_types(query),
                    limit=_query_limit(query),
                    sample_json_path=sample_path,
                )
            except Exception as exc:  # pragma: no cover - exercised via integration smoke.
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "status": "failed",
                        "ready": False,
                        "error": str(exc),
                        "sample_json": str(sample_path),
                    },
                )
                return
            self._send_json(HTTPStatus.OK, response)

        def log_message(self, format: str, *args: object) -> None:
            if not quiet:
                super().log_message(format, *args)

        def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return LocalStructuredCompanyFilingHandler


def run_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    path: str = DEFAULT_PATH,
    sample_json_path: str | Path = STRUCTURED_API_SAMPLE_CONTRACT_PATH,
    quiet: bool = False,
) -> None:
    handler = make_handler(sample_json_path=sample_json_path, api_path=path, quiet=quiet)
    endpoint = f"http://{host}:{int(port)}{_normalized_api_path(path)}"
    server = LocalStructuredCompanyFilingHTTPServer((host, int(port)), handler)
    print(f"Local structured company filing API fixture listening at {endpoint}", flush=True)
    print("Use these env vars in another shell:", flush=True)
    for line in local_fixture_env_lines(host=host, port=port, path=path):
        print(line, flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _first_query_value(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key) or []
    return str(values[0]).strip() if values else ""


def _query_limit(query: dict[str, list[str]]) -> int:
    text = _first_query_value(query, "limit")
    if not text:
        return 3
    try:
        return max(1, int(text))
    except ValueError:
        return 3


def _query_document_types(query: dict[str, list[str]]) -> tuple[str, ...]:
    values = [*query.get("document_type", []), *query.get("document_types", [])]
    return _normalize_document_types(values)


def _normalize_document_types(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    document_types: list[str] = []
    for value in values:
        for part in str(value or "").split(","):
            document_type = part.strip()
            if document_type:
                document_types.append(document_type)
    return tuple(document_types)


def _row_matches_company(row: dict, *, ticker: str, company_name: str) -> bool:
    terms = [term.lower() for term in (ticker.strip(), company_name.strip()) if term.strip()]
    if not terms:
        return True
    haystack = json.dumps(row, ensure_ascii=False, sort_keys=True).lower()
    return any(term in haystack for term in terms)


def _row_matches_document_types(row: dict, document_types: tuple[str, ...]) -> bool:
    if not document_types:
        return True
    return _row_document_type(row) in set(document_types)


def _row_document_type(row: dict) -> str:
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
    return structured_api_document_type(row, title=title, text=text, url=url or None)


def _normalized_api_path(path: str) -> str:
    normalized = "/" + str(path or DEFAULT_PATH).strip().strip("/")
    return normalized if normalized != "/" else DEFAULT_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Serve or render a local structured company filing API fixture."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind.")
    parser.add_argument("--path", default=DEFAULT_PATH, help="API path to serve.")
    parser.add_argument(
        "--sample-json",
        default=str(STRUCTURED_API_SAMPLE_CONTRACT_PATH),
        help="Sample JSON payload shaped as documents/data/results rows.",
    )
    parser.add_argument("--ticker", default=DEFAULT_TICKER, help="Ticker for --once mode.")
    parser.add_argument("--company-name", default=DEFAULT_COMPANY_NAME, help="Company for --once.")
    parser.add_argument(
        "--document-type",
        dest="document_types",
        action="append",
        help="Requested document type for --once mode. Can be repeated.",
    )
    parser.add_argument("--limit", type=int, default=3, help="Maximum documents for --once mode.")
    parser.add_argument("--once", action="store_true", help="Print one fixture response and exit.")
    parser.add_argument("--print-env", action="store_true", help="Print local env exports and exit.")
    parser.add_argument("--quiet", action="store_true", help="Suppress HTTP request logs.")
    parser.add_argument("--json", action="store_true", help="搭配 --once 輸出 JSON，方便工具讀取。")
    args = parser.parse_args(argv)

    if args.print_env:
        print("\n".join(local_fixture_env_lines(host=args.host, port=args.port, path=args.path)))
        print(local_fixture_smoke_command(host=args.host, port=args.port, path=args.path))
        print(
            local_fixture_provider_profile_smoke_command(
                host=args.host,
                port=args.port,
                path=args.path,
            )
        )
        return 0

    if args.once:
        payload = load_fixture_payload(args.sample_json)
        response = local_structured_company_filing_response(
            payload,
            ticker=args.ticker,
            company_name=args.company_name,
            document_types=args.document_types or list(DEFAULT_DOCUMENT_TYPES),
            limit=args.limit,
            sample_json_path=args.sample_json,
        )
        if args.json:
            print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            meta = response["meta"]
            print(
                "Local structured company filing fixture: "
                f"{meta['returned_row_count']}/{meta['matched_row_count']} rows"
            )
        return 0

    try:
        run_server(
            host=args.host,
            port=args.port,
            path=args.path,
            sample_json_path=args.sample_json,
            quiet=bool(args.quiet),
        )
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
