from __future__ import annotations

import json
import subprocess
import sys

from app.services.visual_rag_eval import (
    evaluate_visual_rag_outputs,
    load_visual_rag_golden_cases,
    load_visual_rag_result_outputs,
)


def test_visual_rag_eval_scores_required_rows_and_forbidden_fragments(tmp_path) -> None:
    golden = tmp_path / "golden.jsonl"
    golden.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "case-a",
                        "description": "table case",
                        "required_fragments": ["營業收入", "毛利率"],
                        "required_table_rows": ["2025 Q4 | 1,250 | 42.1%"],
                        "forbidden_fragments": ["自行估算"],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "id": "case-b",
                        "required_fragments": ["AI 伺服器"],
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    cases = load_visual_rag_golden_cases(golden)
    report = evaluate_visual_rag_outputs(
        cases,
        {
            "case-a": "營業收入 | 毛利率\n2025 Q4 | 1,250 | 42.1%",
            "case-b": "沒有對應內容",
        },
    )

    assert report["case_count"] == 2
    assert report["passed_count"] == 1
    assert report["failed_count"] == 1
    assert report["score"] == 0.5
    assert report["results"][1]["missing_required_fragments"] == ["AI 伺服器"]


def test_load_visual_rag_result_outputs_accepts_jsonl(tmp_path) -> None:
    results = tmp_path / "results.jsonl"
    results.write_text(
        '{"id":"case-a","text":"營收表格"}\n{"id":"case-b","text":"KPI 圖表"}\n',
        encoding="utf-8",
    )

    assert load_visual_rag_result_outputs(results) == {
        "case-a": "營收表格",
        "case-b": "KPI 圖表",
    }


def test_evaluate_visual_rag_cli_uses_fail_under_threshold(tmp_path) -> None:
    golden = tmp_path / "golden.jsonl"
    golden.write_text(
        '{"id":"case-a","required_fragments":["營業收入"],"required_table_rows":["2025 | 100"]}\n',
        encoding="utf-8",
    )
    results = tmp_path / "results.json"
    results.write_text('{"case-a":"營業收入\\n2025 | 100"}', encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/evaluate_visual_rag.py",
            "--golden",
            str(golden),
            "--results",
            str(results),
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
    assert payload["threshold_passed"] is True


def test_default_visual_rag_golden_set_covers_complex_pdf_patterns() -> None:
    cases = load_visual_rag_golden_cases("data/visual_rag_golden.jsonl")
    case_ids = {case.case_id for case in cases}

    assert len(cases) >= 9
    assert "cross_page_income_statement" in case_ids
    assert "merged_header_balance_sheet" in case_ids
    assert "chart_callout_guidance" in case_ids
    assert "scanned_page_ocr_disclosure" in case_ids
    assert "nested_segment_currency_table" in case_ids
    assert "cross_page_cash_flow_statement" in case_ids
    assert all(case.required_fragments or case.required_table_rows for case in cases)
