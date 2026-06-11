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
        description="檢查背景任務是否能送出到資料操作端點。"
    )
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="要檢查的 API base URL。")
    parser.add_argument("--operation", default=DEFAULT_OPERATION, help="要送出的資料操作類型。")
    parser.add_argument("--ticker", action="append", default=None, help="要檢查的股票代號，可重複指定。")
    parser.add_argument(
        "--submit",
        action="store_true",
        help="送出安全檢查用的股價刷新任務。",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="輪詢任務狀態，直到檢查任務完成或逾時。",
    )
    parser.add_argument(
        "--skip-processing-ready",
        action="store_true",
        help=(
            "只檢查送出，不要求背景執行器完成任務。"
            "適合在背景執行器內部自我檢查時使用。"
        ),
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="等待任務完成的秒數上限。")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="輪詢任務狀態的間隔秒數。")
    parser.add_argument(
        "--skip-runtime-identity",
        action="store_true",
        help="略過 API 版本比對。",
    )
    parser.add_argument(
        "--expected-api-commit",
        default=None,
        help="預期的 API git commit；預設使用目前工作目錄 commit。",
    )
    parser.add_argument("--strict", action="store_true", help="警示狀態時回傳非 0 結束碼。")
    parser.add_argument("--json", action="store_true", help="輸出 JSON，方便工具讀取。")
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
