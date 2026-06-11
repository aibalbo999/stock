from __future__ import annotations

from app.ui.maintenance_progress_presenter import (
    optimization_progress_metric_values,
    optimization_progress_next_action_rows,
    optimization_progress_operator_summary,
    optimization_progress_scope_summary,
)


def test_progress_presenter_promotes_local_defaults() -> None:
    summary = optimization_progress_operator_summary(
        {
            "status": "ready_with_optional_gaps",
            "blocking_gap_count": 0,
            "optional_gap_count": 3,
            "local_resolvable_gap_count": 2,
            "effective_optional_gap_count_after_available_local_defaults": 1,
            "local_resolution_projection": {
                "next_action": "先套用本機 defaults，再觀察外部選配是否仍需要採購。",
            },
            "prioritized_next_actions": [
                {
                    "label": "MOPS/TWSE/TPEx 高風險文件 unlocker",
                    "status": "local_ready",
                    "locally_available": True,
                    "cost_profile": "free_local_available",
                    "local_auto_default": {
                        "verify_command": ".venv/bin/python scripts/upgrade_audit.py --prefer-unlocker --json",
                    },
                }
            ],
        }
    )

    assert summary["title"] == "核心優化已可用，先驗證本機選配"
    assert summary["local_action"] == "先驗證 MOPS/TWSE/TPEx 高風險文件 unlocker"
    assert summary["paid_external"] == "付費/API 選配 1 項可暫緩"
    assert summary["next_step"] == "先套用本機 defaults，再觀察外部選配是否仍需要採購。"
    assert summary["command"] == (
        ".venv/bin/python scripts/upgrade_audit.py --prefer-unlocker --json"
    )


def test_progress_presenter_localizes_status_and_compacts_commands() -> None:
    progress = {
        "status": "ready_with_optional_gaps",
        "effective_status_after_available_local_defaults": "ready",
        "ready_checks": 31,
        "total_checks": 32,
        "optional_gap_count": 4,
        "effective_optional_gap_count_after_available_local_defaults": 1,
        "prioritized_next_actions": [
            {
                "domain_label": "資料管線與爬蟲穩定度",
                "label": "公司文件結構化 API 備援",
                "status": "not_configured",
                "capability_status": "not_configured",
                "action_type": "paid_external",
                "cost_profile": "paid_external",
                "optional": True,
                "external": True,
                "free_validation_commands": [
                    "cmd one",
                    "cmd two",
                ],
            }
        ],
    }

    metrics = optimization_progress_metric_values(progress)
    rows = optimization_progress_next_action_rows(progress, compact=True)

    assert metrics["狀態"] == "完成"
    assert metrics["狀態_delta"] == "原始 核心完成/外部選配"
    assert rows[0]["狀態"] == "未設定"
    assert rows[0]["免費驗證指令"] == "2 組免費檢查"


def test_progress_presenter_explains_audit_preflight_delta() -> None:
    summary = optimization_progress_scope_summary(
        {
            "optimization_progress": {
                "ready_checks": 1,
                "total_checks": 1,
                "domains": [
                    {
                        "checks": [
                            {
                                "area": "architecture",
                                "capability": "streamlit_mpa",
                            }
                        ]
                    }
                ],
            },
            "upgrade_capability_matrix": {
                "architecture": {
                    "streamlit_mpa": {"status": "ready"},
                    "python_runtime": {"status": "ready"},
                }
            },
        }
    )

    assert summary["title"] == "優化進度與升級稽核分母不同"
    assert summary["objective"] == "優化目標 1/1"
    assert summary["audit"] == "升級稽核 2/2"
    assert "Python 3.11+ runtime" in summary["excluded"]
