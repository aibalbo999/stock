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
        description="Smoke test FastAPI/Celery background task submission with a no-op data operation."
    )
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--operation", default=DEFAULT_OPERATION)
    parser.add_argument("--ticker", action="append", default=None)
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Submit a no-op smoke payload to POST /tasks/data-operation.",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Poll GET /tasks/{task_id} until the smoke task finishes or times out.",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--strict", action="store_true", help="Return non-zero on caution.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    report = run_task_submission_smoke(
        api_url=args.api_url,
        operation=args.operation,
        tickers=tuple(args.ticker or DEFAULT_TICKERS),
        submit=bool(args.submit),
        wait=bool(args.wait),
        timeout_seconds=float(args.timeout),
        poll_interval_seconds=float(args.poll_interval),
    )
    print(to_json(report) if args.json else format_task_submission_smoke(report))
    return smoke_exit_code(report, strict=bool(args.strict))


if __name__ == "__main__":
    raise SystemExit(main())
