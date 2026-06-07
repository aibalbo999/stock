from __future__ import annotations

import json
import subprocess
import sys

from app.services.graphrag_eval import (
    evaluate_graphrag_cases,
    load_graphrag_golden_cases,
)


def test_default_graphrag_golden_set_passes() -> None:
    cases = load_graphrag_golden_cases("data/graphrag_reasoning_golden.jsonl")
    report = evaluate_graphrag_cases(cases)

    assert report["case_count"] >= 13
    assert report["passed"] is True
    assert report["score"] == 1.0
    ids = {result["id"] for result in report["results"]}
    assert "thermal_to_odm_downstream_path" in ids
    assert "cowos_equipment_to_foundry_path" in ids
    assert "server_odm_peer_path" in ids
    assert "memory_peer_comparison_path" in ids
    assert "ccl_to_odm_downstream_path" in ids
    assert "copper_foil_to_odm_downstream_path" in ids
    assert "silicon_wafer_to_foundry_path" in ids
    assert "server_mechanics_to_odm_downstream_path" in ids
    assert "power_to_odm_downstream_path" in ids
    assert "thermal_peer_comparison_path" in ids
    assert "pcb_peer_comparison_path" in ids
    assert "no_path_keeps_context_warning" in ids
    assert "guardrail_rejects_write_cypher" in ids
    guardrail = next(
        result for result in report["results"] if result["id"] == "guardrail_rejects_write_cypher"
    )
    assert guardrail["validation"]["read_only"] is False


def test_graphrag_eval_reports_missing_guardrail_error(tmp_path) -> None:
    golden = tmp_path / "graphrag_bad.jsonl"
    golden.write_text(
        json.dumps(
            {
                "id": "bad-guardrail",
                "mode": "guardrail",
                "candidate_plan": {
                    "cypher": "MATCH (c:Company) DELETE c RETURN c",
                    "parameters": {},
                },
                "expected_validation_valid": False,
                "expected_validation_read_only": False,
                "expected_validation_errors": ["unknown_error_marker"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = evaluate_graphrag_cases(load_graphrag_golden_cases(golden))

    assert report["passed"] is False
    assert report["results"][0]["missing_validation_errors"] == ["unknown_error_marker"]


def test_graphrag_eval_reports_forbidden_path(tmp_path) -> None:
    golden = tmp_path / "graphrag_forbidden_path.jsonl"
    golden.write_text(
        json.dumps(
            {
                "id": "bad-forbidden-path",
                "tickers": ["3324"],
                "target_ticker": "2382",
                "expected_path_tickers": ["3324", "2382"],
                "forbidden_path_tickers": [["3324", "2382"]],
                "expected_validation_valid": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = evaluate_graphrag_cases(load_graphrag_golden_cases(golden))

    assert report["passed"] is False
    assert report["results"][0]["forbidden_path_tickers_present"] == ["3324 -> 2382"]


def test_evaluate_graphrag_reasoning_cli(tmp_path) -> None:
    golden = tmp_path / "graphrag.jsonl"
    golden.write_text(
        json.dumps(
            {
                "id": "thermal",
                "tickers": ["3324"],
                "target_ticker": "2382",
                "question": "上下游衝擊",
                "required_context_fragments": ["3324 雙鴻 -> 2382 廣達"],
                "expected_path_tickers": ["3324", "2382"],
                "expected_impact_direction": "downstream_demand_path",
                "expected_cypher_intent": "shortest_path_between_companies",
                "expected_cypher_parameters": {
                    "source_ticker": "3324",
                    "target_ticker": "2382",
                },
                "expected_validation_valid": True,
                "expected_validation_read_only": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/evaluate_graphrag_reasoning.py",
            "--golden",
            str(golden),
            "--fail-under",
            "1.0",
            "--json",
        ],
        check=False,
        cwd=".",
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["passed"] is True
    assert payload["threshold_passed"] is True
