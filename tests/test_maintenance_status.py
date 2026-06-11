from __future__ import annotations

from app.ui.maintenance_status import (
    optimization_progress_metric_values,
    optimization_progress_next_action_rows,
    optimization_progress_operator_summary,
    optimization_progress_scope_summary,
)


def test_optimization_progress_operator_summary_promotes_local_defaults() -> None:
    summary = optimization_progress_operator_summary(
        {
            "status": "ready_with_optional_gaps",
            "effective_status_after_available_local_defaults": "ready_with_optional_gaps",
            "blocking_gap_count": 0,
            "optional_gap_count": 4,
            "local_resolvable_gap_count": 3,
            "effective_optional_gap_count_after_available_local_defaults": 1,
            "local_resolution_projection": {
                "next_action": "套用已偵測本機 defaults 可先消除 3 項缺口；有效剩餘 1 項付費外部資料 API 選配。",
            },
            "prioritized_next_actions": [
                {
                    "label": "MOPS/TWSE/TPEx 高風險文件 unlocker",
                    "status": "local_ready",
                    "locally_available": True,
                    "optional": True,
                    "external": True,
                    "cost_profile": "free_local_available",
                    "decision": "本機已可免費驗證；正式部署時再固化到 .env。",
                    "local_auto_default": {
                        "verify_command": ".venv/bin/python scripts/upgrade_audit.py --prefer-unlocker --wait-local-flaresolverr 20 --local-browser-render-defaults --json",
                    },
                },
                {
                    "label": "公司文件結構化 API 備援",
                    "status": "not_configured",
                    "optional": True,
                    "external": True,
                    "cost_profile": "paid_external",
                    "decision": "付費資料源/外部 API；只有正式穩定性需求明確時再採購。",
                },
            ],
        }
    )

    assert summary == {
        "state": "ready",
        "title": "核心優化已可用，先驗證本機選配",
        "detail": "目前沒有 blocking 缺口；4 項外部選配中 3 項可用本機 defaults 或免費 smoke 驗證。",
        "local_action": "先驗證 MOPS/TWSE/TPEx 高風險文件 unlocker",
        "paid_external": "付費/API 選配 1 項可暫緩",
        "next_step": "套用已偵測本機 defaults 可先消除 3 項缺口；有效剩餘 1 項付費外部資料 API 選配。",
        "command": ".venv/bin/python scripts/upgrade_audit.py --prefer-unlocker --wait-local-flaresolverr 20 --local-browser-render-defaults --json",
    }


def test_optimization_progress_metric_values_localize_raw_statuses() -> None:
    metrics = optimization_progress_metric_values(
        {
            "status": "ready_with_optional_gaps",
            "effective_status_after_available_local_defaults": "ready",
            "ready_checks": 31,
            "total_checks": 32,
            "blocking_gap_count": 0,
            "optional_gap_count": 4,
            "effective_blocking_gap_count_after_available_local_defaults": 0,
            "effective_optional_gap_count_after_available_local_defaults": 1,
            "local_resolvable_gap_count": 0,
        }
    )

    assert metrics["狀態"] == "完成"
    assert metrics["狀態_delta"] == "原始 核心完成/外部選配"
    assert metrics["完成"] == "31/32"
    assert metrics["Blocking"] == 0
    assert metrics["外部/選配"] == 1
    assert metrics["外部/選配_delta"] == "原始 4"
    assert metrics["本機可補"] == 0
    assert "ready_with_optional_gaps" not in str(metrics)


def test_optimization_progress_next_action_rows_localize_status_values() -> None:
    rows = optimization_progress_next_action_rows(
        {
            "prioritized_next_actions": [
                {
                    "domain_label": "資料管線與爬蟲穩定度",
                    "label": "公司文件結構化 API 備援",
                    "priority_score": 30,
                    "status": "not_configured",
                    "capability_status": "not_configured",
                    "optional": True,
                    "external": True,
                    "action_type": "paid_external",
                    "cost_profile": "paid_external",
                }
            ]
        }
    )

    assert rows[0]["狀態"] == "未設定"
    assert rows[0]["能力狀態"] == "未設定"
    assert "not_configured" not in str(rows[0])


def test_optimization_progress_operator_summary_surfaces_paid_external_only_gap() -> None:
    summary = optimization_progress_operator_summary(
        {
            "status": "ready_with_optional_gaps",
            "effective_status_after_available_local_defaults": "ready_with_optional_gaps",
            "blocking_gap_count": 0,
            "optional_gap_count": 1,
            "local_resolvable_gap_count": 0,
            "effective_optional_gap_count_after_available_local_defaults": 1,
            "prioritized_next_actions": [
                {
                    "label": "公司文件結構化 API 備援",
                    "status": "not_configured",
                    "optional": True,
                    "external": True,
                    "cost_profile": "paid_external",
                    "decision": "付費資料源/外部 API；只有正式穩定性需求明確時再採購。",
                    "next_action": "若法說會簡報或重大訊息需要穩定資料，再設定 TEJ 或專業資料 API。",
                },
            ],
        }
    )

    assert summary == {
        "state": "ready",
        "title": "本機優化已完成，剩下外部資料 API 決策",
        "detail": "目前沒有 blocking 缺口，也沒有本機 defaults 可補；剩餘 1 項是付費/API 選配。",
        "local_action": "本機 defaults 已無待處理項目",
        "paid_external": "公司文件結構化 API 備援：需外部資料商或正式 API",
        "next_step": "若法說會簡報或重大訊息需要穩定資料，再設定 TEJ 或專業資料 API。",
        "command": "-",
    }


def test_optimization_progress_operator_summary_blocks_on_required_gaps() -> None:
    summary = optimization_progress_operator_summary(
        {
            "status": "degraded",
            "blocking_gap_count": 2,
            "optional_gap_count": 1,
            "prioritized_next_actions": [
                {
                    "label": "背景任務佇列",
                    "status": "degraded",
                    "optional": False,
                    "next_action": "先啟動 Redis/Celery。",
                }
            ],
        }
    )

    assert summary["state"] == "blocked"
    assert summary["title"] == "優化仍有 blocking 缺口"
    assert summary["local_action"] == "先處理 背景任務佇列"
    assert summary["paid_external"] == "付費/API 選配不是優先事項"
    assert summary["next_step"] == "先啟動 Redis/Celery。"


def test_optimization_progress_operator_summary_ready_when_no_actions() -> None:
    summary = optimization_progress_operator_summary(
        {
            "status": "ready",
            "ready_checks": 33,
            "total_checks": 33,
            "blocking_gap_count": 0,
            "optional_gap_count": 0,
        }
    )

    assert summary == {
        "state": "ready",
        "title": "優化目標目前沒有待處理缺口",
        "detail": "核心能力與外部部署檢查都沒有待處理項目。",
        "local_action": "不需本機 defaults",
        "paid_external": "付費/API 選配 0 項",
        "next_step": "維持例行 smoke、audit 與報告品質觀測。",
        "command": "-",
    }


def test_optimization_progress_scope_summary_explains_audit_preflight_delta() -> None:
    summary = optimization_progress_scope_summary(
        {
            "optimization_progress": {
                "ready_checks": 28,
                "total_checks": 32,
                "domains": [
                    {
                        "checks": [
                            {"area": "architecture", "capability": "background_task_queue"},
                            {"area": "ai_rag", "capability": "llm_quota_routing"},
                        ]
                    }
                ],
            },
            "upgrade_capability_matrix": {
                "architecture": {
                    "background_task_queue": {"status": "ready"},
                    "python_runtime": {"status": "ready"},
                },
                "ai_rag": {"llm_quota_routing": {"status": "ready"}},
            },
        }
    )

    assert summary == {
        "state": "info",
        "title": "優化進度與升級稽核分母不同",
        "detail": "優化目標追蹤 32 項；完整升級稽核追蹤 3 項，另含 1 項部署 preflight。",
        "objective": "優化目標 28/32",
        "audit": "升級稽核 3/3",
        "excluded": "部署 preflight：Python 3.11+ runtime",
        "note": "這不是缺口漏算；python_runtime 屬部署前檢查，不計入已核准的四大優化目標分母。",
    }
