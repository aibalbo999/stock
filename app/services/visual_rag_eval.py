from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VisualRAGGoldenCase:
    case_id: str
    description: str
    required_fragments: tuple[str, ...] = ()
    required_table_rows: tuple[str, ...] = ()
    forbidden_fragments: tuple[str, ...] = ()


def load_visual_rag_golden_cases(path: str | Path) -> list[VisualRAGGoldenCase]:
    cases: list[VisualRAGGoldenCase] = []
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
            raise ValueError(f"invalid Visual RAG golden JSONL at line {line_number}: {exc}") from exc
        cases.append(_golden_case_from_payload(payload, line_number=line_number))
    return cases


def evaluate_visual_rag_text(case: VisualRAGGoldenCase, text: str) -> dict:
    normalized_text = _normalize_text(text)
    required = [
        fragment
        for fragment in case.required_fragments
        if _normalize_text(fragment) not in normalized_text
    ]
    missing_rows = [
        row
        for row in case.required_table_rows
        if _normalize_table_row(row) not in _normalize_table_row(text)
    ]
    forbidden = [
        fragment
        for fragment in case.forbidden_fragments
        if _normalize_text(fragment) in normalized_text
    ]
    expected_count = len(case.required_fragments) + len(case.required_table_rows)
    matched_count = expected_count - len(required) - len(missing_rows)
    score = 1.0 if expected_count == 0 else max(0.0, matched_count / expected_count)
    return {
        "id": case.case_id,
        "description": case.description,
        "passed": not required and not missing_rows and not forbidden,
        "score": round(score, 4),
        "missing_required_fragments": required,
        "missing_table_rows": missing_rows,
        "forbidden_fragments_present": forbidden,
    }


def evaluate_visual_rag_outputs(cases: list[VisualRAGGoldenCase], outputs: dict[str, str]) -> dict:
    results = [evaluate_visual_rag_text(case, outputs.get(case.case_id, "")) for case in cases]
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


def load_visual_rag_result_outputs(path: str | Path) -> dict[str, str]:
    text = Path(path).read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            return _outputs_from_json_payload(payload)

    outputs: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid Visual RAG result JSONL at line {line_number}: {exc}") from exc
        if not isinstance(item, dict) or item.get("id") is None:
            raise ValueError(
                f"Visual RAG result JSONL at line {line_number} must contain id and text"
            )
        outputs[str(item["id"])] = str(item.get("text") or "")
    return outputs


def format_visual_rag_eval_summary(report: dict) -> str:
    lines = [
        (
            "Visual RAG eval: "
            f"{report['passed_count']}/{report['case_count']} cases passed, "
            f"score={report['score']:.4f}"
        )
    ]
    for result in report.get("results") or []:
        status = "PASS" if result.get("passed") else "FAIL"
        lines.append(f"- [{status}] {result['id']}: score={result['score']:.4f}")
        missing = result.get("missing_required_fragments") or []
        missing_rows = result.get("missing_table_rows") or []
        forbidden = result.get("forbidden_fragments_present") or []
        if missing:
            lines.append("  missing fragments: " + "; ".join(str(item) for item in missing))
        if missing_rows:
            lines.append("  missing table rows: " + "; ".join(str(item) for item in missing_rows))
        if forbidden:
            lines.append("  forbidden fragments: " + "; ".join(str(item) for item in forbidden))
    return "\n".join(lines)


def _outputs_from_json_payload(payload: Any) -> dict[str, str]:
    if isinstance(payload, dict) and all(isinstance(value, str) for value in payload.values()):
        return {str(key): value for key, value in payload.items()}
    if isinstance(payload, list):
        outputs = {}
        for item in payload:
            if isinstance(item, dict) and item.get("id") is not None:
                outputs[str(item["id"])] = str(item.get("text") or "")
        return outputs
    raise ValueError("Visual RAG result file must be a JSON object id->text or a list of {id,text} rows")


def _golden_case_from_payload(payload: dict[str, Any], *, line_number: int) -> VisualRAGGoldenCase:
    case_id = str(payload.get("id") or "").strip()
    if not case_id:
        raise ValueError(f"Visual RAG golden case at line {line_number} is missing id")
    return VisualRAGGoldenCase(
        case_id=case_id,
        description=str(payload.get("description") or case_id),
        required_fragments=tuple(str(item) for item in payload.get("required_fragments") or []),
        required_table_rows=tuple(str(item) for item in payload.get("required_table_rows") or []),
        forbidden_fragments=tuple(str(item) for item in payload.get("forbidden_fragments") or []),
    )


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def _normalize_table_row(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).casefold()
