from __future__ import annotations

from typing import Any


def optimization_local_defaults_action(service_snapshot: dict | None) -> dict[str, Any]:
    snapshot = _dict_value(service_snapshot)
    progress = _dict_value(snapshot.get("optimization_progress"))
    primary_action = _dict_value(progress.get("primary_next_action"))
    local_projection = _dict_value(progress.get("local_resolution_projection"))
    if primary_action.get("capability") != "auto_local_defaults":
        return {}
    local_count = _int_value(
        progress.get("local_resolvable_gap_count")
        or local_projection.get("local_resolvable_gap_count")
    )
    if local_count <= 0:
        return {}
    remaining_optional = _int_value(
        progress.get("effective_optional_gap_count_after_available_local_defaults")
        if progress.get("effective_optional_gap_count_after_available_local_defaults") is not None
        else local_projection.get("projected_optional_gap_count")
    )
    command = _text(
        progress.get("local_defaults_verify_command")
        or local_projection.get("local_defaults_verify_command")
        or primary_action.get("verify_command")
    )
    detail = f"可用本機 defaults 驗證 {local_count} 項外部選配"
    if remaining_optional:
        detail += f"，驗證後剩餘 {remaining_optional} 項外部/付費選配。"
    else:
        detail += "，驗證後沒有剩餘 blocking 缺口。"
    if command:
        detail += " 維護頁已整理對應操作與驗證指令。"
    return {
        "title": "驗證本機 defaults",
        "detail": detail,
        "state": "ready",
        "route_hint": "settings:maintenance:local_defaults",
        "action_label": "查看本機操作",
        "source_ids": ["optimization:auto_local_defaults"],
    }


def optimization_free_validation_action(service_snapshot: dict | None) -> dict[str, Any]:
    snapshot = _dict_value(service_snapshot)
    progress = _dict_value(snapshot.get("optimization_progress"))
    for action in _optimization_actions(progress):
        if not action.get("free_validation_available"):
            continue
        commands = action.get("free_validation_commands")
        command_count = len(commands) if isinstance(commands, list) else 0
        validation_label = _text(
            action.get("free_validation_label"),
            default="可用本機樣本驗證",
        )
        capability = _text(action.get("capability"))
        label = _text(action.get("label") or capability, default="外部 API")
        if capability == "company_filing_structured_api_fallback":
            detail = (
                f"{validation_label}；正式串 TEJ 或付費資料商前，"
                f"先用 {command_count or 1} 組免費檢查驗證 JSON/HTTP 格式。"
            )
            return {
                "title": "驗證公司文件 API 格式",
                "detail": detail,
                "state": "attention",
                "route_hint": "settings:maintenance:structured_api",
                "action_label": "查看免費驗證",
                "source_ids": ["optimization:company_filing_structured_api_fallback"],
            }
        return {
            "title": f"驗證{label}",
            "detail": f"{validation_label}；正式啟用外部服務前先跑免費驗證。",
            "state": "attention",
            "route_hint": "settings:maintenance",
            "action_label": "查看免費驗證",
            "source_ids": [f"optimization:{capability}" if capability else "optimization"],
        }
    return {}


def _optimization_actions(progress: dict) -> list[dict]:
    actions: list[dict] = []
    primary_action = _dict_value(progress.get("primary_next_action"))
    if primary_action:
        actions.append(primary_action)
    for action in progress.get("prioritized_next_actions") or progress.get("next_actions") or []:
        if isinstance(action, dict):
            actions.append(action)
    deduped: list[dict] = []
    seen: set[str] = set()
    for action in actions:
        capability = _text(action.get("capability"))
        key = capability or _text(action.get("label"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _text(value: Any, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default
