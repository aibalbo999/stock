from __future__ import annotations

from typing import Any


def capability_free_validation(capability: dict[str, Any]) -> dict:
    evidence = capability.get("evidence") if isinstance(capability.get("evidence"), dict) else {}
    runtime = evidence.get("runtime") if isinstance(evidence.get("runtime"), dict) else {}
    free_validation = (
        runtime.get("free_validation") if isinstance(runtime.get("free_validation"), dict) else {}
    )
    commands = _ordered_unique(
        [
            runtime.get("sample_contract_cli"),
            free_validation.get("sample_contract_cli"),
            runtime.get("local_fixture_http_smoke_cli"),
            free_validation.get("local_fixture_http_smoke_cli"),
            runtime.get("local_fixture_provider_profile_smoke_cli"),
            free_validation.get("local_fixture_provider_profile_smoke_cli"),
            runtime.get("local_fixture_start_cli"),
            free_validation.get("local_fixture_start_cli"),
            runtime.get("local_fixture_smoke_cli"),
            free_validation.get("local_fixture_smoke_cli"),
        ]
    )
    return {
        "available": bool(commands),
        "label": _free_validation_label(commands),
        "commands": commands,
    }


def _free_validation_label(commands: list[str]) -> str:
    if not commands:
        return ""
    has_sample = any("--sample-json" in command for command in commands)
    has_fixture = any(
        "structured_company_filing_fixture_smoke.py" in command
        or "local_structured_company_filing_api.py" in command
        for command in commands
    )
    has_provider_profile = any("--provider-profile" in command for command in commands)
    if has_sample and has_fixture and has_provider_profile:
        return "樣本資料 + 本機測試 API + 提供者設定可驗證"
    if has_sample and has_fixture:
        return "樣本資料 + 本機測試 API 可驗證"
    if has_sample:
        return "樣本資料格式可驗證"
    return "免費驗證可用"


def _ordered_unique(values: list[object]) -> list[str]:
    items: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in items:
            items.append(item)
    return items
