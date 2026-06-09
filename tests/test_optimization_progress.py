from __future__ import annotations

from app.services.optimization_progress import (
    OPTIMIZATION_DOMAINS,
    optimization_progress_status,
)
from app.ui.maintenance_status import (
    optimization_progress_next_action_rows,
    optimization_progress_rows,
)


def _ready_status() -> dict:
    matrix: dict[str, dict[str, dict]] = {}
    for domain in OPTIMIZATION_DOMAINS:
        for ref in domain.capability_refs:
            matrix.setdefault(ref.area, {})[ref.capability] = {
                "status": "ready",
                "detail": f"{ref.label} ready",
            }
    return {"upgrade_capability_matrix": matrix}


def test_optimization_progress_reports_all_domains_ready() -> None:
    progress = optimization_progress_status(_ready_status())

    assert progress["collector_path"] == "app/services/optimization_progress.py"
    assert progress["status"] == "ready"
    assert progress["total_domains"] == 4
    assert progress["blocking_gap_count"] == 0
    assert progress["optional_gap_count"] == 0
    assert progress["local_resolvable_gap_count"] == 0
    assert progress["effective_status_after_available_local_defaults"] == "ready"
    assert (
        progress["effective_blocking_gap_count_after_available_local_defaults"]
        == 0
    )
    assert (
        progress["effective_optional_gap_count_after_available_local_defaults"]
        == 0
    )
    assert progress["effective_gap_note"] == ""
    assert progress["projected_status_after_local_defaults"] == "ready"
    assert progress["completion_ratio"] == 1.0
    assert progress["summary"]["status"] == "ready"
    assert (
        progress["summary"]["effective_status_after_available_local_defaults"]
        == "ready"
    )
    assert progress["summary"]["completion_ratio"] == 1.0
    assert progress["summary"]["primary_next_action_type"] == "monitoring"
    assert progress["primary_next_action"]["action_type"] == "monitoring"
    assert {domain["id"] for domain in progress["domains"]} == {
        "architecture_uiux",
        "codebase_maintainability",
        "data_pipeline_scraping",
        "ai_rag_graphrag",
    }


def test_optimization_progress_keeps_paid_structured_api_as_optional_gap() -> None:
    status = _ready_status()
    status["upgrade_capability_matrix"]["data_business_logic"][
        "company_filing_structured_api_fallback"
    ] = {
        "status": "not_configured",
        "detail": "paid external API not configured",
    }

    progress = optimization_progress_status(status)

    assert progress["status"] == "ready_with_optional_gaps"
    assert progress["blocking_gap_count"] == 0
    assert progress["optional_gap_count"] == 1
    assert progress["local_resolvable_gap_count"] == 0
    assert (
        progress["effective_optional_gap_count_after_available_local_defaults"]
        == 1
    )
    assert (
        progress["effective_status_after_available_local_defaults"]
        == "ready_with_optional_gaps"
    )
    assert progress["effective_gap_note"] == ""
    assert progress["projected_optional_gap_count_after_local_defaults"] == 1
    assert progress["primary_next_action"]["action_type"] == "optional_review"
    assert "沒有 blocking" in progress["primary_next_action"]["next_action"]
    assert (
        progress["summary"]["primary_next_action_type"]
        == progress["primary_next_action"]["action_type"]
    )
    assert progress["summary"]["optional_gap_count"] == 1
    assert progress["next_actions"][0]["capability"] == ("company_filing_structured_api_fallback")
    assert progress["next_actions"][0]["action_type"] == "paid_external"
    data_domain = next(
        domain for domain in progress["domains"] if domain["id"] == "data_pipeline_scraping"
    )
    assert data_domain["status"] == "ready_with_optional_gaps"
    assert data_domain["optional_gaps"][0]["external"] is True
    assert "TEJ" in data_domain["optional_gaps"][0]["next_action"]


def test_optimization_progress_marks_core_capability_gap_as_blocking() -> None:
    status = _ready_status()
    status["upgrade_capability_matrix"]["architecture"]["background_task_queue"] = {
        "status": "degraded",
        "detail": "worker offline",
    }

    progress = optimization_progress_status(status)

    assert progress["status"] == "degraded"
    assert progress["blocking_gap_count"] == 1
    assert progress["optional_gap_count"] == 0
    assert progress["primary_next_action"]["capability"] == "background_task_queue"
    assert progress["primary_next_action"]["optional"] is False
    architecture = next(
        domain for domain in progress["domains"] if domain["id"] == "architecture_uiux"
    )
    assert architecture["blocking_gaps"][0]["next_action"] == (
        "檢查 背景任務 queue readiness：worker offline"
    )


def test_optimization_progress_marks_local_auto_default_optional_gaps() -> None:
    status = _ready_status()
    status["upgrade_capability_matrix"]["ai_rag"]["neo4j_import"] = {
        "status": "degraded",
        "detail": "missing Neo4j env",
    }
    status["upgrade_capability_matrix"]["ai_rag"]["graphrag_live_cypher_query"] = {
        "status": "degraded",
        "detail": "missing Neo4j env",
    }
    status["upgrade_capability_matrix"]["data_business_logic"][
        "company_filing_high_risk_unlocker"
    ] = {
        "status": "not_configured",
        "detail": "missing unlocker env",
    }
    status["local_dependency_auto_defaults"] = {
        "mode": "status_preview",
        "compatible_audit_command": (
            ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json"
        ),
        "detected": {"neo4j": True, "flaresolverr": True},
        "would_apply_groups": ["flaresolverr", "neo4j"],
        "capability_matches": [
            {
                "area": "ai_rag",
                "capability": "neo4j_import",
                "group": "neo4j",
                "verify_command": ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json",
            },
            {
                "area": "ai_rag",
                "capability": "graphrag_live_cypher_query",
                "group": "neo4j",
                "verify_command": ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json",
            },
            {
                "area": "data_business_logic",
                "capability": "company_filing_high_risk_unlocker",
                "group": "flaresolverr",
                "verify_command": ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json",
            },
        ],
        "local_action_available_count": 3,
    }

    progress = optimization_progress_status(status)

    actions = {row["capability"]: row for row in progress["next_actions"]}
    assert progress["status"] == "ready_with_optional_gaps"
    assert progress["optional_gap_count"] == 3
    assert progress["local_resolvable_gap_count"] == 3
    assert progress["effective_status_after_available_local_defaults"] == "ready"
    assert (
        progress["effective_blocking_gap_count_after_available_local_defaults"]
        == 0
    )
    assert (
        progress["effective_optional_gap_count_after_available_local_defaults"]
        == 0
    )
    assert "原始缺口為 0 blocking / 3 選配" in progress["effective_gap_note"]
    assert "有效剩餘 0 blocking / 0 選配" in progress["effective_gap_note"]
    assert progress["projected_status_after_local_defaults"] == "ready"
    assert progress["projected_optional_gap_count_after_local_defaults"] == 0
    assert progress["local_resolution_projection"]["local_action_capabilities"] == [
        "company_filing_high_risk_unlocker",
        "neo4j_import",
        "graphrag_live_cypher_query",
    ]
    assert progress["local_resolution_projection"]["remaining_action_capabilities"] == []
    assert actions["neo4j_import"]["status"] == "local_ready"
    assert actions["neo4j_import"]["capability_status"] == "degraded"
    assert actions["neo4j_import"]["locally_available"] is True
    assert "--auto-local-defaults" in actions["neo4j_import"]["next_action"]
    assert actions["company_filing_high_risk_unlocker"]["status"] == "local_ready"
    assert progress["primary_next_action"]["capability"] == "auto_local_defaults"
    assert progress["primary_next_action"]["status"] == "local_ready"
    assert progress["primary_next_action"]["locally_available"] is True
    assert progress["summary"]["primary_next_action_capability"] == "auto_local_defaults"
    assert (
        progress["summary"]["primary_next_action_cost_profile"]
        == "free_local_available"
    )
    assert "--auto-local-defaults" in progress["primary_next_action"]["next_action"]
    assert "驗證 3 項缺口" in progress["primary_next_action"]["next_action"]
    assert "剩餘 0 項外部/付費選配" in progress["primary_next_action"]["next_action"]
    action_rows = optimization_progress_next_action_rows(progress)
    assert action_rows[0]["能力"] == "本機 defaults 可驗證"
    assert action_rows[0]["本機"] == "可用"
    assert action_rows[0]["成本/額度"] == "本機免費可驗證"
    assert "--auto-local-defaults" in action_rows[0]["建議"]
    assert action_rows[1]["能力"] == "MOPS/TWSE/TPEx 高風險文件 unlocker"
    assert progress["local_auto_defaults"]["local_action_available_count"] == 3


def test_optimization_progress_prioritizes_high_roi_next_actions() -> None:
    status = _ready_status()
    status["upgrade_capability_matrix"]["architecture"]["background_task_queue"] = {
        "status": "degraded",
        "detail": "worker offline",
    }
    status["upgrade_capability_matrix"]["ai_rag"]["visual_rag"] = {
        "status": "not_configured",
        "detail": "vision-capable model not configured",
    }
    status["upgrade_capability_matrix"]["ai_rag"]["neo4j_import"] = {
        "status": "degraded",
        "detail": "missing Neo4j env",
    }
    status["upgrade_capability_matrix"]["data_business_logic"][
        "company_filing_structured_api_fallback"
    ] = {
        "status": "not_configured",
        "detail": "paid external API not configured",
    }
    status["local_dependency_auto_defaults"] = {
        "capability_matches": [
            {
                "area": "ai_rag",
                "capability": "neo4j_import",
                "group": "neo4j",
                "verify_command": ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json",
            }
        ]
    }

    progress = optimization_progress_status(status)
    prioritized = progress["prioritized_next_actions"]

    assert prioritized[0]["capability"] == "background_task_queue"
    assert prioritized[0]["priority_band"] == "blocking"
    assert prioritized[0]["priority_score"] == 100
    assert progress["primary_next_action"]["capability"] == "background_task_queue"

    positions = {action["capability"]: index for index, action in enumerate(prioritized)}
    assert positions["neo4j_import"] < positions["visual_rag"]
    assert positions["visual_rag"] < positions["company_filing_structured_api_fallback"]
    assert prioritized[positions["neo4j_import"]]["cost_profile"] == "free_local_available"
    assert prioritized[positions["visual_rag"]]["cost_profile"] == "quota_or_external"
    assert prioritized[positions["company_filing_structured_api_fallback"]][
        "cost_profile"
    ] == "paid_external"
    assert progress["local_resolution_projection"]["projected_blocking_gap_count"] == 1
    assert (
        progress["effective_blocking_gap_count_after_available_local_defaults"]
        == 1
    )
    assert progress["local_resolution_projection"]["remaining_action_capabilities"] == [
        "background_task_queue",
        "visual_rag",
        "company_filing_structured_api_fallback",
    ]


def test_optimization_progress_ui_rows_summarize_domains_and_actions() -> None:
    status = _ready_status()
    status["upgrade_capability_matrix"]["data_business_logic"][
        "company_filing_structured_api_fallback"
    ] = {"status": "not_configured", "detail": "paid external API not configured"}
    progress = optimization_progress_status(status)

    rows = optimization_progress_rows(progress)
    action_rows = optimization_progress_next_action_rows(progress)

    data_row = next(row for row in rows if row["主題"] == "資料管線與爬蟲穩定度")
    assert data_row["狀態"] == "核心完成/外部選配"
    assert data_row["外部/選配"] == 1
    assert data_row["Blocking"] == 0
    assert data_row["本機可補"] == 0
    assert data_row["套用後剩餘"] == "0 blocking / 1 選配"
    assert data_row["完成率"] != "-"

    assert action_rows[0]["能力"] == "公司文件結構化 API 備援"
    assert action_rows[0]["類型"] == "付費外部 API"
    assert action_rows[0]["成本/額度"] == "付費外部"
    assert action_rows[0]["優先分數"] == 30
    assert action_rows[0]["決策"]
    assert action_rows[0]["是否選配"] == "是"
    assert action_rows[0]["是否外部"] == "是"
