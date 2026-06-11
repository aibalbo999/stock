from __future__ import annotations

import argparse
import json

from app.services.llm_quota_env_audit import (
    format_llm_quota_env_audit,
    llm_quota_env_audit,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit LLM quota request budgets in an env file."
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Env file to inspect or update.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Update tracked public Free Tier request budgets in the env file.",
    )
    parser.add_argument("--json", action="store_true", help="輸出 JSON，方便工具讀取。")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero when drift, invalid values, or a missing env key is detected.",
    )
    args = parser.parse_args(argv)

    report = llm_quota_env_audit(
        env_file=args.env_file,
        apply_reference_budgets=args.apply,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_llm_quota_env_audit(report))
    return 1 if args.strict and not report.get("ready") else 0


if __name__ == "__main__":
    raise SystemExit(main())
