from __future__ import annotations

from app.ui.task_status_panel import company_filing_gap_rows, task_status_diagnostic_rows


def test_task_status_diagnostic_rows_show_failure_category_and_next_steps() -> None:
    rows = task_status_diagnostic_rows(
        {
            "operation": "report_generation",
            "error_category": "quota",
            "error_severity": "warning",
            "error_summary": "模型/API 額度或速率限制",
            "retryable": True,
            "retry_kind": "report_generation",
            "next_action": "可從維護頁重試，或呼叫 POST /tasks/task-quota/retry",
            "next_steps": [
                "查看 AI 額度與模型路由或資料源額度。",
                "等待額度重置後再重試。",
            ],
        }
    )

    assert rows == [
        {
            "operation": "report_generation",
            "category": "quota",
            "severity": "warning",
            "summary": "模型/API 額度或速率限制",
            "retry": "可重試",
            "retry_kind": "report_generation",
            "next_action": "可從維護頁重試，或呼叫 POST /tasks/task-quota/retry",
            "next_steps": "查看 AI 額度與模型路由或資料源額度。；等待額度重置後再重試。",
        }
    ]


def test_task_status_diagnostic_rows_hide_when_no_failure_category() -> None:
    assert task_status_diagnostic_rows({"status": "SUCCESS"}) == []


def test_company_filing_gap_rows_show_visual_rag_next_actions_from_data_task_result() -> None:
    rows = company_filing_gap_rows(
        {
            "result": {
                "operation": "company_filings_fetch",
                "result": {
                    "gap_summary": {
                        "visual_rag_setup_tickers": ["2382"],
                        "visual_rag_review_tickers": ["3324"],
                    },
                    "next_actions": [
                        {
                            "ticker": "2382",
                            "company_name": "廣達",
                            "action": "configure_company_filing_visual_rag",
                            "missing_required_types": ["annual_report"],
                            "error_categories": ["visual_rag_not_configured"],
                            "reason": "請確認 PyMuPDF、VLM key 與模型。",
                        },
                        {
                            "ticker": "3324",
                            "company_name": "雙鴻",
                            "action": "review_visual_rag_or_manual_import",
                            "missing_recommended_types": ["investor_presentation"],
                            "error_categories": ["visual_rag_quota"],
                            "reason": "Visual RAG 額度用完。",
                        },
                    ],
                },
            }
        }
    )

    assert rows == [
        {
            "股票": "2382",
            "公司": "廣達",
            "下一步": "設定 Visual RAG",
            "缺必要文件": "annual_report",
            "缺建議文件": "-",
            "錯誤類型": "visual_rag_not_configured",
            "原因": "請確認 PyMuPDF、VLM key 與模型。",
        },
        {
            "股票": "3324",
            "公司": "雙鴻",
            "下一步": "檢查 Visual RAG/人工匯入",
            "缺必要文件": "-",
            "缺建議文件": "investor_presentation",
            "錯誤類型": "visual_rag_quota",
            "原因": "Visual RAG 額度用完。",
        },
    ]


def test_company_filing_gap_rows_fall_back_to_gap_summary() -> None:
    rows = company_filing_gap_rows(
        {
            "result": {
                "company_filings": {
                    "gap_summary": {
                        "visual_rag_setup_tickers": ["2382"],
                        "visual_rag_review_tickers": ["3324"],
                        "ocr_required_tickers": ["2308"],
                    }
                }
            }
        }
    )

    assert rows == [
        {
            "股票": "2382",
            "公司": "-",
            "下一步": "設定 Visual RAG",
            "缺必要文件": "-",
            "缺建議文件": "-",
            "錯誤類型": "visual_rag_setup_tickers",
            "原因": "需要 PyMuPDF、VLM model 或 vision key/gateway",
        },
        {
            "股票": "3324",
            "公司": "-",
            "下一步": "檢查 Visual RAG/人工匯入",
            "缺必要文件": "-",
            "缺建議文件": "-",
            "錯誤類型": "visual_rag_review_tickers",
            "原因": "VLM 額度、模型回應或抽取結果需要檢查",
        },
        {
            "股票": "2308",
            "公司": "-",
            "下一步": "OCR 或人工匯入",
            "缺必要文件": "-",
            "缺建議文件": "-",
            "錯誤類型": "ocr_required_tickers",
            "原因": "PDF 沒有可抽取文字或解析失敗",
        },
    ]
