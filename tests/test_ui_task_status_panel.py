from __future__ import annotations

from app.ui.task_status_panel import (
    _fetch_task_status,
    company_filing_gap_rows,
    task_status_diagnostic_rows,
    task_status_poll_caption,
    task_status_poll_interval_seconds,
)


class FakeStreamlit:
    def __init__(self) -> None:
        self.session_state: dict = {}


def test_fetch_task_status_uses_api_loader_and_stores_dict(monkeypatch) -> None:
    from app.ui import task_status_panel

    fake_st = FakeStreamlit()
    captured = {}
    monkeypatch.setattr(task_status_panel, "st", fake_st)

    def fake_loader(path: str, fallback, *, error_message: str):
        captured.update({"path": path, "fallback": fallback, "error_message": error_message})
        return {"task_id": "task-1", "status": "SUCCESS"}

    monkeypatch.setattr(task_status_panel, "load_api_json_or_default", fake_loader)

    assert _fetch_task_status("task-1", "task_status") == {
        "task_id": "task-1",
        "status": "SUCCESS",
    }
    assert fake_st.session_state["task_status"] == {"task_id": "task-1", "status": "SUCCESS"}
    assert captured == {
        "path": "/tasks/task-1",
        "fallback": None,
        "error_message": "查詢失敗",
    }


def test_fetch_task_status_ignores_non_dict_loader_fallback(monkeypatch) -> None:
    from app.ui import task_status_panel

    fake_st = FakeStreamlit()
    monkeypatch.setattr(task_status_panel, "st", fake_st)
    monkeypatch.setattr(task_status_panel, "load_api_json_or_default", lambda *args, **kwargs: None)

    assert _fetch_task_status("task-1", "task_status") is None
    assert "task_status" not in fake_st.session_state


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
            "action_route": "一鍵重試",
            "action_route_detail": "可由維護頁直接重試；若為額度限制，等額度恢復或切換 fallback 後再重試。",
            "next_action": "可從維護頁重試，或呼叫 POST /tasks/task-quota/retry",
            "next_steps": "查看 AI 額度與模型路由或資料源額度。；等待額度重置後再重試。",
        }
    ]


def test_task_status_diagnostic_rows_show_external_config_action_route() -> None:
    rows = task_status_diagnostic_rows(
        {
            "operation": "data_operation",
            "error_category": "task_queue",
            "error_severity": "error",
            "error_summary": "Redis/Celery queue 或 worker 異常",
            "retryable": False,
            "retry_kind": None,
            "next_action": "payload 不支援自動重試；請依錯誤內容手動重新送出。",
            "next_steps": [
                "確認 /services/status 的 task_queue.ready 與 worker_online。",
                "執行 Celery inspect ping 或重新啟動 Redis/Celery worker。",
            ],
        }
    )

    assert rows[0]["action_route"] == "外部配置缺失"
    assert "Redis/Celery" in rows[0]["action_route_detail"]


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


def test_task_status_poll_interval_backs_off_for_queued_tasks() -> None:
    assert (
        task_status_poll_interval_seconds(
            {"status": "PENDING", "ready": False},
            default_seconds=5,
        )
        == 8
    )


def test_task_status_poll_interval_backs_off_more_for_retry_tasks() -> None:
    assert (
        task_status_poll_interval_seconds(
            {"status": "RETRY", "ready": False},
            default_seconds=5,
        )
        == 15
    )


def test_task_status_poll_interval_keeps_fast_polling_for_active_progress() -> None:
    assert (
        task_status_poll_interval_seconds(
            {
                "status": "STARTED",
                "ready": False,
                "progress": {"progress_pct": 0.4},
            },
            default_seconds=5,
        )
        == 5
    )


def test_task_status_poll_caption_explains_queued_poll_cadence() -> None:
    assert (
        task_status_poll_caption(
            {"status": "PENDING", "ready": False},
            auto_refresh=True,
            fragment_supported=True,
            default_seconds=5,
        )
        == "狀態輪詢：約每 8 秒更新，排隊中。"
    )


def test_task_status_poll_caption_explains_retry_poll_cadence() -> None:
    assert (
        task_status_poll_caption(
            {"status": "RETRY", "ready": False},
            auto_refresh=True,
            fragment_supported=True,
            default_seconds=5,
        )
        == "狀態輪詢：約每 15 秒更新，等待重試。"
    )


def test_task_status_poll_caption_reports_stopped_when_ready() -> None:
    assert (
        task_status_poll_caption(
            {"status": "SUCCESS", "ready": True},
            auto_refresh=True,
            fragment_supported=True,
            default_seconds=5,
        )
        == "狀態輪詢：任務已結束，自動刷新停止。"
    )
