from __future__ import annotations

import argparse
import json

from app.services.external_deployment_env_gaps import (
    external_deployment_env_gap_report,
    format_external_deployment_env_gap_report,
    format_external_deployment_env_template,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report missing optional external deployment env keys."
    )
    parser.add_argument(
        "--strict-external",
        action="store_true",
        help="Use strict external upgrade audit scope before deriving env gaps.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero when any env gap is present.",
    )
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    output_group.add_argument(
        "--env-template",
        action="store_true",
        help="Print a safe .env template for the missing optional deployment settings.",
    )
    args = parser.parse_args(argv)

    report = external_deployment_env_gap_report(strict_external=args.strict_external)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    elif args.env_template:
        print(format_external_deployment_env_template(report))
    else:
        print(format_external_deployment_env_gap_report(report))
    return 1 if args.strict and report["status"] != "ready" else 0


if __name__ == "__main__":
    raise SystemExit(main())
