from __future__ import annotations

import streamlit as st

from app.ui.api_actions import run_api_action_or_none
from app.ui.api_client import api_task_post
from app.ui.api_loaders import load_api_json_or_default
from app.ui.follow_up_status import company_filing_action_label


TASK_STATUS_QUEUED_POLL_SECONDS = 8
TASK_STATUS_RETRY_POLL_SECONDS = 15


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
            "operation": task_status.get("operation") or "-",
            "category": task_status.get("error_category") or "-",
            "severity": task_status.get("error_severity") or "-",
            "summary": task_status.get("error_summary") or "-",
            "retry": "可重試" if task_status.get("retryable") else "需人工",
            "retry_kind": task_status.get("retry_kind") or "-",
            "next_action": task_status.get("next_action") or "-",
            "next_steps": _task_status_next_steps_text(task_status),
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


def _task_status_ready(task_status: dict | None) -> bool:
    if not isinstance(task_status, dict):
        return False
    return bool(task_status.get("ready")) or str(task_status.get("status") or "").upper() in {
        "SUCCESS",
        "FAILURE",
        "REVOKED",
    }


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
        if st.button("取消任務", key=f"{refresh_key}_cancel"):
            cancel_response = run_api_action_or_none(
                lambda: api_task_post(f"/tasks/{task_id}/cancel", {}),
                error_message="取消失敗",
            )
            if isinstance(cancel_response, dict):
                st.session_state[status_state_key] = cancel_response
                st.success("已送出取消要求。")
    with action_cols[1]:
        if st.button("重試任務", key=f"{refresh_key}_retry"):
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
