from __future__ import annotations

import json

from app.services.maintenance_diagnostic_summaries import diagnostic_summary_rows


def test_diagnostic_summary_rows_extracts_json_from_noisy_stdout() -> None:
    rows = diagnostic_summary_rows(
        "external_deployment_env_check",
        "log before json\n"
        + json.dumps(
            {
                "status": "action_required",
                "target": "all",
                "targets": ["host"],
                "env_file": ".env",
                "gap_count": 1,
                "checks": {
                    "host": {
                        "status": "action_required",
                        "target": "host",
                        "env_file_exists": True,
                        "checked_count": 2,
                        "set_count": 1,
                        "missing_count": 1,
                        "different_count": 0,
                        "rows": [
                            {
                                "status": "missing",
                                "env_key": "COMPOSE_NEO4J_URI",
                                "action": "加入 COMPOSE_NEO4J_URI=neo4j://neo4j:7687。",
                            }
                        ],
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\ntrailing log",
    )

    assert rows[0] == {
        "項目": "外部 env 檢查",
        "狀態": "action_required",
        "Ready": "target=all；gaps=1",
        "數量": "targets=1；env_file=.env",
        "下一步": "補齊 missing；確認 different；密鑰只顯示是否已設定。",
    }
    assert rows[1]["項目"] == "host env"
    assert rows[1]["Ready"] == "1/2"
    assert "missing=1" in rows[1]["數量"]
    assert "COMPOSE_NEO4J_URI" in rows[1]["下一步"]


def test_diagnostic_summary_rows_summarizes_task_submission_smoke() -> None:
    rows = diagnostic_summary_rows(
        "task_submission_noop_smoke",
        {
            "status": "caution",
            "submit": True,
            "wait": True,
            "next_actions": ["重啟 FastAPI 與 Celery worker 後重跑 smoke。"],
            "checks": [
                {"status": "passed"},
                {"status": "warning"},
                {"status": "failed"},
            ],
            "runtime_identity": {
                "status": "failed",
                "expected_commit_short": "new",
                "actual_commit_short": "old",
                "reason": "api_runtime_commit_mismatch",
            },
            "task_queue": {
                "ready": False,
                "processing_ready": True,
                "worker_online": False,
                "legacy_status_shape": True,
                "status_shape_warning": "legacy celery status",
            },
        },
    )

    assert rows[0]["項目"] == "背景任務送出檢查"
    assert rows[0]["狀態"] == "需注意"
    assert rows[0]["Ready"] == "送出=是；等待=是"
    assert "失敗=1" in rows[0]["數量"]
    assert "警告=1" in rows[0]["數量"]
    assert rows[0]["下一步"] == (
        "重新啟動 API 與背景執行器後，再重跑背景任務送出檢查。"
    )
    assert rows[1]["項目"] == "API 執行版本"
    assert rows[1]["狀態"] == "需處理"
    assert rows[1]["Ready"] == "new"
    assert rows[1]["數量"] == "old"
    assert rows[1]["下一步"] == (
        "API 執行版本與目前程式不同，重新啟動 API 後再重跑檢查。"
    )
    assert rows[2]["項目"] == "背景任務佇列"
    assert rows[2]["狀態"] == "未就緒"
    assert rows[2]["Ready"] == "可執行=是；背景執行器=否"
    assert rows[2]["數量"] == "舊版狀態格式=是"
    assert rows[2]["下一步"] == "舊版背景任務狀態格式"
    rendered = str(rows)
    assert "FastAPI" not in rendered
    assert "Celery worker" not in rendered
    assert "smoke" not in rendered
    assert "submit=True" not in rendered
    assert "worker=False" not in rendered
    assert "legacy celery status" not in rendered
    assert "api_runtime_commit_mismatch" not in rendered
