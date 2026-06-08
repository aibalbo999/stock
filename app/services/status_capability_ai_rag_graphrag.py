from __future__ import annotations

from app.services.status_capability_helpers import capability as _capability
from app.services.status_graphrag import _neo4j_import_capability_status


def graphrag_capabilities(*, graph_status: dict) -> dict:
    neo4j_import = graph_status.get("neo4j_import") or {}
    return {
        "graphrag_context": _capability(
            "ready"
            if graph_status.get("enabled") and graph_status.get("query_expansion_enabled")
            else "degraded",
            evidence={
                "capability_builder_path": (
                    "app/services/status_capability_ai_rag_graphrag.py"
                ),
                "node_count": graph_status.get("node_count"),
                "edge_count": graph_status.get("edge_count"),
                "edge_confidence": graph_status.get("edge_confidence"),
                "retrieval_query_plan_enabled": graph_status.get("retrieval_query_plan_enabled"),
                "retrieval_query_strategy": graph_status.get("retrieval_query_strategy"),
                "retrieval_evidence_policy": graph_status.get("retrieval_evidence_policy"),
                "retrieval_query_example": graph_status.get("retrieval_query_example"),
                "neo4j_export_enabled": graph_status.get("neo4j_export_enabled"),
            },
            detail=graph_status.get("purpose"),
        ),
        "graphrag_path_reasoning": _capability(
            "ready"
            if graph_status.get("path_reasoning_enabled")
            and graph_status.get("shortest_path_context_enabled")
            else "degraded",
            evidence={
                "path_reasoning_enabled": graph_status.get("path_reasoning_enabled"),
                "shortest_path_context_enabled": graph_status.get(
                    "shortest_path_context_enabled"
                ),
                "path_reasoning_strategy": graph_status.get("path_reasoning_strategy"),
                "path_reasoning_evidence_policy": graph_status.get(
                    "path_reasoning_evidence_policy"
                ),
                "path_reasoning_example": graph_status.get("path_reasoning_example"),
                "path_reasoning_endpoint": graph_status.get("path_reasoning_endpoint"),
                "neo4j_shortest_path_template": graph_status.get(
                    "neo4j_shortest_path_template"
                ),
            },
            detail="GraphRAG can compute shortest-path impact context for LLM reasoning while preserving evidence guardrails.",
        ),
        "graphrag_agentic_cypher": _capability(
            "ready"
            if graph_status.get("agentic_cypher_planner_enabled")
            and (graph_status.get("agentic_cypher_plan_example") or {})
            .get("validation", {})
            .get("valid")
            else "degraded",
            evidence={
                "agentic_cypher_planner_enabled": graph_status.get(
                    "agentic_cypher_planner_enabled"
                ),
                "agentic_cypher_strategy": graph_status.get("agentic_cypher_strategy"),
                "agentic_cypher_endpoint": graph_status.get("agentic_cypher_endpoint"),
                "agentic_cypher_guardrails": graph_status.get("agentic_cypher_guardrails"),
                "agentic_cypher_plan_example": graph_status.get("agentic_cypher_plan_example"),
                "local_dry_run_enabled": graph_status.get(
                    "agentic_cypher_local_dry_run_enabled"
                ),
                "local_dry_run_status": graph_status.get(
                    "agentic_cypher_local_dry_run_status"
                ),
                "local_dry_run_mode": graph_status.get(
                    "agentic_cypher_local_dry_run_mode"
                ),
                "local_dry_run_row_count": graph_status.get(
                    "agentic_cypher_local_dry_run_row_count"
                ),
                "local_dry_run_evidence_policy": graph_status.get(
                    "agentic_cypher_local_dry_run_evidence_policy"
                ),
            },
            detail=(
                "LLM-generated Cypher is supported through a guarded planner that validates "
                "read-only operations, labels, relationship types, parameters, and path depth; "
                "a local in-memory dry-run validates plan semantics before Neo4j is configured."
            ),
        ),
        "neo4j_payload_export": _capability(
            "ready"
            if neo4j_import.get("payload_export_ready")
            else "degraded",
            evidence={
                "payload_export_ready": neo4j_import.get("payload_export_ready"),
                "payload_format": neo4j_import.get("payload_format"),
                "payload_node_count": neo4j_import.get("payload_node_count"),
                "payload_structural_edge_count": neo4j_import.get("payload_structural_edge_count"),
                "payload_peer_edge_count": neo4j_import.get("payload_peer_edge_count"),
                "payload_statement_count": neo4j_import.get("payload_statement_count"),
                "payload_export_endpoint": neo4j_import.get("payload_export_endpoint"),
                "payload_dry_run_cli": neo4j_import.get("payload_dry_run_cli"),
            },
            detail="Ready means GraphRAG can produce parameterized Neo4j Cypher payloads without requiring a live Neo4j connection.",
        ),
        "neo4j_import": _capability(
            _neo4j_import_capability_status(neo4j_import),
            evidence=neo4j_import,
            detail="External Neo4j import is ready only when URI, dependency, auth, and connection checks are available.",
        ),
        "graphrag_live_cypher_query": _capability(
            "ready"
            if neo4j_import.get("ready")
            and graph_status.get("agentic_cypher_planner_enabled")
            else "degraded",
            evidence={
                "endpoint": graph_status.get("agentic_cypher_live_query_endpoint"),
                "external_dependency": graph_status.get(
                    "agentic_cypher_live_query_external_dependency"
                ),
                "neo4j_ready": neo4j_import.get("ready"),
                "planner_enabled": graph_status.get("agentic_cypher_planner_enabled"),
                "local_dry_run_enabled": graph_status.get(
                    "agentic_cypher_local_dry_run_enabled"
                ),
                "local_dry_run_status": graph_status.get(
                    "agentic_cypher_local_dry_run_status"
                ),
                "local_dry_run_row_count": graph_status.get(
                    "agentic_cypher_local_dry_run_row_count"
                ),
                "plan_validation": (graph_status.get("agentic_cypher_plan_example") or {}).get(
                    "validation"
                ),
                "payload_dry_run_cli": neo4j_import.get("payload_dry_run_cli"),
                "smoke_cli": neo4j_import.get("smoke_cli"),
                "import_smoke_cli": neo4j_import.get("import_smoke_cli"),
            },
            detail=(
                "Live GraphRAG Cypher execution only runs server-generated guarded plans; "
                "without Neo4j it remains available as a validated plan plus clear degraded status."
            ),
        ),
    }
