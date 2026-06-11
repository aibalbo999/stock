from __future__ import annotations

import argparse
import json

from app.services.external_deployment_env_gaps import (
    external_deployment_env_gap_report,
    external_deployment_env_check_status_report,
    format_external_deployment_env_gap_report,
    format_external_deployment_env_check_status_report,
    format_external_deployment_env_check_report,
    format_external_deployment_env_template,
    external_deployment_env_check_report,
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
    parser.add_argument("--json", action="store_true", help="輸出 JSON，方便工具讀取。")
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--env-template",
        action="store_true",
        help="Print a safe .env template for the missing optional deployment settings.",
    )
    output_group.add_argument(
        "--env-check",
        action="store_true",
        help="Compare the recommended external deployment env keys with an env file.",
    )
    parser.add_argument(
        "--env-template-target",
        choices=("host", "compose"),
        default="host",
        help="Choose host-only localhost values or docker-compose service DNS values.",
    )
    parser.add_argument(
        "--env-check-target",
        choices=("host", "compose", "all"),
        default=None,
        help=(
            "Choose host, compose, or both targets for --env-check. Defaults to "
            "--env-template-target for backward compatibility."
        ),
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Env file to inspect when --env-check is used.",
    )
    parser.add_argument(
        "--include-process-env",
        action="store_true",
        help="Let process environment values override --env-file during --env-check.",
    )
    args = parser.parse_args(argv)
    if args.json and args.env_template:
        parser.error("--json cannot be combined with --env-template.")

    env_check_target = args.env_check_target or args.env_template_target
    if args.env_check and env_check_target == "all":
        check = external_deployment_env_check_status_report(
            target="all",
            env_file=args.env_file,
            include_process_env=args.include_process_env,
            strict_external=args.strict_external,
        )
        if args.json:
            print(json.dumps(check, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(format_external_deployment_env_check_status_report(check))
        return 1 if args.strict and check["status"] != "ready" else 0

    report = external_deployment_env_gap_report(strict_external=args.strict_external)
    strict_status = report["status"]
    if args.env_template:
        print(format_external_deployment_env_template(report, target=args.env_template_target))
    elif args.env_check:
        check = external_deployment_env_check_report(
            report,
            target=env_check_target,
            env_file=args.env_file,
            include_process_env=args.include_process_env,
        )
        strict_status = check["status"]
        if args.json:
            print(json.dumps(check, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(format_external_deployment_env_check_report(check))
    elif args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_external_deployment_env_gap_report(report))
    return 1 if args.strict and strict_status != "ready" else 0


if __name__ == "__main__":
    raise SystemExit(main())
