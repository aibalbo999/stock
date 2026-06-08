from __future__ import annotations

import argparse
import json
from typing import Any

from app.services.supply_chain_graph_api import SupplyChainGraphApiService


DEFAULT_TICKERS = "2330"
DEFAULT_TARGET_TICKER = "2382"
DEFAULT_TOPIC = "AI 伺服器"
DEFAULT_QUESTION = "上下游衝擊"
SMOKE_COMMAND = (
    ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
    "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json"
)
IMPORT_SMOKE_COMMAND = (
    ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
    "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 --import-first --json"
)
LOCAL_CONTRACT_SMOKE_COMMAND = (
    ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
    "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 --local-contract --json"
)


def neo4j_graphrag_smoke_report(
    *,
    tickers: str = DEFAULT_TICKERS,
    target_ticker: str = DEFAULT_TARGET_TICKER,
    topic: str = DEFAULT_TOPIC,
    question: str = DEFAULT_QUESTION,
    max_depth: int = 3,
    max_records: int = 8,
    use_llm: bool = False,
    import_first: bool = False,
    service: SupplyChainGraphApiService | None = None,
) -> dict[str, Any]:
    graph_service = service or SupplyChainGraphApiService()
    payload = graph_service.graph_neo4j_payload(tickers)
    payload_summary = neo4j_payload_summary(payload)
    import_result = None
    if import_first:
        import_result = graph_service.import_graph_to_neo4j(tickers)
        if import_result.get("status") != "imported":
            return build_smoke_report(
                status=neo4j_import_failure_status(import_result),
                ready=False,
                tickers=tickers,
                target_ticker=target_ticker,
                topic=topic,
                question=question,
                payload=payload_summary,
                import_result=import_result,
                query_result=None,
                remediation="Neo4j import smoke failed before read-only query execution.",
            )

    query_result = graph_service.graph_cypher_query(
        tickers,
        target_ticker=target_ticker,
        topic=topic,
        question=question,
        max_depth=max_depth,
        use_llm=use_llm,
        max_records=max_records,
    )
    execution = query_result.get("execution") if isinstance(query_result.get("execution"), dict) else {}
    execution_status = str(execution.get("status") or "unknown")
    plan = query_result.get("plan") if isinstance(query_result.get("plan"), dict) else {}
    plan_validation = plan.get("validation") if isinstance(plan.get("validation"), dict) else {}
    plan_ready = bool(plan and plan_validation.get("valid") is True)

    if not payload_summary["ready"]:
        status = "payload_degraded"
        ready = False
        remediation = "GraphRAG Neo4j payload is incomplete; inspect /supply-chain/graph/neo4j output."
    elif execution_status == "executed" and plan_ready:
        status = "ready"
        ready = True
        remediation = None
    elif execution_status == "not_configured":
        status = "not_configured"
        ready = False
        remediation = "Configure NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD and start Neo4j."
    elif execution_status == "dependency_missing":
        status = "dependency_missing"
        ready = False
        remediation = "Install the neo4j Python driver with pip install -e \".[graph]\"."
    elif execution_status == "rejected":
        status = "rejected"
        ready = False
        remediation = "Guarded Cypher plan was rejected before execution; inspect validation errors."
    elif execution_status == "query_failed":
        status = "failed"
        ready = False
        remediation = "Neo4j read-only query failed; inspect connection, auth, database, and graph import state."
    else:
        status = "degraded"
        ready = False
        remediation = "Neo4j live query smoke did not execute cleanly; inspect query execution payload."

    return build_smoke_report(
        status=status,
        ready=ready,
        tickers=tickers,
        target_ticker=target_ticker,
        topic=topic,
        question=question,
        payload=payload_summary,
        import_result=import_result,
        query_result=summarize_query_result(query_result),
        remediation=remediation,
    )


def neo4j_graphrag_local_contract_report(
    *,
    tickers: str = DEFAULT_TICKERS,
    target_ticker: str = DEFAULT_TARGET_TICKER,
    topic: str = DEFAULT_TOPIC,
    question: str = DEFAULT_QUESTION,
    max_depth: int = 3,
    use_llm: bool = False,
    service: SupplyChainGraphApiService | None = None,
) -> dict[str, Any]:
    graph_service = service or SupplyChainGraphApiService()
    payload = graph_service.graph_neo4j_payload(tickers)
    payload_summary = neo4j_payload_summary(payload)
    plan_payload = graph_service.graph_cypher_plan(
        tickers,
        target_ticker=target_ticker,
        topic=topic,
        question=question,
        max_depth=max_depth,
        use_llm=use_llm,
        include_dry_run=True,
    )
    query_result = summarize_query_result(plan_payload) or {}
    query_result.pop("execution", None)
    plan = query_result.get("plan") if isinstance(query_result, dict) else {}
    plan_validation = plan.get("validation") if isinstance(plan, dict) else {}
    local_dry_run = (
        query_result.get("local_dry_run")
        if isinstance(query_result.get("local_dry_run"), dict)
        else {}
    )
    local_validation = (
        local_dry_run.get("validation")
        if isinstance(local_dry_run.get("validation"), dict)
        else {}
    )
    plan_ready = bool(plan_validation.get("valid") and plan_validation.get("read_only"))
    local_ready = bool(
        local_dry_run.get("ready")
        and local_dry_run.get("status") == "executed_dry_run"
        and local_validation.get("valid")
        and local_validation.get("read_only")
    )
    ready = bool(payload_summary["ready"] and plan_ready and local_ready)
    if ready:
        status = "ready"
        remediation = None
    elif not payload_summary["ready"]:
        status = "payload_degraded"
        remediation = "GraphRAG Neo4j payload is incomplete; inspect /supply-chain/graph/neo4j output."
    elif not plan_ready:
        status = "plan_degraded"
        remediation = "Guarded Cypher plan is missing or failed read-only validation."
    else:
        status = "local_dry_run_degraded"
        remediation = "Local in-memory Cypher dry-run failed; inspect the plan and graph whitelist data."

    return build_smoke_report(
        status=status,
        ready=ready,
        tickers=tickers,
        target_ticker=target_ticker,
        topic=topic,
        question=question,
        payload=payload_summary,
        import_result=None,
        query_result=query_result,
        remediation=remediation,
        local_contract=True,
    )


def neo4j_payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    parameters = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
    nodes = parameters.get("nodes") if isinstance(parameters.get("nodes"), list) else []
    structural_edges = (
        parameters.get("structural_edges")
        if isinstance(parameters.get("structural_edges"), list)
        else []
    )
    peer_edges = parameters.get("peer_edges") if isinstance(parameters.get("peer_edges"), list) else []
    statements = payload.get("statements") if isinstance(payload.get("statements"), list) else []
    ready = bool(
        payload.get("format") == "neo4j_cypher_v1"
        and statements
        and nodes
    )
    return {
        "ready": ready,
        "format": payload.get("format"),
        "node_count": len(nodes),
        "structural_edge_count": len(structural_edges),
        "peer_edge_count": len(peer_edges),
        "statement_count": len(statements),
    }


def summarize_query_result(query_result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not query_result:
        return None
    execution = query_result.get("execution") if isinstance(query_result.get("execution"), dict) else {}
    local_dry_run = (
        query_result.get("local_dry_run")
        if isinstance(query_result.get("local_dry_run"), dict)
        else {}
    )
    plan = query_result.get("plan") if isinstance(query_result.get("plan"), dict) else {}
    validation = plan.get("validation") if isinstance(plan.get("validation"), dict) else {}
    return {
        "strategy": query_result.get("strategy"),
        "planner": query_result.get("planner"),
        "plan": {
            "intent": plan.get("intent"),
            "source": plan.get("source"),
            "validation": validation,
            "cypher": plan.get("cypher"),
            "parameters": plan.get("parameters") if isinstance(plan.get("parameters"), dict) else {},
        },
        "execution": {
            "status": execution.get("status"),
            "row_count": execution.get("row_count"),
            "record_limit": execution.get("record_limit"),
            "validation": execution.get("validation"),
            "neo4j": execution.get("neo4j"),
            "error": execution.get("error"),
        },
        "local_dry_run": {
            "status": local_dry_run.get("status"),
            "ready": local_dry_run.get("ready"),
            "execution_mode": local_dry_run.get("execution_mode"),
            "row_count": local_dry_run.get("row_count"),
            "validation": local_dry_run.get("validation"),
            "evidence_policy": local_dry_run.get("evidence_policy"),
        },
    }


def neo4j_import_failure_status(import_result: dict[str, Any]) -> str:
    status = str(import_result.get("status") or "")
    if status == "not_configured":
        return "not_configured"
    if status == "dependency_missing":
        return "dependency_missing"
    if status == "import_failed":
        return "failed"
    return "degraded"


def build_smoke_report(
    *,
    status: str,
    ready: bool,
    tickers: str,
    target_ticker: str,
    topic: str,
    question: str,
    payload: dict[str, Any],
    import_result: dict[str, Any] | None,
    query_result: dict[str, Any] | None,
    remediation: str | None,
    local_contract: bool = False,
) -> dict[str, Any]:
    return {
        "status": status,
        "ready": ready,
        "local_contract": local_contract,
        "request": {
            "tickers": tickers,
            "target_ticker": target_ticker,
            "topic": topic,
            "question": question,
        },
        "payload": payload,
        "import_first": import_result is not None,
        "import_result": import_result,
        "query_result": query_result,
        "smoke_command": SMOKE_COMMAND,
        "import_smoke_command": IMPORT_SMOKE_COMMAND,
        "local_contract_command": LOCAL_CONTRACT_SMOKE_COMMAND,
        "remediation": remediation,
    }


def format_neo4j_graphrag_smoke(report: dict[str, Any]) -> str:
    payload = report.get("payload") or {}
    query = report.get("query_result") or {}
    execution = query.get("execution") if isinstance(query.get("execution"), dict) else {}
    local_dry_run = query.get("local_dry_run") if isinstance(query.get("local_dry_run"), dict) else {}
    title = (
        "Neo4j GraphRAG local contract"
        if report.get("local_contract")
        else "Neo4j GraphRAG smoke"
    )
    lines = [
        f"{title}: {report['status']}",
        f"- ready: {str(bool(report.get('ready'))).lower()}",
        (
            "- payload: "
            f"{payload.get('node_count', 0)} nodes, "
            f"{payload.get('structural_edge_count', 0)} structural edges, "
            f"{payload.get('peer_edge_count', 0)} peer edges"
        ),
    ]
    if execution:
        lines.append(
            "- live query: "
            f"{execution.get('status')} "
            f"({execution.get('row_count', 0) or 0} rows)"
        )
    if local_dry_run:
        lines.append(
            "- local dry-run: "
            f"{local_dry_run.get('status')} "
            f"({local_dry_run.get('row_count', 0) or 0} rows)"
        )
    if report.get("import_result"):
        lines.append(f"- import: {report['import_result'].get('status')}")
    if report.get("remediation"):
        lines.append(f"- remediation: {report['remediation']}")
    lines.append(f"- command: {report['smoke_command']}")
    lines.append(f"- local contract command: {report['local_contract_command']}")
    lines.append(f"- import command: {report['import_smoke_command']}")
    return "\n".join(lines)


def smoke_exit_code(report: dict[str, Any], *, strict: bool = False) -> int:
    if report.get("ready"):
        return 0
    if strict:
        return 1
    return 0 if report.get("status") == "not_configured" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-test Neo4j GraphRAG payload export and guarded read-only Cypher execution."
    )
    parser.add_argument("--tickers", default=DEFAULT_TICKERS, help="Comma-separated source tickers.")
    parser.add_argument("--target-ticker", default=DEFAULT_TARGET_TICKER, help="Optional target ticker.")
    parser.add_argument("--topic", default=DEFAULT_TOPIC, help="Topic context for the guarded Cypher plan.")
    parser.add_argument("--question", default=DEFAULT_QUESTION, help="Question context for the guarded Cypher plan.")
    parser.add_argument("--max-depth", type=int, default=3, help="Maximum graph traversal depth.")
    parser.add_argument("--max-records", type=int, default=8, help="Maximum live query records to return.")
    parser.add_argument("--use-llm", action="store_true", help="Allow LLM-generated Cypher plan before validation.")
    parser.add_argument("--import-first", action="store_true", help="Import the current graph into Neo4j before querying.")
    parser.add_argument(
        "--local-contract",
        action="store_true",
        help="Validate payload export, guarded Cypher plan, and local dry-run without live Neo4j.",
    )
    parser.add_argument("--strict", action="store_true", help="Return non-zero when not ready.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.local_contract:
        report = neo4j_graphrag_local_contract_report(
            tickers=args.tickers,
            target_ticker=args.target_ticker,
            topic=args.topic,
            question=args.question,
            max_depth=args.max_depth,
            use_llm=bool(args.use_llm),
        )
    else:
        report = neo4j_graphrag_smoke_report(
            tickers=args.tickers,
            target_ticker=args.target_ticker,
            topic=args.topic,
            question=args.question,
            max_depth=args.max_depth,
            max_records=args.max_records,
            use_llm=bool(args.use_llm),
            import_first=bool(args.import_first),
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_neo4j_graphrag_smoke(report))
    return smoke_exit_code(report, strict=bool(args.strict))


if __name__ == "__main__":
    raise SystemExit(main())
