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
    assert progress["completion_ratio"] == 1.0
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
    assert progress["primary_next_action"]["action_type"] == "optional_review"
    assert "沒有 blocking" in progress["primary_next_action"]["next_action"]
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
    assert actions["neo4j_import"]["status"] == "local_ready"
    assert actions["neo4j_import"]["capability_status"] == "degraded"
    assert actions["neo4j_import"]["locally_available"] is True
    assert "--auto-local-defaults" in actions["neo4j_import"]["next_action"]
    assert actions["company_filing_high_risk_unlocker"]["status"] == "local_ready"
    assert progress["local_auto_defaults"]["local_action_available_count"] == 3


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
    assert data_row["完成率"] != "-"

    assert action_rows[0]["能力"] == "公司文件結構化 API 備援"
    assert action_rows[0]["類型"] == "付費外部 API"
    assert action_rows[0]["是否選配"] == "是"
    assert action_rows[0]["是否外部"] == "是"
