from __future__ import annotations

import argparse
import json

from app.services.visual_rag_eval import (
    evaluate_visual_rag_outputs,
    format_visual_rag_eval_summary,
    load_visual_rag_golden_cases,
    load_visual_rag_result_outputs,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate Visual RAG extracted text against a golden set without calling an LLM."
    )
    parser.add_argument(
        "--golden",
        default="data/visual_rag_golden.jsonl",
        help="Golden JSONL file with id, required_fragments, required_table_rows, and forbidden_fragments.",
    )
    parser.add_argument(
        "--results",
        required=True,
        help="JSON object id->text, JSON list of {id,text}, or JSONL rows of {id,text}.",
    )
    parser.add_argument(
        "--fail-under",
        type=float,
        default=1.0,
        help="Fail when aggregate score is below this value.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    cases = load_visual_rag_golden_cases(args.golden)
    outputs = load_visual_rag_result_outputs(args.results)
    report = evaluate_visual_rag_outputs(cases, outputs)
    report["threshold"] = float(args.fail_under)
    report["threshold_passed"] = float(report["score"]) >= float(args.fail_under)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_visual_rag_eval_summary(report))
        if not report["threshold_passed"]:
            print(f"Score is below threshold: {report['score']:.4f} < {args.fail_under:.4f}")
    return 0 if report["passed"] and report["threshold_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
