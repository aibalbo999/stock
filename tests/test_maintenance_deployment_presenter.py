from __future__ import annotations

from app.ui.maintenance_deployment_presenter import (
    external_deployment_operator_summary,
    external_deployment_effective_gap_rows,
    external_deployment_focus_banner,
    maintenance_operation_post_run_check_rows,
    maintenance_operation_post_run_diagnostic_action_ids,
    maintenance_operation_recommendation_caption,
    maintenance_operation_rows,
    recommended_maintenance_operation_id,
)


def test_external_deployment_operator_summary_explains_optional_warnings() -> None:
    summary = external_deployment_operator_summary(
        {
            "summary": {
                "deployment_optional_only": True,
                "deployment_blocking_failures": 0,
                "failures": 0,
                "optional_warnings": 4,
            }
        },
        {
            "pending": 4,
            "blocking_pending": 0,
            "all_pending_optional": True,
            "free_local_pending": 3,
            "local_action_available": 3,
            "paid_external_pending": 1,
            "primary_next_action": "先處理本機免費可補強項目，再評估 API 額度或付費資料商。",
        },
        {
            "current_pending": 4,
            "available_local_default_gap_count": 3,
            "remaining_pending": 1,
            "remaining_blocking_pending": 0,
            "remaining_paid_external_pending": 1,
            "next_action": "套用已偵測本機 defaults 可先消除 3 項缺口；有效剩餘 1 項付費外部資料 API 選配。",
        },
    )

    assert summary["state"] == "ready"
    assert summary["title"] == "外部選配不是系統故障"
    assert "沒有 blocking deployment 缺口" in summary["detail"]
    assert summary["local_action"] == "3 項可先用本機 defaults 驗證"
    assert summary["effective_remaining"] == "有效剩餘 1 項"
    assert summary["paid_external"] == "付費/API 選配 1 項"
    assert summary["next_step"] == (
        "套用已偵測本機 defaults 可先消除 3 項缺口；有效剩餘 1 項付費外部資料 API 選配。"
    )


def test_external_deployment_operator_summary_flags_blocking_gaps() -> None:
    summary = external_deployment_operator_summary(
        {"summary": {"deployment_blocking_failures": 1, "failures": 1}},
        {"pending": 2, "blocking_pending": 1, "local_action_available": 0},
        {"remaining_pending": 2, "remaining_blocking_pending": 1},
    )

    assert summary["state"] == "blocked"
    assert summary["title"] == "外部部署需先處理 blocking 缺口"
    assert "目前仍有 1 項 blocking deployment 缺口" in summary["detail"]
    assert summary["next_step"] == "先處理 blocking 缺口，再回來重跑升級稽核。"


def test_maintenance_deployment_presenter_builds_structured_api_focus_banner() -> None:
    banner = external_deployment_focus_banner("structured_api")

    assert banner["title"] == "公司文件結構化 API 免費驗證"
    assert "正式串 TEJ 或付費資料商前" in banner["detail"]
    assert "結構化文件 API 操作提示" in banner["detail"]
    assert banner["state"] == "attention"
    assert banner["target_caption"] == "免費 smoke 驗證 JSON/HTTP contract"
    assert external_deployment_focus_banner("unknown") == {}
    assert external_deployment_focus_banner(None) == {}


def test_maintenance_deployment_presenter_builds_effective_gap_rows() -> None:
    rows = external_deployment_effective_gap_rows(
        {
            "current_pending": 3,
            "available_local_default_gap_count": 2,
            "remaining_pending": 1,
            "remaining_blocking_pending": 0,
            "remaining_optional_pending": 1,
            "remaining_paid_external_pending": 1,
            "local_default_capabilities": [
                {"capability": "neo4j_import", "label": "外部 Neo4j 匯入連線"},
                "GraphRAG guarded live Cypher query",
            ],
            "remaining_capabilities": [
                {
                    "capability": "company_filing_structured_api_fallback",
                    "label": "公司文件結構化 API 備援",
                }
            ],
            "local_default_verify_commands": ["audit --local"],
        }
    )

    assert rows[0] == {"項目": "原始外部選配", "數量": 3, "說明": "尚未扣除已偵測本機 defaults"}
    assert rows[1]["說明"] == "外部 Neo4j 匯入連線、GraphRAG guarded live Cypher query"
    assert rows[2] == {"項目": "有效剩餘", "數量": 1, "說明": "公司文件結構化 API 備援"}
    assert rows[-1] == {"項目": "本機驗證指令", "數量": 1, "說明": "audit --local"}
    assert external_deployment_effective_gap_rows({}) == []
    assert external_deployment_effective_gap_rows([]) == []


def test_maintenance_deployment_presenter_recommends_operations_from_projection_first() -> None:
    operations = {
        "operations": [
            {
                "id": "start_local_dependencies",
                "label": "啟動本機核心依賴",
                "display_command": "docker compose up -d neo4j",
                "mutates_local_state": True,
            },
            {
                "id": "start_local_dependencies_with_unlocker",
                "label": "啟動本機依賴與 unlocker",
                "display_command": "docker compose --profile unlocker up -d flaresolverr",
                "mutates_local_state": True,
            },
        ]
    }

    assert (
        recommended_maintenance_operation_id(
            operations,
            [{"本機可套用": 2, "本機指令": "--prefer-unlocker"}],
            {"local_action_capabilities": ["neo4j_import"]},
        )
        == "start_local_dependencies"
    )
    assert (
        recommended_maintenance_operation_id(
            operations,
            [],
            {"local_default_capabilities": [{"capability": "company_filing_high_risk_unlocker"}]},
        )
        == "start_local_dependencies_with_unlocker"
    )
    assert (
        maintenance_operation_recommendation_caption(
            operations,
            "start_local_dependencies",
        )
        == "建議操作：啟動本機核心依賴；會預選此操作，確認後才會執行。指令：docker compose up -d neo4j"
    )


def test_maintenance_deployment_presenter_builds_operation_and_post_run_rows() -> None:
    rows = maintenance_operation_rows(
        {
            "operations": [
                {
                    "id": "start_local_dependencies",
                    "label": "啟動本機核心依賴",
                    "description": "啟動 Neo4j。",
                    "display_command": "docker compose up -d neo4j",
                    "timeout_seconds": 240,
                    "requires_confirmation": True,
                    "scope": "Docker services",
                    "resolves_capabilities": [
                        {"capability": "neo4j_import", "label": "外部 Neo4j 匯入連線"}
                    ],
                }
            ]
        }
    )
    post_run_rows = maintenance_operation_post_run_check_rows(
        {
            "post_run_checks": [
                {
                    "item": "GraphRAG live Neo4j smoke",
                    "purpose": "驗證 live query",
                    "diagnostic_action_id": "graphrag_live_query_smoke",
                    "command": "neo4j-smoke --json",
                },
                {
                    "item": "GraphRAG live Neo4j smoke duplicate",
                    "purpose": "驗證 live query",
                    "diagnostic_action_id": "graphrag_live_query_smoke",
                    "command": "neo4j-smoke --json",
                },
            ]
        }
    )

    assert rows == [
        {
            "操作": "啟動本機核心依賴",
            "狀態": "需確認",
            "作用範圍": "Docker services",
            "可處理能力": "外部 Neo4j 匯入連線",
            "說明": "啟動 Neo4j。",
            "指令": "docker compose up -d neo4j",
            "Timeout": 240,
        }
    ]
    assert post_run_rows[0]["可執行診斷"] == "graphrag_live_query_smoke"
    assert maintenance_operation_post_run_diagnostic_action_ids(
        [post_run_rows[0], post_run_rows[1], {"可執行診斷": "-"}]
    ) == ["graphrag_live_query_smoke"]
