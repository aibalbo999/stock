from __future__ import annotations

from app.ui.maintenance_status import optimization_progress_operator_summary


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
