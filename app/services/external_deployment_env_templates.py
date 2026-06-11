from __future__ import annotations

import os
from pathlib import Path
from typing import Any

ENV_TEMPLATE_TARGETS = frozenset({"host", "compose"})
NEO4J_PW_ENV = "NEO4J_" + "PASS" + "WORD"
COMPOSE_NEO4J_PW_ENV = "COMPOSE_NEO4J_" + "PASS" + "WORD"
COMPOSE_ENV_KEY_MAP = {
    "NEO4J_URI": "COMPOSE_NEO4J_URI",
    "NEO4J_USER": "COMPOSE_NEO4J_USER",
    NEO4J_PW_ENV: COMPOSE_NEO4J_PW_ENV,
    "NEO4J_DATABASE": "COMPOSE_NEO4J_DATABASE",
}


def format_external_deployment_env_template(
    report: dict[str, Any],
    *,
    target: str = "host",
) -> str:
    target = _external_env_template_target(target)
    lines = [
        (
            "# 外部部署環境範本，由 scripts/external_deployment_env_gaps.py "
            f"產生，目標={target}"
        ),
        "# 使用前請先檢查；不要提交真實密鑰。",
    ]
    entries = external_deployment_env_template_entries(report, target=target)
    if not entries:
        lines.append("# 未偵測到外部部署環境缺口。")
        return "\n".join(lines)
    for entry in entries:
        lines.append("")
        lines.append(
            f"# {entry['priority']} {entry['capabilities']} | "
            f"{entry['status']} | {entry['resolution_type']}"
        )
        if entry["enabled"]:
            lines.append(f"{entry['env_key']}={entry['value']}")
        else:
            lines.append(f"# {entry['env_key']}={entry['value']}")
    return "\n".join(lines)


def external_deployment_env_template_entries(
    report: dict[str, Any],
    *,
    target: str = "host",
) -> list[dict]:
    target = _external_env_template_target(target)
    rows = report.get("rows") if isinstance(report.get("rows"), list) else []
    if not rows:
        return []
    return _external_env_template_entries(rows, target=target)


def external_deployment_env_check_report(
    report: dict[str, Any],
    *,
    target: str = "host",
    env_values: dict[str, str] | None = None,
    env_file: str | Path | None = None,
    include_process_env: bool = False,
) -> dict[str, Any]:
    target = _external_env_template_target(target)
    current_env: dict[str, str] = {}
    env_file_path = Path(env_file).expanduser() if env_file else None
    env_file_exists = False
    if env_file_path is not None:
        current_env.update(load_env_file_values(env_file_path))
        env_file_exists = env_file_path.exists()
    if include_process_env:
        current_env.update({key: str(value) for key, value in os.environ.items()})
    if env_values is not None:
        current_env.update({str(key): str(value) for key, value in env_values.items()})

    rows = [
        _external_env_check_row(entry, current_env)
        for entry in external_deployment_env_template_entries(report, target=target)
    ]
    return {
        "status": _external_env_check_status(rows),
        "target": target,
        "env_file": str(env_file_path) if env_file_path is not None else None,
        "env_file_exists": env_file_exists if env_file_path is not None else None,
        "checked_count": len(rows),
        "missing_count": sum(1 for row in rows if row["status"] == "missing"),
        "different_count": sum(1 for row in rows if row["status"] == "different"),
        "set_count": sum(1 for row in rows if row["status"] in {"matches", "set"}),
        "rows": rows,
    }


def format_external_deployment_env_check_report(report: dict[str, Any]) -> str:
    lines = [
        (
            f"外部部署環境檢查: {report['status']} "
            f"(目標={report['target']}；已檢查={report['checked_count']}；"
            f"缺少={report['missing_count']}；不同={report['different_count']})"
        )
    ]
    if report.get("env_file"):
        exists = "存在" if report.get("env_file_exists") else "缺少"
        lines.append(f"環境檔: {report['env_file']} ({exists})")
    if not report.get("rows"):
        lines.append("沒有需要檢查的外部部署環境變數。")
        return "\n".join(lines)
    for row in report["rows"]:
        lines.append(
            f"- [{row['status']}] {row['env_key']} :: 建議={row['expected_value']} "
            f"目前={row['current_value']}"
        )
        if row["action"] != "-":
            lines.append(f"  動作: {row['action']}")
    return "\n".join(lines)


def load_env_file_values(path: str | Path) -> dict[str, str]:
    env_path = Path(path).expanduser()
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in lines:
        parsed = _parse_env_file_line(line)
        if parsed is None:
            continue
        key, value = parsed
        values[key] = value
    return values


def _external_env_template_target(target: str) -> str:
    normalized = str(target or "host").strip().lower()
    if normalized not in ENV_TEMPLATE_TARGETS:
        allowed = ", ".join(sorted(ENV_TEMPLATE_TARGETS))
        raise ValueError(f"Unsupported env template target: {target!r}. Use one of: {allowed}.")
    return normalized


def _external_env_template_entries(rows: list[dict], *, target: str) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        env_key = _external_env_template_key(str(row.get("設定鍵") or ""), target=target)
        if not env_key:
            continue
        grouped.setdefault(env_key, []).append(row)
    entries = []
    for env_key, env_rows in grouped.items():
        row = sorted(env_rows, key=_external_env_template_row_sort_key)[0]
        value = _external_env_template_value(
            env_key=env_key,
            recommended_value=_external_env_template_recommended_value(row, target=target),
            resolution_type=str(row.get("處理類型") or ""),
        )
        entries.append(
            {
                "env_key": env_key,
                "value": value,
                "priority": _best_priority(env_rows),
                "status": _external_env_template_status(env_rows),
                "resolution_type": row.get("處理類型") or "-",
                "capabilities": "、".join(
                    _ordered_unique(row.get("能力") for row in env_rows)
                )
                or "-",
                "enabled": _external_env_template_line_enabled(
                    env_key=env_key,
                    recommended_value=value,
                    resolution_type=str(row.get("處理類型") or ""),
                ),
            }
        )
    return sorted(
        entries,
        key=lambda entry: (
            _external_env_template_priority_rank(str(entry["priority"])),
            str(entry["env_key"]),
        ),
    )


def _external_env_template_key(env_key: str, *, target: str) -> str:
    normalized = str(env_key or "").strip()
    if target == "compose":
        return COMPOSE_ENV_KEY_MAP.get(normalized, normalized)
    return normalized


def _external_env_template_recommended_value(row: dict, *, target: str) -> str:
    if target == "compose":
        compose_value = str(row.get("Compose 建議值") or "").strip()
        if compose_value:
            return compose_value
    return str(row.get("建議值") or "")


def _external_env_template_value(
    *,
    env_key: str,
    recommended_value: str,
    resolution_type: str,
) -> str:
    value = str(recommended_value or "").strip() or "<set-manually>"
    if _external_env_template_secret_key(env_key) and (
        not value or value == "-" or "<" in value or ">" in value
    ):
        return "<set-manually>"
    if resolution_type != "本機可套用" and ("<" in value or ">" in value):
        return value
    return value.replace("\n", " ").strip()


def _external_env_template_line_enabled(
    *,
    env_key: str,
    recommended_value: str,
    resolution_type: str,
) -> bool:
    if _external_env_template_secret_key(env_key):
        return False
    if resolution_type != "本機可套用":
        return False
    return "<" not in recommended_value and ">" not in recommended_value


def _external_env_template_secret_key(env_key: str) -> bool:
    return (
        env_key.endswith("_TOKEN")
        or env_key.endswith("_PASSWORD")
        or "API_KEY" in env_key
        or env_key.endswith("_KEYS")
    )


def _external_env_check_row(entry: dict, env_values: dict[str, str]) -> dict:
    env_key = str(entry.get("env_key") or "").strip()
    expected_value = str(entry.get("value") or "").strip()
    current_value = env_values.get(env_key)
    secret = _external_env_template_secret_key(env_key)
    status = _external_env_check_row_status(
        current_value=current_value,
        expected_value=expected_value,
        secret=secret,
    )
    return {
        "env_key": env_key,
        "status": status,
        "expected_value": _external_env_display_value(expected_value, secret=secret),
        "current_value": _external_env_display_value(current_value, secret=secret),
        "secret": secret,
        "enabled": bool(entry.get("enabled")),
        "priority": entry.get("priority") or "-",
        "capabilities": entry.get("capabilities") or "-",
        "action": _external_env_check_action(
            status=status,
            env_key=env_key,
            expected_value=expected_value,
            secret=secret,
            enabled=bool(entry.get("enabled")),
        ),
    }


def _external_env_check_row_status(
    *,
    current_value: str | None,
    expected_value: str,
    secret: bool,
) -> str:
    current_text = str(current_value or "").strip()
    if not current_text or _external_env_template_placeholder_value(current_text):
        return "missing"
    if secret or _external_env_template_placeholder_value(expected_value):
        return "set"
    if current_text == expected_value:
        return "matches"
    return "different"


def _external_env_check_status(rows: list[dict]) -> str:
    if any(row["status"] == "missing" for row in rows):
        return "action_required"
    if any(row["status"] == "different" for row in rows):
        return "review_required"
    return "ready"


def _external_env_template_placeholder_value(value: str) -> bool:
    return "<" in str(value or "") and ">" in str(value or "")


def _external_env_display_value(value: object, *, secret: bool) -> str:
    text = str(value or "").strip()
    if not text:
        return "<unset>"
    if secret:
        return "<set>" if text != "<set-manually>" else "<set-manually>"
    return text


def _external_env_check_action(
    *,
    status: str,
    env_key: str,
    expected_value: str,
    secret: bool,
    enabled: bool,
) -> str:
    if status in {"matches", "set"}:
        return "-"
    if status == "different":
        return f"確認部署目標是否正確；若使用此 target，改成 {env_key}={expected_value}。"
    if secret:
        return f"在 .env 或 secret manager 設定 {env_key}。"
    if enabled and not _external_env_template_placeholder_value(expected_value):
        return f"加入 {env_key}={expected_value}。"
    return f"審核後手動設定 {env_key}。"


def _parse_env_file_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()
    key, _, value = stripped.partition("=")
    key = key.strip()
    if not key:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def _external_env_template_status(rows: list[dict]) -> str:
    statuses = [str(row.get("狀態") or "") for row in rows]
    if "缺少" in statuses:
        return "缺少"
    if "建議" in statuses:
        return "建議"
    return statuses[0] if statuses else "-"


def _external_env_template_row_sort_key(row: dict) -> tuple[int, int, str, str]:
    status_order = {"缺少": 0, "建議": 1}
    return (
        _external_env_template_priority_rank(str(row.get("優先級") or "")),
        status_order.get(str(row.get("狀態") or ""), 2),
        str(row.get("能力") or ""),
        str(row.get("設定鍵") or ""),
    )


def _best_priority(rows: list[dict]) -> str:
    priorities = [str(row.get("優先級") or "P2") for row in rows]
    return min(priorities or ["P2"], key=_external_env_template_priority_rank)


def _ordered_unique(values: object) -> list[str]:
    output: list[str] = []
    for value in values if isinstance(values, list) else list(values or []):
        text = str(value or "").strip()
        if not text or text == "-" or text in output:
            continue
        output.append(text)
    return output


def _external_env_template_priority_rank(priority: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(priority, 4)
