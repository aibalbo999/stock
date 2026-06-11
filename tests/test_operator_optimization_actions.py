from __future__ import annotations

from app.ui.operator_optimization_actions import (
    optimization_free_validation_action,
    optimization_local_defaults_action,
)


def test_optimization_local_defaults_action_summarizes_local_projection() -> None:
    action = optimization_local_defaults_action(
        {
            "optimization_progress": {
                "primary_next_action": {
                    "capability": "auto_local_defaults",
                    "verify_command": "python scripts/check.py",
                },
                "local_resolvable_gap_count": 2,
                "effective_optional_gap_count_after_available_local_defaults": 1,
            }
        }
    )

    assert action == {
        "title": "驗證本機 defaults",
        "detail": "可用本機 defaults 驗證 2 項外部選配，驗證後剩餘 1 項外部/付費選配。 維護頁已整理對應操作與驗證指令。",
        "state": "ready",
        "route_hint": "settings:maintenance:local_defaults",
        "action_label": "查看本機操作",
        "source_ids": ["optimization:auto_local_defaults"],
    }


def test_optimization_free_validation_action_prioritizes_structured_filing_api() -> None:
    action = optimization_free_validation_action(
        {
            "optimization_progress": {
                "prioritized_next_actions": [
                    {
                        "capability": "company_filing_structured_api_fallback",
                        "free_validation_available": True,
                        "free_validation_label": "可用本機 fixture 驗證",
                        "free_validation_commands": ["cmd-1", "cmd-2"],
                    }
                ]
            }
        }
    )

    assert action == {
        "title": "驗證公司文件 API 格式",
        "detail": "可用本機 fixture 驗證；正式串 TEJ 或付費資料商前，先用 2 組免費檢查驗證 JSON/HTTP 格式。",
        "state": "attention",
        "route_hint": "settings:maintenance:structured_api",
        "action_label": "查看免費驗證",
        "source_ids": ["optimization:company_filing_structured_api_fallback"],
    }
