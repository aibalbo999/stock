from __future__ import annotations

from app.services.supply_chain_graph_cypher import GraphCypherPlannerService
from app.services.supply_chain_graph_neo4j import Neo4jGraphImportService
from app.services.whitelist import SupplyChainWhitelist


def supply_chain_graph_status() -> dict:
    try:
        graph = SupplyChainWhitelist().graph()
        neo4j_payload = graph.neo4j_import_payload()
        sample_ticker = graph.nodes[0].ticker if graph.nodes else ""
        retrieval_plan = graph.retrieval_plan([sample_ticker], topic="AI 產業鏈") if sample_ticker else {}
        reasoning_plan = graph.reasoning_plan([sample_ticker], topic="AI 產業鏈") if sample_ticker else {}
        cypher_plan = (
            GraphCypherPlannerService().plan(
                graph,
                tickers=[sample_ticker],
                topic="AI 產業鏈",
                question="分析上游供應衝擊",
            )
            if sample_ticker
            else {}
        )
        cypher_dry_run = (
            GraphCypherPlannerService().dry_run(graph, cypher_plan.get("plan") or {})
            if cypher_plan.get("plan")
            else {}
        )
        reasoning_examples = next(
            iter((reasoning_plan.get("paths_by_ticker") or {}).values()),
            [],
        )
        cypher_templates = reasoning_plan.get("cypher_templates") or {}
        neo4j_import = {
            **Neo4jGraphImportService().status(),
            "payload_export_ready": bool(
                neo4j_payload.get("format") == "neo4j_cypher_v1"
                and neo4j_payload.get("statements")
                and neo4j_payload.get("parameters", {}).get("nodes")
            ),
            "payload_format": neo4j_payload.get("format"),
            "payload_node_count": len(neo4j_payload.get("parameters", {}).get("nodes") or []),
            "payload_structural_edge_count": len(
                neo4j_payload.get("parameters", {}).get("structural_edges") or []
            ),
            "payload_peer_edge_count": len(neo4j_payload.get("parameters", {}).get("peer_edges") or []),
            "payload_statement_count": len(neo4j_payload.get("statements") or []),
            "payload_export_endpoint": "GET /supply-chain/graph/neo4j",
            "payload_dry_run_cli": ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run",
        }
        return {
            "collector_path": "app/services/status_graphrag.py",
            "enabled": True,
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "edge_confidence": "taxonomy",
            "query_expansion_enabled": True,
            "retrieval_hints_enabled": True,
            "retrieval_query_plan_enabled": bool(retrieval_plan.get("queries_by_ticker")),
            "retrieval_query_strategy": retrieval_plan.get("strategy"),
            "retrieval_evidence_policy": retrieval_plan.get("evidence_policy"),
            "retrieval_query_example": next(
                iter((retrieval_plan.get("queries_by_ticker") or {}).values()),
                [],
            )[:2],
            "path_reasoning_enabled": bool(reasoning_plan.get("paths_by_ticker")),
            "shortest_path_context_enabled": bool(reasoning_plan.get("context")),
            "path_reasoning_strategy": reasoning_plan.get("strategy"),
            "path_reasoning_evidence_policy": reasoning_plan.get("evidence_policy"),
            "path_reasoning_example": reasoning_examples[:2],
            "path_reasoning_endpoint": "GET /supply-chain/graph/reasoning",
            "neo4j_shortest_path_template": cypher_templates.get(
                "shortest_path_between_companies"
            ),
            "agentic_cypher_planner_enabled": bool(cypher_plan.get("plan")),
            "agentic_cypher_strategy": cypher_plan.get("strategy"),
            "agentic_cypher_endpoint": "GET /supply-chain/graph/cypher-plan",
            "agentic_cypher_live_query_endpoint": "GET /supply-chain/graph/cypher-query",
            "agentic_cypher_live_query_external_dependency": "Neo4j",
            "agentic_cypher_guardrails": cypher_plan.get("allowed_schema"),
            "agentic_cypher_plan_example": cypher_plan.get("plan"),
            "agentic_cypher_local_dry_run_enabled": cypher_dry_run.get("ready"),
            "agentic_cypher_local_dry_run_status": cypher_dry_run.get("status"),
            "agentic_cypher_local_dry_run_mode": cypher_dry_run.get("execution_mode"),
            "agentic_cypher_local_dry_run_row_count": cypher_dry_run.get("row_count"),
            "agentic_cypher_local_dry_run_evidence_policy": cypher_dry_run.get(
                "evidence_policy"
            ),
            "agentic_cypher_local_dry_run_example": cypher_dry_run,
            "prompt_context_enabled": True,
            "neo4j_export_enabled": True,
            "neo4j_import": neo4j_import,
            "purpose": "GraphRAG context for structural upstream/downstream retrieval, not direct supplier proof.",
        }
    except Exception as exc:
        return {
            "collector_path": "app/services/status_graphrag.py",
            "enabled": False,
            "error": str(exc),
        }


def _neo4j_import_capability_status(status: dict) -> str:
    if status.get("ready"):
        return "ready"
    if status.get("payload_export_ready"):
        return "degraded"
    if not status.get("configured"):
        return "not_configured"
    return "degraded"
