from __future__ import annotations

import json
from html import escape

import streamlit as st

from app.ui.api_actions import run_api_action_or_none
from app.ui.api_client import api_task_post
from app.ui.api_loaders import load_api_json_or_default
from app.ui.follow_up_status import company_filing_action_label
from app.ui.task_failure_diagnostics import (
    task_failure_action_route,
    task_failure_action_route_detail,
    task_failure_category_label,
    task_failure_next_steps_text,
    task_failure_operation_label,
    task_failure_retry_kind_label,
    task_failure_severity_label,
)


TASK_STATUS_QUEUED_POLL_SECONDS = 8
TASK_STATUS_RETRY_POLL_SECONDS = 15


def task_status_operation_label(task_status: dict | None) -> str:
    if not isinstance(task_status, dict):
        return "-"

    for value in (
        task_status.get("operation"),
        _nested_text(task_status.get("execution_context"), "operation"),
    ):
        label = _clean_task_operation_label(value)
        if label:
            return label

    run = task_status.get("run")
    if isinstance(run, dict):
        payload = _task_run_payload(run)
        for key in ("operation", "task", "workflow_name"):
            label = _clean_task_operation_label(payload.get(key))
            if label:
                return label

        workflow = run.get("workflow")
        label = _clean_task_operation_label(_nested_text(workflow, "name"))
        if label:
            return label

    for value in (
        _nested_text(task_status.get("execution_context"), "run_source"),
        _nested_text(run, "source") if isinstance(run, dict) else None,
    ):
        label = _clean_task_operation_label(value)
        if label:
            return _operator_operation_from_source(label)

    return "-"


def task_action_preflight_summary(
    task_status: dict,
    *,
    action: str,
    confirmed: bool,
) -> dict[str, str]:
    action_key = str(action or "").strip().casefold()
    task_id = str(task_status.get("task_id") or "-")
    status = str(task_status.get("status") or "UNKNOWN").upper()
    operation = task_status_operation_label(task_status)
    detail_parts = [
        f"Task {task_id}",
        f"狀態 {status}",
        f"操作 {operation}",
    ]

    if action_key == "retry":
        retry_kind = str(task_status.get("retry_kind") or "-")
        detail = "｜".join([*detail_parts, f"重試類型 {retry_kind}"])
        if task_status.get("retryable") is False:
            return {
                "state": "blocked",
                "label": "任務操作摘要",
                "title": "此任務不支援一鍵重試",
                "detail": detail,
                "next_step": str(
                    task_status.get("next_action")
                    or "請依失敗診斷修正輸入或外部設定後，從原本入口重新送出。"
                ),
                "impact": "尚未送出重試；先修正輸入、白名單或外部設定，避免重複失敗與額度浪費。",
            }
        if _task_status_successful(task_status):
            return {
                "state": "blocked",
                "label": "任務操作摘要",
                "title": "此任務已成功，不需要一鍵重試",
                "detail": detail,
                "next_step": "若需要重新執行，請回原本功能入口建立新任務。",
                "impact": "不會送出重試；避免對已成功任務重複消耗模型、外部資料源或 API 額度。",
            }
        if not _task_status_ready(task_status):
            return {
                "state": "blocked",
                "label": "任務操作摘要",
                "title": "此任務仍在執行，不能重試",
                "detail": detail,
                "next_step": "等待任務結束後，再依結果決定是否需要重試。",
                "impact": "不會送出重試；避免同一任務尚未完成時重複排隊。",
            }
        if not confirmed:
            return {
                "state": "attention",
                "label": "任務操作摘要",
                "title": "準備重試背景任務",
                "detail": detail,
                "next_step": "勾選確認後，再按「重試任務」重新送出背景任務。",
                "impact": "會重新排隊並可能再次消耗模型、外部資料源或 API 額度；若錯誤類型是 quota，建議先確認額度是否恢復。",
            }
        return {
            "state": "ready",
            "label": "任務操作摘要",
            "title": "可以重試背景任務",
            "detail": detail,
            "next_step": "按「重試任務」重新送出；送出後請查看新的 task id 與輪詢狀態。",
            "impact": "會重新排隊並可能再次消耗模型、外部資料源或 API 額度；完成前避免重複按重試。",
        }

    detail = "｜".join(detail_parts)
    if _task_status_ready(task_status):
        return {
            "state": "blocked",
            "label": "任務操作摘要",
            "title": "此任務已結束，不能取消",
            "detail": detail,
            "next_step": "不需取消；若結果失敗且支援重試，請使用重試或回原入口重新送出。",
            "impact": "不會送出取消要求；避免改動已完成任務紀錄。",
        }
    if not confirmed:
        return {
            "state": "attention",
            "label": "任務操作摘要",
            "title": "準備取消背景任務",
            "detail": detail,
            "next_step": "勾選確認後，再按「取消任務」送出取消要求。",
            "impact": "取消要求會寫入任務紀錄；若 worker 已完成，可能只會留下取消請求紀錄。",
        }
    return {
        "state": "ready",
        "label": "任務操作摘要",
        "title": "可以送出取消要求",
        "detail": detail,
        "next_step": "按「取消任務」通知背景任務停止；取消後請刷新狀態確認是否已停止。",
        "impact": "取消要求會寫入任務紀錄；若 worker 已完成，可能只會留下取消請求紀錄。",
    }


def render_task_action_preflight_summary(summary: dict[str, str]) -> None:
    if not summary:
        return
    st.markdown(
        f"""<section class="task-action-preflight-summary is-{escape(summary.get("state", "attention"))}" aria-label="任務操作送出前摘要">
<span>{escape(summary.get("label", "任務操作摘要"))}</span>
<strong>{escape(summary.get("title", ""))}</strong>
<p>{escape(summary.get("detail", ""))}</p>
<em>{escape(summary.get("next_step", ""))}</em>
<small>{escape(summary.get("impact", ""))}</small>
</section>""",
        unsafe_allow_html=True,
    )


def render_task_status(task_status: dict) -> None:
    cols = st.columns(4)
    cols[0].metric("Task", task_status.get("status", "UNKNOWN"))
    cols[1].metric("Ready", str(task_status.get("ready", False)))
    cols[2].metric("Success", str(task_status.get("successful", False)))
    run = task_status.get("run")
    cols[3].metric("Run", f"#{run['id']}" if isinstance(run, dict) and run.get("id") else "-")
    progress = task_status.get("progress") if isinstance(task_status.get("progress"), dict) else {}
    progress_pct = progress.get("progress_pct")
    if isinstance(progress_pct, (int, float)):
        st.progress(max(0.0, min(float(progress_pct), 1.0)))
    if progress:
        st.caption(
            "進度："
            f"{progress.get('status') or task_status.get('status', 'UNKNOWN')}｜"
            f"{progress.get('current_step') or progress.get('next_incomplete_step') or '等待中'}"
        )
        if progress.get("resume_hint"):
            st.caption(str(progress["resume_hint"]))
    company_filing_rows = company_filing_gap_rows(task_status)
    if company_filing_rows:
        st.caption("公司文件補抓摘要")
        st.dataframe(company_filing_rows, width="stretch", hide_index=True)
    execution_rows = task_execution_context_rows(task_status)
    if execution_rows:
        st.caption("執行上下文")
        st.dataframe(execution_rows, width="stretch", hide_index=True)
    if task_status.get("result"):
        st.json(task_status["result"])
    if task_status.get("error"):
        st.error(task_status["error"])
    diagnostic_rows = task_status_diagnostic_rows(task_status)
    if diagnostic_rows:
        st.caption("失敗診斷")
        st.dataframe(diagnostic_rows, width="stretch", hide_index=True)
    if isinstance(run, dict):
        st.dataframe(
            [
                {
                    "run_id": run.get("id"),
                    "status": run.get("status"),
                    "report_id": run.get("report_id"),
                    "output_path": run.get("output_path"),
                    "started_at": run.get("started_at"),
                    "finished_at": run.get("finished_at"),
                }
            ],
            width="stretch",
            hide_index=True,
        )


def task_status_diagnostic_rows(task_status: dict) -> list[dict]:
    if not isinstance(task_status, dict) or not task_status.get("error_category"):
        return []
    return [
        {
            "operation": task_failure_operation_label(task_status.get("operation")),
            "category": task_failure_category_label(task_status.get("error_category")),
            "severity": task_failure_severity_label(task_status.get("error_severity")),
            "summary": task_status.get("error_summary") or "-",
            "retry": "可重試" if task_status.get("retryable") else "需人工",
            "retry_kind": task_failure_retry_kind_label(task_status.get("retry_kind")),
            "action_route": task_failure_action_route(task_status),
            "action_route_detail": task_failure_action_route_detail(task_status),
            "next_action": task_status.get("next_action") or "-",
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
            "celery_status": context.get("celery_status") or task_status.get("status") or "-",
            "ready": str(context.get("ready", task_status.get("ready", False))),
            "successful": str(context.get("successful", task_status.get("successful", False))),
            "run": f"#{context['run_id']}" if context.get("run_id") else "-",
            "run_status": context.get("run_status") or "-",
            "source": context.get("run_source") or "-",
            "operation": context.get("operation") or task_status.get("operation") or "-",
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


def _nested_text(value: object, key: str) -> object:
    if isinstance(value, dict):
        return value.get(key)
    return None


def _clean_task_operation_label(value: object) -> str:
    label = str(value or "").strip()
    if not label or label in {"-", "unknown", "UNKNOWN"}:
        return ""
    return label


def _task_run_payload(run: dict) -> dict:
    for key in ("payload", "payload_json"):
        raw_payload = run.get(key)
        if isinstance(raw_payload, dict):
            return raw_payload
        if not isinstance(raw_payload, str):
            continue
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _operator_operation_from_source(source: str) -> str:
    if source.startswith("celery_"):
        return source.removeprefix("celery_")
    return source


def _string_values(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _task_status_next_steps_text(task_status: dict) -> str:
    next_steps = task_status.get("next_steps")
    if not isinstance(next_steps, list):
        return "-"
    steps = [str(step).strip() for step in next_steps if str(step).strip()]
    return "；".join(steps) if steps else "-"


def _task_payload_shape_text(payload_shape: dict) -> str:
    if not payload_shape.get("present"):
        return "無 run payload"
    parts = [
        f"keys={_join_values(payload_shape.get('top_level_keys'))}",
        f"tickers={int(payload_shape.get('ticker_count') or 0)}",
    ]
    request_keys = _join_values(payload_shape.get("request_keys"))
    operation_payload_keys = _join_values(payload_shape.get("operation_payload_keys"))
    if request_keys != "-":
        parts.append(f"request={request_keys}")
    if operation_payload_keys != "-":
        parts.append(f"payload={operation_payload_keys}")
    sensitive_count = int(payload_shape.get("sensitive_key_count") or 0)
    if sensitive_count:
        parts.append(f"sensitive_keys_masked={sensitive_count}")
    return "；".join(parts)


def _celery_info_shape_text(celery_info_shape: dict) -> str:
    if not celery_info_shape.get("present"):
        return "-"
    parts = [f"type={celery_info_shape.get('type') or '-'}"]
    top_level_keys = _join_values(celery_info_shape.get("top_level_keys"))
    progress_keys = _join_values(celery_info_shape.get("progress_keys"))
    if top_level_keys != "-":
        parts.append(f"keys={top_level_keys}")
    if progress_keys != "-":
        parts.append(f"progress={progress_keys}")
    sensitive_count = int(celery_info_shape.get("sensitive_key_count") or 0)
    if sensitive_count:
        parts.append(f"sensitive_keys_masked={sensitive_count}")
    return "；".join(parts)


def _task_exception_text(context: dict) -> str:
    exception_type = str(context.get("exception_type") or "").strip()
    preview = str(context.get("exception_message_preview") or "").strip()
    if exception_type and preview:
        return f"{exception_type}: {preview}"
    return exception_type or preview or "-"


def _task_status_ready(task_status: dict | None) -> bool:
    if not isinstance(task_status, dict):
        return False
    return bool(task_status.get("ready")) or str(task_status.get("status") or "").upper() in {
        "SUCCESS",
        "FAILURE",
        "REVOKED",
    }


def _task_status_successful(task_status: dict | None) -> bool:
    if not isinstance(task_status, dict):
        return False
    return bool(task_status.get("successful")) or str(task_status.get("status") or "").upper() == (
        "SUCCESS"
    )


def task_status_poll_interval_seconds(
    task_status: dict | None,
    *,
    default_seconds: int,
) -> int:
    interval = max(1, int(default_seconds or 5))
    if _task_status_ready(task_status):
        return interval
    status = str((task_status or {}).get("status") or "").upper()
    progress = (task_status or {}).get("progress")
    progress_pct = progress.get("progress_pct") if isinstance(progress, dict) else None
    if isinstance(progress_pct, (int, float)) and progress_pct > 0:
        return interval
    if status in {"PENDING", "QUEUED", "RECEIVED"}:
        return max(interval, TASK_STATUS_QUEUED_POLL_SECONDS)
    if status == "RETRY":
        return max(interval, TASK_STATUS_RETRY_POLL_SECONDS)
    return interval


def task_status_poll_caption(
    task_status: dict | None,
    *,
    auto_refresh: bool,
    fragment_supported: bool,
    default_seconds: int,
) -> str:
    if _task_status_ready(task_status):
        return "狀態輪詢：任務已結束，自動刷新停止。"
    if not auto_refresh:
        return "狀態輪詢：已暫停。"
    if not fragment_supported:
        return "狀態輪詢：目前環境不支援自動刷新。"

    interval = task_status_poll_interval_seconds(
        task_status,
        default_seconds=default_seconds,
    )
    status = str((task_status or {}).get("status") or "").upper()
    progress = (task_status or {}).get("progress")
    progress_pct = progress.get("progress_pct") if isinstance(progress, dict) else None
    if status in {"PENDING", "QUEUED", "RECEIVED"}:
        reason = "排隊中"
    elif status == "RETRY":
        reason = "等待重試"
    elif isinstance(progress_pct, (int, float)) and progress_pct > 0:
        reason = "執行中"
    else:
        reason = "處理中"
    return f"狀態輪詢：約每 {interval} 秒更新，{reason}。"


def _fetch_task_status(task_id: str, status_state_key: str) -> dict | None:
    task_status = load_api_json_or_default(
        f"/tasks/{task_id}",
        None,
        error_message="查詢失敗",
    )
    if not isinstance(task_status, dict):
        return None
    st.session_state[status_state_key] = task_status
    return task_status


def _render_task_status_panel_controls(
    *,
    task_id: str,
    refresh_key: str,
    status_state_key: str,
    apply_result_key: str | None,
    task_state_key: str | None,
) -> dict | None:
    task_status = st.session_state.get(status_state_key)
    if not isinstance(task_status, dict) or task_status.get("task_id") != task_id:
        return None
    render_task_status(task_status)
    action_cols = st.columns(2)
    with action_cols[0]:
        cancel_confirmed = st.checkbox(
            "我了解這會取消目前背景任務",
            value=False,
            key=f"{refresh_key}_confirm_cancel",
        )
        if not cancel_confirmed:
            st.caption("避免誤觸取消；確認後才可送出取消要求。")
        cancel_summary = task_action_preflight_summary(
            task_status,
            action="cancel",
            confirmed=cancel_confirmed,
        )
        render_task_action_preflight_summary(cancel_summary)
        cancel_blocked = cancel_summary.get("state") == "blocked"
        if st.button(
            "取消任務",
            key=f"{refresh_key}_cancel",
            disabled=cancel_blocked or not cancel_confirmed,
        ):
            cancel_response = run_api_action_or_none(
                lambda: api_task_post(f"/tasks/{task_id}/cancel", {}),
                error_message="取消失敗",
            )
            if isinstance(cancel_response, dict):
                st.session_state[status_state_key] = cancel_response
                st.success("已送出取消要求。")
    with action_cols[1]:
        retry_confirmed = st.checkbox(
            "我了解這會重新送出任務，可能消耗模型或資料源額度",
            value=False,
            key=f"{refresh_key}_confirm_retry",
        )
        if not retry_confirmed:
            st.caption("避免誤觸重試；確認後才可重新送出並消耗額度。")
        retry_summary = task_action_preflight_summary(
            task_status,
            action="retry",
            confirmed=retry_confirmed,
        )
        render_task_action_preflight_summary(retry_summary)
        retry_blocked = retry_summary.get("state") == "blocked"
        if st.button(
            "重試任務",
            key=f"{refresh_key}_retry",
            disabled=retry_blocked or not retry_confirmed,
        ):
            retry_response = run_api_action_or_none(
                lambda: api_task_post(f"/tasks/{task_id}/retry", {}),
                error_message="重試失敗",
            )
            if isinstance(retry_response, dict):
                retry_task_id = retry_response.get("task_id") or task_id
                if task_state_key:
                    st.session_state[task_state_key] = retry_task_id
                st.session_state[status_state_key] = retry_response
                st.success(f"已送出重試任務：{retry_task_id}")
    result = (task_status or {}).get("result")
    if (
        apply_result_key
        and isinstance(result, dict)
        and isinstance(result.get("report"), dict)
        and st.button("載入本次分析結果", key=apply_result_key)
    ):
        st.session_state["last_analysis_result"] = result
        active_report_id = result.get("active_report_id") or result.get("report_id")
        if active_report_id:
            st.session_state["pending_selected_report_id"] = int(active_report_id)
        st.rerun()
    return task_status


def render_task_status_panel(
    *,
    task_id: str,
    refresh_key: str,
    apply_result_key: str | None = None,
    task_state_key: str | None = None,
    auto_refresh_seconds: int = 5,
) -> dict | None:
    if not task_id:
        st.warning("請輸入 task id。")
        return None
    status_state_key = f"{refresh_key}_status"
    task_status = st.session_state.get(status_state_key)
    if isinstance(task_status, dict) and task_status.get("task_id") != task_id:
        task_status = None
        st.session_state.pop(status_state_key, None)
    control_cols = st.columns([1, 1])
    with control_cols[0]:
        if st.button("刷新狀態", key=refresh_key):
            task_status = _fetch_task_status(task_id, status_state_key)
            if task_status is None:
                return None
    with control_cols[1]:
        auto_refresh = st.toggle(
            "自動刷新",
            value=not _task_status_ready(task_status),
            key=f"{refresh_key}_auto_refresh",
        )
    if not isinstance(task_status, dict):
        task_status = _fetch_task_status(task_id, status_state_key)
    fragment_factory = getattr(st, "fragment", None)
    fragment_supported = callable(fragment_factory)
    st.caption(
        task_status_poll_caption(
            task_status,
            auto_refresh=auto_refresh,
            fragment_supported=fragment_supported,
            default_seconds=auto_refresh_seconds,
        )
    )
    if auto_refresh and not _task_status_ready(task_status) and fragment_supported:
        interval = task_status_poll_interval_seconds(
            task_status,
            default_seconds=auto_refresh_seconds,
        )

        @fragment_factory(run_every=f"{interval}s")
        def _auto_task_status_panel() -> dict | None:
            current_status = st.session_state.get(status_state_key)
            if not _task_status_ready(current_status if isinstance(current_status, dict) else None):
                _fetch_task_status(task_id, status_state_key)
            return _render_task_status_panel_controls(
                task_id=task_id,
                refresh_key=refresh_key,
                status_state_key=status_state_key,
                apply_result_key=apply_result_key,
                task_state_key=task_state_key,
            )

        return _auto_task_status_panel()
    return _render_task_status_panel_controls(
        task_id=task_id,
        refresh_key=refresh_key,
        status_state_key=status_state_key,
        apply_result_key=apply_result_key,
        task_state_key=task_state_key,
    )
