from __future__ import annotations

import argparse

from app.services.frontend_smoke import (
    DEFAULT_API_ENDPOINTS,
    format_frontend_smoke_report,
    run_frontend_smoke,
    to_json,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run HTTP and optional Playwright frontend smoke checks.")
    parser.add_argument("--streamlit-url", default="http://127.0.0.1:8501")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--api-endpoint",
        action="append",
        default=None,
        help=(
            "API endpoint to check. Can be repeated; defaults to /services/status "
            "and /services/external-deployment/env-check."
        ),
    )
    parser.add_argument(
        "--screenshot",
        default="artifacts/frontend_smoke/streamlit.png",
        help="Screenshot output path when Playwright is available.",
    )
    parser.add_argument("--skip-browser", action="store_true", help="Skip Playwright visual smoke.")
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-check timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    report = run_frontend_smoke(
        streamlit_url=args.streamlit_url,
        api_url=args.api_url,
        api_endpoints=tuple(args.api_endpoint or DEFAULT_API_ENDPOINTS),
        screenshot_path=args.screenshot,
        skip_browser=args.skip_browser,
        timeout_seconds=args.timeout,
    )
    print(to_json(report) if args.json else format_frontend_smoke_report(report))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
