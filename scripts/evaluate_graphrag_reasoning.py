from __future__ import annotations

import argparse
import json

from app.services.graphrag_eval import (
    evaluate_graphrag_cases,
    format_graphrag_eval_summary,
    load_graphrag_golden_cases,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate GraphRAG reasoning and guarded Cypher plans against a golden set."
    )
    parser.add_argument(
        "--golden",
        default="data/graphrag_reasoning_golden.jsonl",
        help="Golden JSONL file for GraphRAG reasoning and Cypher guardrail cases.",
    )
    parser.add_argument(
        "--fail-under",
        type=float,
        default=1.0,
        help="Fail when aggregate score is below this value.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    cases = load_graphrag_golden_cases(args.golden)
    report = evaluate_graphrag_cases(cases)
    report["threshold"] = float(args.fail_under)
    report["threshold_passed"] = float(report["score"]) >= float(args.fail_under)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_graphrag_eval_summary(report))
        if not report["threshold_passed"]:
            print(f"Score is below threshold: {report['score']:.4f} < {args.fail_under:.4f}")
    return 0 if report["passed"] and report["threshold_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
