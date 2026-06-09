from __future__ import annotations


def external_deployment_env_resolution_rows_from_key_rows(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        capability = str(row.get("能力") or "-")
        grouped.setdefault(capability, []).append(row)
    return [
        _external_env_resolution_row(capability, capability_rows)
        for capability, capability_rows in sorted(
            grouped.items(),
            key=lambda item: _external_env_resolution_sort_key(item[1]),
        )
    ]


def _external_env_resolution_row(capability: str, rows: list[dict]) -> dict:
    local_rows = [row for row in rows if row.get("處理類型") == "本機可套用"]
    manual_rows = [row for row in rows if row.get("處理類型") != "本機可套用"]
    secret_rows = [row for row in rows if row.get("處理類型") == "需人工密鑰"]
    missing_count = sum(1 for row in rows if row.get("狀態") == "缺少")
    recommended_count = sum(1 for row in rows if row.get("狀態") == "建議")
    local_commands = _ordered_unique(row.get("維護動作") for row in local_rows)
    manual_keys = _ordered_unique(row.get("設定鍵") for row in manual_rows)
    all_keys = _ordered_unique(row.get("設定鍵") for row in rows)
    verify_commands = _ordered_unique(row.get("驗證指令") for row in rows)
    return {
        "優先級": _best_priority(rows),
        "能力": capability,
        "處理策略": _external_env_resolution_strategy(local_rows, manual_rows, secret_rows),
        "缺口數": len(rows),
        "缺少": missing_count,
        "建議": recommended_count,
        "本機可套用": len(local_rows),
        "需人工處理": len(manual_rows),
        "需人工密鑰": len(secret_rows),
        "設定鍵": "、".join(all_keys) if all_keys else "-",
        "本機指令": "\n".join(local_commands) if local_commands else "-",
        "手動設定鍵": "、".join(manual_keys) if manual_keys else "-",
        "建議動作": _external_env_resolution_action(local_commands, manual_rows, rows),
        "驗證指令": "\n".join(verify_commands) if verify_commands else "-",
    }


def _external_env_resolution_strategy(
    local_rows: list[dict],
    manual_rows: list[dict],
    secret_rows: list[dict],
) -> str:
    if local_rows and not manual_rows:
        return "可用本機維護操作"
    if local_rows and manual_rows:
        return "先啟動本機依賴，再補外部設定"
    if secret_rows:
        return "需人工密鑰"
    if manual_rows:
        return "需人工設定"
    return "已無缺口"


def _external_env_resolution_action(
    local_commands: list[str],
    manual_rows: list[dict],
    rows: list[dict],
) -> str:
    if local_commands and not manual_rows:
        return local_commands[0]
    if local_commands and manual_rows:
        manual_keys = ", ".join(_ordered_unique(row.get("設定鍵") for row in manual_rows))
        return f"{local_commands[0]}；再補 {manual_keys}"
    if manual_rows:
        return str(manual_rows[0].get("維護動作") or "手動補 .env 或 secret manager。")
    if rows:
        return str(rows[0].get("下一步") or "-")
    return "-"


def _external_env_resolution_sort_key(rows: list[dict]) -> tuple[int, int, str]:
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    best_priority = _best_priority(rows)
    manual_count = sum(1 for row in rows if row.get("處理類型") != "本機可套用")
    return (
        priority_order.get(best_priority, 4),
        -manual_count,
        str(rows[0].get("能力") if rows else ""),
    )


def _best_priority(rows: list[dict]) -> str:
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    priorities = [str(row.get("優先級") or "P2") for row in rows]
    return min(priorities or ["P2"], key=lambda item: priority_order.get(item, 4))


def _ordered_unique(values: object) -> list[str]:
    output: list[str] = []
    for value in values if isinstance(values, list) else list(values or []):
        text = str(value or "").strip()
        if not text or text == "-" or text in output:
            continue
        output.append(text)
    return output
