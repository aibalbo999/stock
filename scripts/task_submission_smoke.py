from __future__ import annotations

import argparse

from app.services.task_submission_smoke import (
    DEFAULT_API_URL,
    DEFAULT_OPERATION,
    DEFAULT_TICKERS,
    format_task_submission_smoke,
    run_task_submission_smoke,
    smoke_exit_code,
    to_json,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check background task submission with a safe no-op data operation."
    )
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--operation", default=DEFAULT_OPERATION)
    parser.add_argument("--ticker", action="append", default=None)
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Submit a safe no-op check payload to POST /tasks/data-operation.",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Poll GET /tasks/{task_id} until the check task finishes or times out.",
    )
    parser.add_argument(
        "--skip-processing-ready",
        action="store_true",
        help=(
            "Do not require Celery worker processing readiness. Useful for diagnostics "
            "running inside a single Celery worker that only need to verify enqueue."
        ),
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument(
        "--skip-runtime-identity",
        action="store_true",
        help="Skip API runtime commit comparison.",
    )
    parser.add_argument(
        "--expected-api-commit",
        default=None,
        help="Expected API runtime git commit. Defaults to the current working tree commit.",
    )
    parser.add_argument("--strict", action="store_true", help="Return non-zero on caution.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    report = run_task_submission_smoke(
        api_url=args.api_url,
        operation=args.operation,
        tickers=tuple(args.ticker or DEFAULT_TICKERS),
        submit=bool(args.submit),
        wait=bool(args.wait),
        check_processing_ready=not bool(args.skip_processing_ready),
        timeout_seconds=float(args.timeout),
        poll_interval_seconds=float(args.poll_interval),
        check_runtime_identity=not args.skip_runtime_identity,
        expected_api_commit=args.expected_api_commit,
    )
    print(to_json(report) if args.json else format_task_submission_smoke(report))
    return smoke_exit_code(report, strict=bool(args.strict))


if __name__ == "__main__":
    raise SystemExit(main())
