from __future__ import annotations

from app.ui.follow_up_status import company_filing_action_label
from app.ui.task_failure_diagnostics import (
    task_failure_action_route,
    task_failure_action_route_detail,
    task_failure_category_label,
    task_failure_next_action_text,
    task_failure_next_steps_text,
    task_failure_operation_label,
    task_failure_retry_kind_label,
    task_failure_severity_label,
    task_failure_summary_text,
)
from app.ui.task_status_presenter import (
    task_run_source_label,
    task_run_status_label,
    task_status_progress_step_label,
    task_status_state_label,
)


def task_status_metric_values(task_status: dict) -> list[dict[str, str]]:
    run = task_status.get("run") if isinstance(task_status.get("run"), dict) else {}
    return [
        {
            "label": "任務狀態",
            "value": task_status_state_label(task_status.get("status") or "UNKNOWN"),
        },
        {
            "label": "是否結束",
            "value": _task_context_ready_label(task_status.get("ready", False)),
        },
        {
            "label": "是否成功",
            "value": _task_context_success_label(task_status.get("successful", False)),
        },
        {
            "label": "執行紀錄",
            "value": _number_ref(run.get("id")),
        },
    ]


def task_run_summary_rows(task_status: dict) -> list[dict[str, object]]:
    run = task_status.get("run") if isinstance(task_status, dict) else None
    if not isinstance(run, dict):
        return []
    return [
        {
            "執行紀錄": _number_ref(run.get("id")),
            "狀態": task_run_status_label(run.get("status")),
            "報告": _number_ref(run.get("report_id")),
            "輸出檔": run.get("output_path") or "-",
            "開始": run.get("started_at") or "-",
            "結束": run.get("finished_at") or "-",
        }
    ]


def task_status_progress_caption(task_status: dict) -> str:
    progress = task_status.get("progress") if isinstance(task_status.get("progress"), dict) else {}
    if not progress:
        return ""
    status = task_status_state_label(progress.get("status") or task_status.get("status") or "UNKNOWN")
    step = task_status_progress_step_label(
        progress.get("current_step") or progress.get("next_incomplete_step") or "等待中"
    )
    return f"進度：{status}｜{step}"


def task_status_diagnostic_rows(task_status: dict) -> list[dict]:
    if not isinstance(task_status, dict) or not task_status.get("error_category"):
        return []
    return [
        {
            "operation": task_failure_operation_label(task_status.get("operation")),
            "category": task_failure_category_label(task_status.get("error_category")),
            "severity": task_failure_severity_label(task_status.get("error_severity")),
            "summary": task_failure_summary_text(task_status),
            "retry": "可重試" if task_status.get("retryable") else "需人工",
            "retry_kind": task_failure_retry_kind_label(task_status.get("retry_kind")),
            "action_route": task_failure_action_route(task_status),
            "action_route_detail": task_failure_action_route_detail(task_status),
            "next_action": task_failure_next_action_text(task_status),
            "next_steps": task_failure_next_steps_text(task_status),
        }
    ]


def task_execution_context_rows(task_status: dict) -> list[dict]:
    if not isinstance(task_status, dict):
        return []
    context = task_status.get("execution_context")
    if not isinstance(context, dict):
        return []
    payload_shape = (
        context.get("payload_shape") if isinstance(context.get("payload_shape"), dict) else {}
    )
    celery_info_shape = (
        context.get("celery_info_shape")
        if isinstance(context.get("celery_info_shape"), dict)
        else {}
    )
    return [
        {
            "celery_status": task_status_state_label(
                context.get("celery_status") or task_status.get("status") or "-"
            ),
            "ready": _task_context_ready_label(
                context.get("ready", task_status.get("ready", False))
            ),
            "successful": _task_context_success_label(
                context.get("successful", task_status.get("successful", False))
            ),
            "run": f"#{context['run_id']}" if context.get("run_id") else "-",
            "run_status": task_run_status_label(context.get("run_status")),
            "source": task_run_source_label(context.get("run_source")),
            "operation": task_failure_operation_label(
                context.get("operation") or task_status.get("operation")
            ),
            "payload": _task_payload_shape_text(payload_shape),
            "celery_info": _celery_info_shape_text(celery_info_shape),
            "exception": _task_exception_text(context),
        }
    ]


def company_filing_gap_rows(task_status: dict) -> list[dict]:
    result = _company_filing_result_payload(
        task_status.get("result") if isinstance(task_status, dict) else None
    )
    if not result:
        return []
    action_rows = _company_filing_next_action_rows(result)
    if action_rows:
        return action_rows
    return _company_filing_gap_summary_rows(result)


def _company_filing_result_payload(result: object) -> dict:
    if not isinstance(result, dict):
        return {}
    candidates: list[dict] = [result]
    nested_result = result.get("result")
    if isinstance(nested_result, dict):
        candidates.append(nested_result)
    company_filings = result.get("company_filings")
    if isinstance(company_filings, dict):
        candidates.append(company_filings)
    pre_report = result.get("pre_report_ingestion")
    if isinstance(pre_report, dict) and isinstance(pre_report.get("company_filings"), dict):
        candidates.append(pre_report["company_filings"])

    for candidate in candidates:
        if any(key in candidate for key in ("gap_summary", "next_actions", "per_ticker_results")):
            return candidate
    return {}


def _company_filing_next_action_rows(result: dict) -> list[dict]:
    rows = []
    for action in result.get("next_actions") or []:
        if not isinstance(action, dict):
            continue
        rows.append(
            {
                "股票": action.get("ticker") or "-",
                "公司": action.get("company_name") or "-",
                "下一步": company_filing_action_label(action.get("action")),
                "缺必要文件": _join_values(action.get("missing_required_types")),
                "缺建議文件": _join_values(action.get("missing_recommended_types")),
                "錯誤類型": _join_values(action.get("error_categories")),
                "原因": action.get("reason") or "-",
            }
        )
    return rows


def _company_filing_gap_summary_rows(result: dict) -> list[dict]:
    summary = result.get("gap_summary")
    if not isinstance(summary, dict):
        return []
    rows = []
    specs = (
        (
            "visual_rag_setup_tickers",
            "設定 Visual RAG",
            "需要 PyMuPDF、VLM model 或 vision key/gateway",
        ),
        (
            "visual_rag_review_tickers",
            "檢查 Visual RAG/人工匯入",
            "VLM 額度、模型回應或抽取結果需要檢查",
        ),
        ("browser_recovery_tickers", "改用瀏覽器/Proxy 重試", "官方頁面疑似被反爬蟲或動態渲染擋住"),
        (
            "setup_required_tickers",
            "補齊執行環境設定",
            "缺少 PDF parser、Browser render 或 Visual RAG 設定",
        ),
        ("ocr_required_tickers", "OCR 或人工匯入", "PDF 沒有可抽取文字或解析失敗"),
        ("broaden_search_tickers", "擴大官方搜尋", "現有搜尋結果不足或文件不匹配"),
        ("retryable_tickers", "稍後自動重試", "資料源暫時錯誤"),
        ("blocked_tickers", "人工補齊公司文件", "公司文件仍不足"),
    )
    for key, action_label, reason in specs:
        tickers = _string_values(summary.get(key))
        if not tickers:
            continue
        rows.append(
            {
                "股票": "、".join(tickers),
                "公司": "-",
                "下一步": action_label,
                "缺必要文件": "-",
                "缺建議文件": "-",
                "錯誤類型": key,
                "原因": reason,
            }
        )
    return rows


def _join_values(value: object) -> str:
    values = _string_values(value)
    return "、".join(values) if values else "-"


def _number_ref(value: object) -> str:
    text = str(value or "").strip()
    if not text or text == "-":
        return "-"
    return f"#{text}"


def _string_values(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _display_string_values(value: object) -> list[str]:
    return [_display_shape_value(item) for item in _string_values(value)]


def _display_shape_value(value: object) -> str:
    text = str(value or "").strip()
    if text in {"<sensitive>", "[sensitive]", "sensitive"}:
        return "已遮蔽敏感欄位"
    return text


def _task_payload_shape_text(payload_shape: dict) -> str:
    if not payload_shape.get("present"):
        return "沒有任務輸入紀錄"
    parts = [
        f"資料欄位：{_join_display_values(payload_shape.get('top_level_keys'))}",
        f"股票 {int(payload_shape.get('ticker_count') or 0)} 檔",
    ]
    request_keys = _join_display_values(payload_shape.get("request_keys"))
    operation_payload_keys = _join_display_values(payload_shape.get("operation_payload_keys"))
    if request_keys != "-":
        parts.append(f"請求欄位：{request_keys}")
    if operation_payload_keys != "-":
        parts.append(f"任務欄位：{operation_payload_keys}")
    sensitive_count = int(payload_shape.get("sensitive_key_count") or 0)
    if sensitive_count:
        parts.append(f"已遮蔽敏感欄位 {sensitive_count} 個")
    return "；".join(parts)


def _celery_info_shape_text(celery_info_shape: dict) -> str:
    if not celery_info_shape.get("present"):
        return "-"
    parts = [f"回報型態：{celery_info_shape.get('type') or '-'}"]
    top_level_keys = _join_display_values(celery_info_shape.get("top_level_keys"))
    progress_keys = _join_display_values(celery_info_shape.get("progress_keys"))
    if top_level_keys != "-":
        parts.append(f"回報欄位：{top_level_keys}")
    if progress_keys != "-":
        parts.append(f"進度欄位：{progress_keys}")
    sensitive_count = int(celery_info_shape.get("sensitive_key_count") or 0)
    if sensitive_count:
        parts.append(f"已遮蔽敏感欄位 {sensitive_count} 個")
    return "；".join(parts)


def _join_display_values(value: object) -> str:
    values = _display_string_values(value)
    return "、".join(values) if values else "-"


def _task_context_ready_label(value: object) -> str:
    return "已結束" if bool(value) else "未結束"


def _task_context_success_label(value: object) -> str:
    return "成功" if bool(value) else "未成功"


def _task_exception_text(context: dict) -> str:
    exception_type = str(context.get("exception_type") or "").strip()
    preview = str(context.get("exception_message_preview") or "").strip()
    if preview:
        return f"執行錯誤：{preview}"
    if exception_type:
        return "執行錯誤"
    return "-"
