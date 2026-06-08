from __future__ import annotations

from app.services.external_deployment_env_gaps import (
    external_deployment_env_check_report as _external_deployment_env_check_report,
    external_deployment_env_gap_report as _external_deployment_env_gap_report,
    external_deployment_env_key_rows as _external_deployment_env_key_rows,
    external_deployment_env_resolution_rows as _external_deployment_env_resolution_rows,
)

ENV_CHECK_TARGETS = ("host", "compose")


def external_deployment_env_key_rows(
    upgrade_audit: dict,
    service_snapshot: dict | None = None,
) -> list[dict]:
    return _external_deployment_env_key_rows(upgrade_audit, service_snapshot)


def external_deployment_env_resolution_rows(
    upgrade_audit: dict,
    service_snapshot: dict | None = None,
) -> list[dict]:
    return _external_deployment_env_resolution_rows(upgrade_audit, service_snapshot)


def external_deployment_env_check_summary_rows(
    upgrade_audit: dict,
    service_snapshot: dict | None = None,
    *,
    env_file: str = ".env",
) -> list[dict]:
    gap_report = _external_deployment_env_gap_report(
        upgrade_audit=upgrade_audit,
        service_snapshot=service_snapshot or {},
    )
    return [
        _external_deployment_env_check_summary_row(
            _external_deployment_env_check_report(
                gap_report,
                target=target,
                env_file=env_file,
            )
        )
        for target in ENV_CHECK_TARGETS
    ]


def external_deployment_env_check_detail_rows(
    upgrade_audit: dict,
    service_snapshot: dict | None = None,
    *,
    target: str = "host",
    env_file: str = ".env",
) -> list[dict]:
    gap_report = _external_deployment_env_gap_report(
        upgrade_audit=upgrade_audit,
        service_snapshot=service_snapshot or {},
    )
    check = _external_deployment_env_check_report(
        gap_report,
        target=target,
        env_file=env_file,
    )
    return [
        {
            "目標": check["target"],
            "設定鍵": row["env_key"],
            "狀態": _external_deployment_env_check_status_label(str(row["status"])),
            "建議值": row["expected_value"],
            "目前值": row["current_value"],
            "類型": "密鑰" if row.get("secret") else "一般",
            "能力": row.get("capabilities") or "-",
            "下一步": row.get("action") or "-",
        }
        for row in check.get("rows") or []
        if isinstance(row, dict)
    ]


def _external_deployment_env_check_summary_row(check: dict) -> dict:
    return {
        "目標": check.get("target") or "-",
        "狀態": _external_deployment_env_check_status_label(str(check.get("status") or "")),
        ".env": "存在" if check.get("env_file_exists") else "未找到",
        "檢查鍵數": int(check.get("checked_count") or 0),
        "已設定": int(check.get("set_count") or 0),
        "缺少": int(check.get("missing_count") or 0),
        "值不同": int(check.get("different_count") or 0),
        "檢查指令": _external_deployment_env_check_command(
            str(check.get("target") or "host"),
            str(check.get("env_file") or ".env"),
        ),
    }


def _external_deployment_env_check_command(target: str, env_file: str) -> str:
    command = f".venv/bin/python scripts/external_deployment_env_gaps.py --env-check --env-file {env_file}"
    if target == "compose":
        return f"{command} --env-template-target compose"
    return command


def _external_deployment_env_check_status_label(status: str) -> str:
    return {
        "ready": "就緒",
        "matches": "就緒",
        "set": "就緒",
        "action_required": "需補設定",
        "missing": "需補設定",
        "review_required": "需確認",
        "different": "需確認",
    }.get(status, status or "-")
