from __future__ import annotations

from app.ui.maintenance_deployment_presenter import (
    external_deployment_effective_gap_rows,
    maintenance_operation_post_run_check_rows,
    maintenance_operation_post_run_diagnostic_action_ids,
    maintenance_operation_recommendation_caption,
    maintenance_operation_rows,
    recommended_maintenance_operation_id,
)


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
