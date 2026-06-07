from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.supply_chain_graph import SupplyChainGraph
from app.services.supply_chain_graph_cypher import (
    GraphCypherPlannerService,
    validate_graph_cypher_plan,
)
from app.services.whitelist import SupplyChainWhitelist


@dataclass(frozen=True)
class GraphRAGGoldenCase:
    case_id: str
    description: str
    mode: str = "reasoning"
    tickers: tuple[str, ...] = ()
    target_ticker: str = ""
    topic: str = ""
    question: str = ""
    max_depth: int = 3
    max_paths: int = 8
    required_context_fragments: tuple[str, ...] = ()
    forbidden_context_fragments: tuple[str, ...] = ()
    expected_path_tickers: tuple[str, ...] = ()
    expected_impact_direction: str = ""
    expected_no_path: bool = False
    expected_cypher_intent: str = ""
    expected_cypher_parameters: dict[str, Any] | None = None
    expected_validation_valid: bool | None = None
    expected_validation_read_only: bool | None = None
    expected_validation_errors: tuple[str, ...] = ()
    candidate_plan: dict[str, Any] | None = None


def load_graphrag_golden_cases(path: str | Path) -> list[GraphRAGGoldenCase]:
    cases: list[GraphRAGGoldenCase] = []
    for line_number, raw_line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid GraphRAG golden JSONL at line {line_number}: {exc}") from exc
        cases.append(_golden_case_from_payload(payload, line_number=line_number))
    return cases


def evaluate_graphrag_cases(
    cases: list[GraphRAGGoldenCase],
    *,
    graph: SupplyChainGraph | None = None,
) -> dict:
    resolved_graph = graph or SupplyChainWhitelist().graph()
    results = [evaluate_graphrag_case(case, graph=resolved_graph) for case in cases]
    passed = sum(1 for result in results if result["passed"])
    score = sum(float(result["score"]) for result in results) / len(results) if results else 1.0
    return {
        "case_count": len(results),
        "passed_count": passed,
        "failed_count": len(results) - passed,
        "score": round(score, 4),
        "passed": passed == len(results),
        "results": results,
    }


def evaluate_graphrag_case(case: GraphRAGGoldenCase, *, graph: SupplyChainGraph) -> dict:
    if case.mode == "guardrail":
        return _evaluate_guardrail_case(case, graph=graph)
    return _evaluate_reasoning_case(case, graph=graph)


def format_graphrag_eval_summary(report: dict) -> str:
    lines = [
        (
            "GraphRAG eval: "
            f"{report['passed_count']}/{report['case_count']} cases passed, "
            f"score={report['score']:.4f}"
        )
    ]
    for result in report.get("results") or []:
        status = "PASS" if result.get("passed") else "FAIL"
        lines.append(f"- [{status}] {result['id']}: score={result['score']:.4f}")
        for label, key in (
            ("missing context", "missing_context_fragments"),
            ("forbidden context", "forbidden_context_fragments_present"),
            ("missing path", "missing_path_tickers"),
            ("missing impact", "missing_impact_direction"),
            ("cypher mismatch", "cypher_mismatches"),
            ("missing validation errors", "missing_validation_errors"),
            ("validation mismatch", "validation_mismatches"),
        ):
            values = result.get(key) or []
            if values:
                lines.append(f"  {label}: " + "; ".join(str(item) for item in values))
    return "\n".join(lines)


def _evaluate_reasoning_case(case: GraphRAGGoldenCase, *, graph: SupplyChainGraph) -> dict:
    reasoning = graph.reasoning_plan(
        list(case.tickers),
        target_ticker=case.target_ticker,
        topic=case.topic,
        max_depth=case.max_depth,
        max_paths=case.max_paths,
    )
    plan = GraphCypherPlannerService().plan(
        graph,
        tickers=list(case.tickers),
        target_ticker=case.target_ticker,
        topic=case.topic,
        question=case.question,
        max_depth=case.max_depth,
        use_llm=False,
    )
    context = str(reasoning.get("context") or "")
    normalized_context = _normalize_text(context)
    missing_context = [
        fragment
        for fragment in case.required_context_fragments
        if _normalize_text(fragment) not in normalized_context
    ]
    forbidden_context = [
        fragment
        for fragment in case.forbidden_context_fragments
        if _normalize_text(fragment) in normalized_context
    ]
    flattened_paths = _flatten_paths(reasoning.get("paths_by_ticker") or {})
    missing_path = []
    if case.expected_path_tickers and not any(
        tuple(path.get("path_tickers") or ()) == case.expected_path_tickers
        for path in flattened_paths
    ):
        missing_path.append(" -> ".join(case.expected_path_tickers))
    missing_impact = []
    if case.expected_impact_direction and not any(
        path.get("impact_direction") == case.expected_impact_direction for path in flattened_paths
    ):
        missing_impact.append(case.expected_impact_direction)
    no_path_mismatch = bool(case.expected_no_path and flattened_paths)
    cypher_mismatches = _cypher_mismatches(case, plan.get("plan") or {})
    checks = (
        len(case.required_context_fragments)
        + len(case.forbidden_context_fragments)
        + int(bool(case.expected_path_tickers))
        + int(bool(case.expected_impact_direction))
        + int(case.expected_no_path)
        + len(cypher_mismatches["expected_checks"])
    )
    failures = (
        len(missing_context)
        + len(forbidden_context)
        + len(missing_path)
        + len(missing_impact)
        + int(no_path_mismatch)
        + len(cypher_mismatches["failed"])
    )
    score = 1.0 if checks == 0 else max(0.0, (checks - failures) / checks)
    return {
        "id": case.case_id,
        "description": case.description,
        "mode": case.mode,
        "passed": failures == 0,
        "score": round(score, 4),
        "missing_context_fragments": missing_context,
        "forbidden_context_fragments_present": forbidden_context,
        "missing_path_tickers": missing_path,
        "missing_impact_direction": missing_impact,
        "unexpected_paths_present": no_path_mismatch,
        "cypher_mismatches": cypher_mismatches["failed"],
        "path_count": len(flattened_paths),
        "planner": plan.get("planner"),
        "cypher_intent": (plan.get("plan") or {}).get("intent"),
        "validation": (plan.get("plan") or {}).get("validation"),
    }


def _evaluate_guardrail_case(case: GraphRAGGoldenCase, *, graph: SupplyChainGraph) -> dict:
    validation = validate_graph_cypher_plan(
        case.candidate_plan or {},
        graph,
        max_depth=case.max_depth,
    )
    expected_checks = (
        int(case.expected_validation_valid is not None)
        + int(case.expected_validation_read_only is not None)
        + len(case.expected_validation_errors)
    )
    missing_errors = [
        error for error in case.expected_validation_errors if error not in validation.get("errors", [])
    ]
    validation_mismatches: list[str] = []
    if (
        case.expected_validation_valid is not None
        and bool(validation.get("valid")) is not bool(case.expected_validation_valid)
    ):
        validation_mismatches.append(
            f"valid:{validation.get('valid')} != {case.expected_validation_valid}"
        )
    if (
        case.expected_validation_read_only is not None
        and bool(validation.get("read_only")) is not bool(case.expected_validation_read_only)
    ):
        validation_mismatches.append(
            f"read_only:{validation.get('read_only')} != {case.expected_validation_read_only}"
        )
    failures = len(missing_errors) + len(validation_mismatches)
    score = 1.0 if expected_checks == 0 else max(0.0, (expected_checks - failures) / expected_checks)
    return {
        "id": case.case_id,
        "description": case.description,
        "mode": case.mode,
        "passed": failures == 0,
        "score": round(score, 4),
        "validation": validation,
        "missing_validation_errors": missing_errors,
        "validation_mismatches": validation_mismatches,
    }


def _cypher_mismatches(case: GraphRAGGoldenCase, plan: dict[str, Any]) -> dict[str, list[str]]:
    failed: list[str] = []
    expected_checks: list[str] = []
    if case.expected_cypher_intent:
        expected_checks.append("expected_cypher_intent")
        if plan.get("intent") != case.expected_cypher_intent:
            failed.append(f"intent:{plan.get('intent')} != {case.expected_cypher_intent}")
    if case.expected_cypher_parameters:
        parameters = plan.get("parameters") if isinstance(plan.get("parameters"), dict) else {}
        for key, expected in case.expected_cypher_parameters.items():
            expected_checks.append(f"parameter:{key}")
            if parameters.get(key) != expected:
                failed.append(f"parameter:{key}:{parameters.get(key)} != {expected}")
    if case.expected_validation_valid is not None:
        expected_checks.append("validation_valid")
        validation = plan.get("validation") if isinstance(plan.get("validation"), dict) else {}
        if bool(validation.get("valid")) is not bool(case.expected_validation_valid):
            failed.append(f"validation_valid:{validation.get('valid')} != {case.expected_validation_valid}")
    if case.expected_validation_read_only is not None:
        expected_checks.append("validation_read_only")
        validation = plan.get("validation") if isinstance(plan.get("validation"), dict) else {}
        if bool(validation.get("read_only")) is not bool(case.expected_validation_read_only):
            failed.append(
                f"validation_read_only:{validation.get('read_only')} "
                f"!= {case.expected_validation_read_only}"
            )
    return {"failed": failed, "expected_checks": expected_checks}


def _flatten_paths(paths_by_ticker: dict[str, Any]) -> list[dict]:
    paths: list[dict] = []
    for ticker_paths in paths_by_ticker.values():
        if isinstance(ticker_paths, list):
            paths.extend(path for path in ticker_paths if isinstance(path, dict))
    return paths


def _golden_case_from_payload(payload: dict[str, Any], *, line_number: int) -> GraphRAGGoldenCase:
    case_id = str(payload.get("id") or "").strip()
    if not case_id:
        raise ValueError(f"GraphRAG golden case at line {line_number} is missing id")
    return GraphRAGGoldenCase(
        case_id=case_id,
        description=str(payload.get("description") or case_id),
        mode=str(payload.get("mode") or "reasoning"),
        tickers=tuple(str(item) for item in payload.get("tickers") or []),
        target_ticker=str(payload.get("target_ticker") or ""),
        topic=str(payload.get("topic") or ""),
        question=str(payload.get("question") or ""),
        max_depth=int(payload.get("max_depth") or 3),
        max_paths=int(payload.get("max_paths") or 8),
        required_context_fragments=tuple(
            str(item) for item in payload.get("required_context_fragments") or []
        ),
        forbidden_context_fragments=tuple(
            str(item) for item in payload.get("forbidden_context_fragments") or []
        ),
        expected_path_tickers=tuple(str(item) for item in payload.get("expected_path_tickers") or []),
        expected_impact_direction=str(payload.get("expected_impact_direction") or ""),
        expected_no_path=bool(payload.get("expected_no_path")),
        expected_cypher_intent=str(payload.get("expected_cypher_intent") or ""),
        expected_cypher_parameters=(
            dict(payload.get("expected_cypher_parameters"))
            if isinstance(payload.get("expected_cypher_parameters"), dict)
            else None
        ),
        expected_validation_valid=(
            bool(payload.get("expected_validation_valid"))
            if payload.get("expected_validation_valid") is not None
            else None
        ),
        expected_validation_read_only=(
            bool(payload.get("expected_validation_read_only"))
            if payload.get("expected_validation_read_only") is not None
            else None
        ),
        expected_validation_errors=tuple(
            str(item) for item in payload.get("expected_validation_errors") or []
        ),
        candidate_plan=(
            dict(payload.get("candidate_plan"))
            if isinstance(payload.get("candidate_plan"), dict)
            else None
        ),
    )


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()
