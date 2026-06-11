from __future__ import annotations

from typing import Any

from app.services.external_deployment_env_actions import (
    external_env_key_actions,
    external_env_key_next_step,
    external_env_maintenance_action,
    external_env_resolution_type,
    external_env_summary,
)
from app.services.external_deployment_env_catalog import (
    EXTERNAL_ENV_CHECK_TARGETS,
    external_env_compose_recommended_value,
    external_env_key_hint,
)
from app.services.external_deployment_env_items import (
    service_snapshot_external_env_items as build_service_snapshot_external_env_items,
)
from app.services.external_deployment_env_templates import (
    external_deployment_env_check_report as external_deployment_env_check_report,
    format_external_deployment_env_template as format_external_deployment_env_template,
    format_external_deployment_env_check_report as format_external_deployment_env_check_report,
)
from app.services.external_deployment_env_resolution import (
    external_deployment_env_resolution_rows_from_key_rows as build_external_deployment_env_resolution_rows,
)
from app.services.external_deployment_readiness import (
    external_deployment_command_summary,
    external_deployment_item_ready,
    external_deployment_readiness_items,
    external_deployment_readiness_metadata,
    external_smoke_commands_from_payload,
)

EXTERNAL_ENV_RESOLUTION_CONTRACT_COLUMNS = ("處理策略", "處理類型", "維護動作")


def external_deployment_env_gap_report(
    *,
    upgrade_audit: dict[str, Any] | None = None,
    service_snapshot: dict[str, Any] | None = None,
    strict_external: bool = False,
) -> dict[str, Any]:
    from app.services.service_status import service_status
    from app.services.upgrade_audit import audit_upgrade_capabilities

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
    resolution_rows = external_deployment_env_resolution_rows_from_key_rows(rows)
    return {
        "status": "action_required" if rows else "ready",
        "gap_count": len(rows),
        "missing_count": missing_count,
        "recommended_count": recommended_count,
        "manual_secret_count": manual_secret_count,
        "local_action_count": local_action_count,
        "capability_gap_count": len(resolution_rows),
        "rows": rows,
        "resolution_rows": resolution_rows,
        "local_start_command": ".venv/bin/python scripts/start_system.py --start-dependencies",
        "local_unlocker_start_command": (
            ".venv/bin/python scripts/start_system.py --start-dependencies --prefer-unlocker"
        ),
        "strict_external": bool(strict_external),
    }


def external_deployment_env_check_status_report(
    *,
    target: str = "all",
    env_file: str = ".env",
    include_process_env: bool = False,
    strict_external: bool = False,
    upgrade_audit: dict[str, Any] | None = None,
    service_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    targets = _external_env_check_targets(target)
    gap_report = external_deployment_env_gap_report(
        upgrade_audit=upgrade_audit,
        service_snapshot=service_snapshot,
        strict_external=strict_external,
    )
    checks = {
        check_target: external_deployment_env_check_report(
            gap_report,
            target=check_target,
            env_file=env_file,
            include_process_env=include_process_env,
        )
        for check_target in targets
    }
    return {
        "status": _external_env_check_status_from_reports(list(checks.values())),
        "target": "all" if len(targets) > 1 else targets[0],
        "targets": targets,
        "strict_external": bool(strict_external),
        "include_process_env": bool(include_process_env),
        "env_file": env_file,
        "gap_status": gap_report.get("status"),
        "gap_count": gap_report.get("gap_count", 0),
        "checks": checks,
    }


def format_external_deployment_env_check_status_report(report: dict[str, Any]) -> str:
    checks = report.get("checks") or {}
    targets = report.get("targets") or sorted(str(target) for target in checks)
    lines = [
        (
            f"外部部署環境檢查: {report['status']} "
            f"(目標={report.get('target', 'all')}；缺口={report.get('gap_count', 0)})"
        )
    ]
    if report.get("env_file"):
        lines.append(f"環境檔: {report['env_file']}")
    if not checks:
        lines.append("沒有外部部署環境檢查明細。")
        return "\n".join(lines)
    for target in targets:
        check = checks.get(str(target)) or {}
        lines.append(
            (
                f"[{target}] {check.get('status', 'unknown')} "
                f"(已檢查={check.get('checked_count', 0)}；"
                f"缺少={check.get('missing_count', 0)}；"
                f"不同={check.get('different_count', 0)})"
            )
        )
        if check.get("env_file"):
            exists = "存在" if check.get("env_file_exists") else "缺少"
            lines.append(f"  環境檔: {check['env_file']} ({exists})")
        for row in check.get("rows") or []:
            lines.append(
                f"  - [{row['status']}] {row['env_key']} :: "
                f"建議={row['expected_value']} 目前={row['current_value']}"
            )
            if row["action"] != "-":
                lines.append(f"    動作: {row['action']}")
    return "\n".join(lines)


def format_external_deployment_env_gap_report(report: dict[str, Any]) -> str:
    lines = [
        (
            f"外部部署環境缺口: {report['status']} "
            f"({report['gap_count']} 缺口；缺少={report['missing_count']}；"
            f"建議值={report['recommended_count']})"
        )
    ]
    if not report.get("rows"):
        lines.append("未偵測到外部部署環境缺口。")
        return "\n".join(lines)
    if report.get("resolution_rows"):
        lines.append("處理計畫:")
        for row in report["resolution_rows"]:
            lines.append(
                f"- {row['優先級']} {row['能力']} :: {row['處理策略']} "
                f"(缺口={row['缺口數']}；本機={row['本機可套用']}；"
                f"人工={row['需人工處理']})"
            )
            lines.append(f"  動作: {row['建議動作']}")
            lines.append(f"  設定鍵: {row['設定鍵']}")
            lines.append(f"  驗證: {row['驗證指令']}")
    for row in report["rows"]:
        lines.append(
            f"- [{row['狀態']}] {row['優先級']} {row['能力']} :: "
            f"{row['設定鍵']} ({row['處理類型']})"
        )
        lines.append(f"  建議值: {row['建議值']}")
        lines.append(f"  動作: {row['維護動作']}")
        lines.append(f"  驗證: {row['驗證指令']}")
    return "\n".join(lines)


def _external_env_check_targets(target: str) -> list[str]:
    normalized = str(target or "all").strip().lower()
    if normalized == "all":
        return list(EXTERNAL_ENV_CHECK_TARGETS)
    if normalized in EXTERNAL_ENV_CHECK_TARGETS:
        return [normalized]
    allowed = ", ".join(("all", *EXTERNAL_ENV_CHECK_TARGETS))
    raise ValueError(f"Unsupported external env check target: {target!r}. Use one of: {allowed}.")


def _external_env_check_status_from_reports(reports: list[dict[str, Any]]) -> str:
    statuses = [str(report.get("status") or "ready") for report in reports]
    if "action_required" in statuses:
        return "action_required"
    if "review_required" in statuses:
        return "review_required"
    return "ready"


def external_deployment_env_key_rows(
    upgrade_audit: dict,
    service_snapshot: dict | None = None,
) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for item in [
        *external_deployment_readiness_items(upgrade_audit),
        *_service_snapshot_external_env_items(service_snapshot or {}),
    ]:
        if external_deployment_item_ready(item):
            continue
        metadata = external_deployment_readiness_metadata(item)
        env_summary = external_env_summary(item)
        verify_command = external_deployment_command_summary(
            external_smoke_commands_from_payload(item)
        )
        capability = str(item.get("capability") or "")
        source = str(item.get("_env_source") or "upgrade audit")
        for env_key, status in external_env_key_actions(item, env_summary):
            key = (capability, env_key, status)
            if key in seen:
                continue
            seen.add(key)
            hint = external_env_key_hint(env_key)
            recommended_value = (
                env_summary["recommended"].get(env_key) or hint.get("default") or "-"
            )
            compose_recommended_value = external_env_compose_recommended_value(
                env_key,
                recommended_value,
                env_summary["compose_recommended"],
            )
            resolution_type = external_env_resolution_type(item, env_key, recommended_value)
            rows.append(
                {
                    "優先級": metadata["priority"],
                    "能力": item.get("label") or item.get("capability") or "-",
                    "設定鍵": env_key,
                    "狀態": status,
                    "目前": "未設定" if status == "缺少" else "建議確認",
                    "建議值": recommended_value,
                    "Compose 建議值": compose_recommended_value,
                    "用途": hint.get("scope") or metadata["impact"],
                    "來源": source,
                    "處理類型": resolution_type,
                    "維護動作": external_env_maintenance_action(
                        item,
                        env_key,
                        recommended_value,
                        resolution_type,
                    ),
                    "下一步": external_env_key_next_step(item, env_key, status),
                    "驗證指令": verify_command,
                }
            )
    return sorted(rows, key=_external_env_key_row_sort_key)


def external_deployment_env_resolution_rows(
    upgrade_audit: dict,
    service_snapshot: dict | None = None,
) -> list[dict]:
    return external_deployment_env_resolution_rows_from_key_rows(
        external_deployment_env_key_rows(upgrade_audit, service_snapshot)
    )


def external_deployment_env_resolution_rows_from_key_rows(rows: list[dict]) -> list[dict]:
    return build_external_deployment_env_resolution_rows(rows)


def _service_snapshot_external_env_items(service_snapshot: dict) -> list[dict]:
    return build_service_snapshot_external_env_items(service_snapshot)


def _external_env_key_row_sort_key(row: dict) -> tuple[int, int, str, str]:
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    status_order = {"缺少": 0, "建議": 1}
    return (
        priority_order.get(str(row.get("優先級") or ""), 4),
        status_order.get(str(row.get("狀態") or ""), 2),
        str(row.get("能力") or ""),
        str(row.get("設定鍵") or ""),
    )
