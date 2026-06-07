from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.services.llm_client import LLMClient
from app.services.supply_chain_graph import SupplyChainGraph


AGENTIC_CYPHER_STRATEGY = "guarded_llm_cypher_planner"
ALLOWED_NODE_LABELS = {"Company"}
ALLOWED_RELATIONSHIP_TYPES = {"STRUCTURAL_UPSTREAM_TO", "SAME_SEGMENT_PEER"}
WRITE_OR_PROCEDURE_KEYWORDS = {
    "ALTER",
    "CALL",
    "CREATE",
    "DELETE",
    "DENY",
    "DETACH",
    "DROP",
    "GRANT",
    "LOAD",
    "MERGE",
    "REMOVE",
    "REVOKE",
    "SET",
    "TERMINATE",
    "UNWIND",
}
DISALLOWED_CLAUSE_KEYWORDS = {
    "EXPLAIN",
    "FOREACH",
    "OPTIONAL",
    "PROFILE",
    "SHOW",
    "START",
    "UNION",
    "USE",
    "USING",
    "WHEN",
    "WHERE",
    "WITH",
}
DEFAULT_AGENTIC_CYPHER_EVIDENCE_POLICY = (
    "LLM-generated Cypher is accepted only after read-only validation. "
    "Returned graph paths remain structural hypotheses and must be corroborated by filings, "
    "news, revenue, or financial metrics before becoming investment evidence."
)
LOCAL_DRY_RUN_EVIDENCE_POLICY = (
    "In-memory dry-run executes the validated Cypher plan against the taxonomy graph only. "
    "It proves planner semantics and local path availability, but production live reads still "
    "require Neo4j plus source corroboration."
)


@dataclass(frozen=True)
class GuardedCypherPlan:
    intent: str
    cypher: str
    parameters: dict[str, Any]
    rationale: str
    source: str
    validation: dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "cypher": self.cypher,
            "parameters": self.parameters,
            "rationale": self.rationale,
            "source": self.source,
            "validation": self.validation,
        }


class GraphCypherPlannerService:
    def __init__(
        self,
        *,
        llm_client_factory: type[LLMClient] | None = None,
    ) -> None:
        self.llm_client_factory = llm_client_factory or LLMClient

    def plan(
        self,
        graph: SupplyChainGraph,
        *,
        tickers: list[str] | None = None,
        target_ticker: str = "",
        topic: str = "",
        question: str = "",
        max_depth: int = 3,
        use_llm: bool = False,
    ) -> dict:
        requested_tickers = [ticker for ticker in tickers or [] if ticker]
        source_ticker = requested_tickers[0] if requested_tickers else ""
        safe_depth = max(1, min(4, int(max_depth)))
        deterministic = self._deterministic_plan(
            source_ticker=source_ticker,
            target_ticker=target_ticker,
            topic=topic,
            question=question,
            max_depth=safe_depth,
        )
        validation = validate_graph_cypher_plan(deterministic, graph, max_depth=safe_depth)
        plan = GuardedCypherPlan(
            intent=deterministic["intent"],
            cypher=deterministic["cypher"],
            parameters=deterministic["parameters"],
            rationale=deterministic["rationale"],
            source="deterministic_template",
            validation=validation,
        )
        llm_payload: dict[str, Any] = {"attempted": False, "used": False}

        if use_llm:
            llm_payload = self._llm_plan(
                graph,
                deterministic=deterministic,
                source_ticker=source_ticker,
                target_ticker=target_ticker,
                topic=topic,
                question=question,
                max_depth=safe_depth,
            )
            if llm_payload.get("used") and isinstance(llm_payload.get("plan"), GuardedCypherPlan):
                plan = llm_payload["plan"]

        return {
            "strategy": AGENTIC_CYPHER_STRATEGY,
            "planner": "llm_guarded" if llm_payload.get("used") else "deterministic_guarded",
            "requested_tickers": requested_tickers,
            "target_ticker": target_ticker,
            "topic": topic,
            "question": question,
            "max_depth": safe_depth,
            "allowed_schema": {
                "labels": sorted(ALLOWED_NODE_LABELS),
                "relationship_types": sorted(ALLOWED_RELATIONSHIP_TYPES),
                "operations": ["MATCH", "RETURN", "ORDER BY", "LIMIT"],
            },
            "evidence_policy": DEFAULT_AGENTIC_CYPHER_EVIDENCE_POLICY,
            "plan": plan.to_dict(),
            "llm": _serializable_llm_payload(llm_payload),
            "prompt": build_cypher_planner_prompt(
                graph,
                source_ticker=source_ticker,
                target_ticker=target_ticker,
                topic=topic,
                question=question,
                max_depth=safe_depth,
            ),
        }

    def dry_run(
        self,
        graph: SupplyChainGraph,
        plan: dict,
        *,
        max_records: int = 25,
    ) -> dict:
        safe_limit = max(1, min(int(max_records or 25), 100))
        validation = validate_graph_cypher_plan(
            plan,
            graph,
            max_depth=_max_depth_from_plan(plan),
        )
        if not validation["valid"]:
            return {
                "status": "validation_failed",
                "ready": False,
                "dry_run": True,
                "execution_mode": "in_memory_graph",
                "validation": validation,
                "rows": [],
                "row_count": 0,
                "evidence_policy": LOCAL_DRY_RUN_EVIDENCE_POLICY,
            }
        rows = _dry_run_rows_for_plan(graph, plan, limit=safe_limit)
        return {
            "status": "executed_dry_run",
            "ready": True,
            "dry_run": True,
            "execution_mode": "in_memory_graph",
            "intent": str(plan.get("intent") or ""),
            "validation": validation,
            "rows": rows,
            "row_count": len(rows),
            "max_records": safe_limit,
            "evidence_policy": LOCAL_DRY_RUN_EVIDENCE_POLICY,
        }

    def _llm_plan(
        self,
        graph: SupplyChainGraph,
        *,
        deterministic: dict,
        source_ticker: str,
        target_ticker: str,
        topic: str,
        question: str,
        max_depth: int,
    ) -> dict:
        prompt = build_cypher_planner_prompt(
            graph,
            source_ticker=source_ticker,
            target_ticker=target_ticker,
            topic=topic,
            question=question,
            max_depth=max_depth,
        )
        result = self.llm_client_factory().generate_with_metadata(prompt)
        payload: dict[str, Any] = {
            "attempted": True,
            "used": False,
            "fallback_reason": None,
            "model": result.model,
            "provider": result.provider,
            "observability": result.observability,
        }
        if result.fallback or not result.text.strip():
            payload["fallback_reason"] = "llm_unavailable_or_empty"
            return payload
        try:
            candidate = parse_llm_cypher_json(result.text)
        except ValueError as exc:
            payload["fallback_reason"] = f"invalid_llm_json:{exc}"
            return payload
        validation = validate_graph_cypher_plan(candidate, graph, max_depth=max_depth)
        if not validation["valid"]:
            payload["fallback_reason"] = "llm_cypher_validation_failed"
            payload["validation_errors"] = validation["errors"]
            payload["rejected_plan"] = candidate
            return payload
        payload["used"] = True
        payload["fallback_reason"] = None
        payload["plan"] = GuardedCypherPlan(
            intent=str(candidate.get("intent") or deterministic["intent"]),
            cypher=str(candidate.get("cypher") or deterministic["cypher"]),
            parameters=dict(candidate.get("parameters") or deterministic["parameters"]),
            rationale=str(candidate.get("rationale") or "LLM generated a validated Cypher plan."),
            source="llm_validated",
            validation=validation,
        )
        return payload

    @staticmethod
    def _deterministic_plan(
        *,
        source_ticker: str,
        target_ticker: str,
        topic: str,
        question: str,
        max_depth: int,
    ) -> dict:
        if source_ticker and target_ticker:
            return {
                "intent": "shortest_path_between_companies",
                "cypher": (
                    "MATCH path = shortestPath("
                    f"(source:Company {{ticker: $source_ticker}})-[*..{max_depth}]-"
                    "(target:Company {ticker: $target_ticker})"
                    ") RETURN path LIMIT $limit"
                ),
                "parameters": {
                    "source_ticker": source_ticker,
                    "target_ticker": target_ticker,
                    "limit": 8,
                },
                "rationale": "Default to shortest-path impact context when source and target tickers are provided.",
            }
        if "同業" in question or "peer" in question.lower():
            return {
                "intent": "same_segment_peers",
                "cypher": (
                    "MATCH (company:Company {ticker: $ticker})-[:SAME_SEGMENT_PEER]-"
                    "(peer:Company) RETURN company, peer ORDER BY peer.ticker LIMIT $limit"
                ),
                "parameters": {"ticker": source_ticker, "limit": 12},
                "rationale": "Question asks for same-segment comparison.",
            }
        if "下游" in question or "demand" in question.lower() or "customer" in question.lower():
            return {
                "intent": "downstream_demand_path",
                "cypher": (
                    "MATCH (source:Company {ticker: $ticker})-"
                    f"[:STRUCTURAL_UPSTREAM_TO*1..{max_depth}]->(customer:Company) "
                    "RETURN source, customer ORDER BY customer.ticker LIMIT $limit"
                ),
                "parameters": {"ticker": source_ticker, "limit": 12},
                "rationale": "Question asks for downstream demand or customer impact.",
            }
        return {
            "intent": "upstream_supply_path",
            "cypher": (
                "MATCH (supplier:Company)-"
                f"[:STRUCTURAL_UPSTREAM_TO*1..{max_depth}]->"
                "(target:Company {ticker: $ticker}) "
                "RETURN supplier, target ORDER BY supplier.ticker LIMIT $limit"
            ),
            "parameters": {"ticker": source_ticker, "limit": 12},
            "rationale": (
                "Default to upstream supply/cost context for "
                f"{topic or question or source_ticker}."
            ),
        }


def build_cypher_planner_prompt(
    graph: SupplyChainGraph,
    *,
    source_ticker: str,
    target_ticker: str,
    topic: str,
    question: str,
    max_depth: int,
) -> str:
    node_rows = [
        f"{node.ticker} {node.name} segment={node.segment_name}"
        for node in graph.nodes[:40]
    ]
    return (
        "你是受保護的 Neo4j Cypher planner。請只輸出 JSON，不要輸出 Markdown。"
        "目標是為台股 AI/機器人供應鏈 GraphRAG 產生 read-only Cypher。"
        "\n限制：只能使用 MATCH/RETURN/ORDER BY/LIMIT；只能使用 Company label；"
        "只能使用 STRUCTURAL_UPSTREAM_TO 或 SAME_SEGMENT_PEER 關係；"
        f"可變長路徑最大深度 {max_depth}；不可使用 CALL/CREATE/MERGE/SET/DELETE/LOAD。"
        "\n輸出 JSON schema："
        '{"intent": "...", "cypher": "...", "parameters": {...}, "rationale": "..."}'
        f"\nsource_ticker={source_ticker or '未指定'}"
        f"\ntarget_ticker={target_ticker or '未指定'}"
        f"\ntopic={topic or '未指定'}"
        f"\nquestion={question or '未指定'}"
        "\n可用公司：\n" + "\n".join(node_rows)
    )


def parse_llm_cypher_json(text: str) -> dict:
    candidate = (text or "").strip()
    candidate = re.sub(r"^```(?:json)?", "", candidate).strip()
    candidate = re.sub(r"```$", "", candidate).strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(exc.msg) from exc
    if not isinstance(payload, dict):
        raise ValueError("payload_must_be_object")
    return payload


def validate_graph_cypher_plan(plan: dict, graph: SupplyChainGraph, *, max_depth: int = 3) -> dict:
    cypher = str(plan.get("cypher") or "").strip()
    parameters = plan.get("parameters") if isinstance(plan.get("parameters"), dict) else {}
    errors: list[str] = []
    if not cypher.upper().startswith("MATCH "):
        errors.append("cypher_must_start_with_match")
    if ";" in cypher or "--" in cypher or "/*" in cypher:
        errors.append("cypher_must_not_contain_statement_separators_or_comments")
    upper_tokens = {token.upper() for token in re.findall(r"\b[A-Za-z_]+\b", cypher)}
    blocked = sorted(upper_tokens & WRITE_OR_PROCEDURE_KEYWORDS)
    if blocked:
        errors.append("blocked_keywords:" + ",".join(blocked))
    disallowed_clauses = sorted(upper_tokens & DISALLOWED_CLAUSE_KEYWORDS)
    if disallowed_clauses:
        errors.append("disallowed_clauses:" + ",".join(disallowed_clauses))
    if "$" not in cypher:
        errors.append("cypher_must_be_parameterized")
    labels = set(re.findall(r":([A-Za-z][A-Za-z0-9_]*)", cypher))
    rel_types = {label for label in labels if label.isupper()}
    node_labels = labels - rel_types
    unknown_labels = sorted(node_labels - ALLOWED_NODE_LABELS)
    unknown_rels = sorted(rel_types - ALLOWED_RELATIONSHIP_TYPES)
    if unknown_labels:
        errors.append("unknown_node_labels:" + ",".join(unknown_labels))
    if unknown_rels:
        errors.append("unknown_relationship_types:" + ",".join(unknown_rels))
    for depth in re.findall(r"\*\s*(?:\d+)?\.\.(\d+)", cypher):
        if int(depth) > max(1, min(4, int(max_depth))):
            errors.append("path_depth_exceeds_limit")
    ticker_values = {
        str(value)
        for key, value in parameters.items()
        if "ticker" in str(key) and value not in {None, ""}
    }
    known_tickers = {node.ticker for node in graph.nodes}
    unknown_tickers = sorted(ticker_values - known_tickers)
    if unknown_tickers:
        errors.append("unknown_ticker_parameters:" + ",".join(unknown_tickers))
    return {
        "valid": not errors,
        "errors": errors,
        "read_only": not any(error.startswith("blocked_keywords") for error in errors),
        "parameterized": "$" in cypher,
        "max_depth": max(1, min(4, int(max_depth))),
    }


def _dry_run_rows_for_plan(graph: SupplyChainGraph, plan: dict, *, limit: int) -> list[dict[str, Any]]:
    intent = str(plan.get("intent") or "").strip()
    parameters = plan.get("parameters") if isinstance(plan.get("parameters"), dict) else {}
    max_depth = _max_depth_from_plan(plan)
    if intent == "shortest_path_between_companies":
        paths = graph.shortest_paths(
            str(parameters.get("source_ticker") or ""),
            str(parameters.get("target_ticker") or ""),
            max_depth=max_depth,
            max_paths=limit,
        )
        return [_path_row(path) for path in paths[:limit]]
    if intent in {"upstream_supply_path", "downstream_demand_path"}:
        paths = graph.neighborhood_paths(
            str(parameters.get("ticker") or ""),
            max_depth=max_depth,
            max_paths=limit * 2,
        )
        expected_direction = (
            "upstream_impact_path"
            if intent == "upstream_supply_path"
            else "downstream_demand_path"
        )
        return [
            _path_row(path)
            for path in paths
            if path.get("impact_direction") == expected_direction
        ][:limit]
    if intent == "same_segment_peers":
        return _same_segment_peer_rows(
            graph,
            str(parameters.get("ticker") or ""),
            limit=limit,
        )
    return [
        _path_row(path)
        for path in graph.neighborhood_paths(
            str(parameters.get("ticker") or parameters.get("source_ticker") or ""),
            max_depth=max_depth,
            max_paths=limit,
        )
    ][:limit]


def _path_row(path: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "path",
        "path_label": path.get("path_label"),
        "path_tickers": path.get("path_tickers"),
        "hop_count": path.get("hop_count"),
        "impact_direction": path.get("impact_direction"),
        "impact_direction_label": path.get("impact_direction_label"),
        "path": path,
    }


def _same_segment_peer_rows(
    graph: SupplyChainGraph,
    ticker: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    nodes = {node.ticker: node.to_dict() for node in graph.nodes}
    rows = []
    for edge in graph.neighbor_edges(ticker):
        if edge.relation != "same_segment_peer":
            continue
        peer_ticker = edge.target_ticker if edge.source_ticker == ticker else edge.source_ticker
        rows.append(
            {
                "type": "peer",
                "company": nodes.get(ticker),
                "peer": nodes.get(peer_ticker),
                "edge": edge.to_dict(),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _max_depth_from_plan(plan: dict) -> int:
    cypher = str(plan.get("cypher") or "")
    depths = [int(depth) for depth in re.findall(r"\*\s*(?:\d+)?\.\.(\d+)", cypher)]
    return max(1, min(min(depths) if depths else 3, 6))


def _serializable_llm_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key != "plan"
    }
