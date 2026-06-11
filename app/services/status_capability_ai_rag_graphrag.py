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
            detail="GraphRAG 可計算最短路徑衝擊脈絡給 LLM 推理使用，同時保留證據護欄。",
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
                "支援 LLM 產生 Cypher，但必須先通過受控 planner 驗證唯讀操作、label、"
                "relationship type、參數與路徑深度；Neo4j 尚未設定前，會用本機記憶體 "
                "dry-run 驗證查詢計畫語意。"
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
            detail="就緒代表 GraphRAG 可產生參數化 Neo4j Cypher 匯入 payload，不需要 live Neo4j 連線。",
        ),
        "neo4j_import": _capability(
            _neo4j_import_capability_status(neo4j_import),
            evidence=neo4j_import,
            detail="外部 Neo4j 匯入需 URI、依賴套件、認證與連線檢查都可用才算就緒。",
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
                "Live GraphRAG Cypher 執行只會跑伺服端產生且通過護欄的計畫；"
                "沒有 Neo4j 時仍會提供已驗證計畫與清楚的 degraded 狀態。"
            ),
        ),
    }
