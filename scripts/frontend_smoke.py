from __future__ import annotations

import argparse

from app.services.frontend_smoke import (
    DEFAULT_API_ENDPOINTS,
    DEFAULT_REQUIRED_TEXT_MAX_TOP_PX,
    DEFAULT_REQUIRED_TEXT_SCOPE_SELECTOR,
    DEFAULT_VISUAL_TEXT_FRAGMENTS,
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
    parser.add_argument(
        "--required-text",
        action="append",
        default=None,
        help="Visible text fragment required before screenshot. Can be repeated.",
    )
    parser.add_argument(
        "--no-required-text",
        action="store_true",
        help="Do not require any specific visible text before screenshot.",
    )
    parser.add_argument(
        "--required-text-max-top-px",
        type=float,
        default=DEFAULT_REQUIRED_TEXT_MAX_TOP_PX,
        help=(
            "Maximum allowed top position for each required text fragment in the desktop "
            "viewport. Use --no-required-text-layout to disable."
        ),
    )
    parser.add_argument(
        "--no-required-text-layout",
        action="store_true",
        help="Do not enforce a maximum viewport position for required text.",
    )
    parser.add_argument(
        "--required-text-scope-selector",
        default=DEFAULT_REQUIRED_TEXT_SCOPE_SELECTOR,
        help=(
            "CSS selector that scopes required text checks. The default requires the "
            "operator marker inside the next-action decision card."
        ),
    )
    parser.add_argument(
        "--no-required-text-scope",
        action="store_true",
        help="Search the whole page body for required text instead of a scoped component.",
    )
    parser.add_argument(
        "--skip-runtime-identity",
        action="store_true",
        help="Skip API and Streamlit runtime commit comparison.",
    )
    parser.add_argument(
        "--expected-api-commit",
        default=None,
        help="Expected API runtime git commit. Defaults to the current working tree commit.",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-check timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)
    if args.no_required_text:
        required_text_fragments = ()
    elif args.required_text is None:
        required_text_fragments = DEFAULT_VISUAL_TEXT_FRAGMENTS
    else:
        required_text_fragments = tuple(args.required_text)
    required_text_max_top_px = (
        None if args.no_required_text_layout else float(args.required_text_max_top_px)
    )
    required_text_scope_selector = (
        None if args.no_required_text_scope else args.required_text_scope_selector
    )

    report = run_frontend_smoke(
        streamlit_url=args.streamlit_url,
        api_url=args.api_url,
        api_endpoints=tuple(args.api_endpoint or DEFAULT_API_ENDPOINTS),
        screenshot_path=args.screenshot,
        skip_browser=args.skip_browser,
        required_text_fragments=required_text_fragments,
        required_text_max_top_px=required_text_max_top_px,
        required_text_scope_selector=required_text_scope_selector,
        check_runtime_identity=not args.skip_runtime_identity,
        expected_api_commit=args.expected_api_commit,
        timeout_seconds=args.timeout,
    )
    print(to_json(report) if args.json else format_frontend_smoke_report(report))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
