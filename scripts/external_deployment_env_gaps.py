from __future__ import annotations

import argparse
import json
from typing import Any

from app.services.service_status import service_status
from app.services.upgrade_audit import audit_upgrade_capabilities
from app.ui.external_deployment_env_keys import external_deployment_env_key_rows


def external_deployment_env_gap_report(
    *,
    upgrade_audit: dict[str, Any] | None = None,
    service_snapshot: dict[str, Any] | None = None,
    strict_external: bool = False,
) -> dict[str, Any]:
    audit = (
        audit_upgrade_capabilities(strict_external=strict_external)
        if upgrade_audit is None
        else upgrade_audit
    )
    snapshot = service_status() if service_snapshot is None else service_snapshot
    rows = external_deployment_env_key_rows(audit, snapshot)
    missing_count = sum(1 for row in rows if row.get("狀態") == "缺少")
    recommended_count = sum(1 for row in rows if row.get("狀態") == "建議")
    manual_secret_count = sum(1 for row in rows if row.get("處理類型") == "需人工密鑰")
    local_action_count = sum(1 for row in rows if row.get("處理類型") == "本機可套用")
    return {
        "status": "action_required" if rows else "ready",
        "gap_count": len(rows),
        "missing_count": missing_count,
        "recommended_count": recommended_count,
        "manual_secret_count": manual_secret_count,
        "local_action_count": local_action_count,
        "rows": rows,
        "local_start_command": ".venv/bin/python scripts/start_system.py --start-dependencies",
        "local_unlocker_start_command": (
            ".venv/bin/python scripts/start_system.py --start-dependencies --prefer-unlocker"
        ),
        "strict_external": bool(strict_external),
    }


def format_external_deployment_env_gap_report(report: dict[str, Any]) -> str:
    lines = [
        (
            f"External deployment env gaps: {report['status']} "
            f"({report['gap_count']} gaps; missing={report['missing_count']}; "
            f"recommended={report['recommended_count']})"
        )
    ]
    if not report.get("rows"):
        lines.append("No external deployment env gaps detected.")
        return "\n".join(lines)
    for row in report["rows"]:
        lines.append(
            f"- [{row['狀態']}] {row['優先級']} {row['能力']} :: "
            f"{row['設定鍵']} ({row['處理類型']})"
        )
        lines.append(f"  value: {row['建議值']}")
        lines.append(f"  action: {row['維護動作']}")
        lines.append(f"  verify: {row['驗證指令']}")
    return "\n".join(lines)


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
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    report = external_deployment_env_gap_report(strict_external=args.strict_external)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_external_deployment_env_gap_report(report))
    return 1 if args.strict and report["status"] != "ready" else 0


if __name__ == "__main__":
    raise SystemExit(main())
