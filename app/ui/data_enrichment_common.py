from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from app.ui.operator_route_controls import render_operator_route_button
from app.ui.task_status_panel import render_task_status_panel


DATA_TASK_STATUS_STATE_KEYS = (
    "refresh_data_task_status_status",
    "refresh_manual_data_task_status_status",
    "refresh_rss_data_task_status_status",
)


def render_last_data_task_status(*, label: str, key: str, expanded: bool = False) -> None:
    last_data_task_id = st.session_state.get("last_data_task_id")
    if not last_data_task_id:
        return
    with st.expander("背景資料任務狀態", expanded=expanded):
        data_task_id = st.text_input("資料任務編號", value=last_data_task_id, key=key)
        task_status = render_task_status_panel(
            task_id=data_task_id,
            refresh_key=label,
            task_state_key="last_data_task_id",
        )
        _render_data_task_followup_summary(
            data_task_followup_summary(task_status),
            key=f"{label}_followup_action",
        )


def data_task_followup_summary(task_status: dict | None) -> dict[str, str]:
    if not isinstance(task_status, dict):
        return {}

    task_id = _text(task_status.get("task_id"))
    status = _text(task_status.get("status")).upper()
    if bool(task_status.get("successful")) or status == "SUCCESS":
        return {
            "state": "ready",
            "title": "資料補強完成",
            "detail": "資料任務已完成；回報告中心確認最新版生命週期是否仍需重跑。",
            "next_step": "開啟報告中心確認資料、品質、補強、重跑與可讀狀態。",
            "action_label": "查看報告中心",
            "route_hint": _data_task_report_route_hint(task_status),
        }

    if _data_task_failed(task_status, status):
        return {
            "state": "blocked",
            "title": "資料補強未完成",
            "detail": _data_task_failure_detail(task_status),
            "next_step": _text(
                task_status.get("next_action"),
                default="到維護頁查看診斷並視情況重試資料任務。",
            ),
            "action_label": "查看任務診斷",
            "route_hint": f"task:{task_id}" if task_id else "settings:maintenance",
        }

    return {
        "state": "attention",
        "title": "等待資料補強完成",
        "detail": "資料任務仍在處理中；完成前不要重複送出同類補強。",
        "next_step": "保持本頁狀態輪詢，完成後回報告中心確認是否需要重跑。",
        "action_label": "查看任務進度",
        "route_hint": f"task:{task_id}" if task_id else "settings:maintenance",
    }


def _render_data_task_followup_summary(summary: dict[str, str], *, key: str) -> None:
    if not summary:
        return
    st.markdown(
        f"""<section class="data-task-followup-summary is-{escape(summary.get("state", "attention"))}" aria-label="資料任務後續處理">
<span>後續處理</span>
<strong>{escape(summary.get("title", ""))}</strong>
<p>{escape(summary.get("detail", ""))}</p>
<em>{escape(summary.get("next_step", ""))}</em>
</section>""",
        unsafe_allow_html=True,
    )
    if summary.get("route_hint"):
        render_operator_route_button(
            {
                "action_label": summary.get("action_label"),
                "route_hint": summary.get("route_hint"),
            },
            key=key,
            primary=True,
            show_caption=True,
        )


def render_data_ingest_submission_summary(
    summary: dict[str, str],
    *,
    streamlit_module: Any | None = None,
) -> None:
    if not summary:
        return
    streamlit_module = streamlit_module or st
    streamlit_module.markdown(
        f"""<section class="data-ingest-submission-summary is-{escape(summary.get("state", "attention"))}" aria-label="資料送出前摘要">
<span>資料送出前摘要</span>
<strong>{escape(summary.get("title", ""))}</strong>
<p>{escape(summary.get("detail", ""))}</p>
<em>{escape(summary.get("next_step", ""))}</em>
<small>{escape(summary.get("quota_hint", ""))}</small>
</section>""",
        unsafe_allow_html=True,
    )


def _data_task_failed(task_status: dict, status: str) -> bool:
    if status in {"FAILURE", "FAILED", "REVOKED", "CANCELLED", "CANCELED", "ERROR"}:
        return True
    return bool(task_status.get("ready")) and not bool(task_status.get("successful"))


def _data_task_failure_detail(task_status: dict) -> str:
    return _text(
        task_status.get("error_summary") or task_status.get("error"),
        default="資料任務已結束但未成功。",
    )


def _data_task_report_route_hint(task_status: dict) -> str:
    report_id = _data_task_report_id(task_status)
    if report_id:
        return f"report:{report_id}"
    return "report_center"


def _data_task_report_id(task_status: dict) -> str:
    candidates: list[Any] = [
        task_status.get("report_id"),
        task_status.get("active_report_id"),
    ]
    result = task_status.get("result")
    if isinstance(result, dict):
        candidates.extend(
            [
                result.get("report_id"),
                result.get("active_report_id"),
            ]
        )
        report = result.get("report")
        if isinstance(report, dict):
            candidates.extend([report.get("id"), report.get("report_id")])
    run = task_status.get("run")
    if isinstance(run, dict):
        candidates.append(run.get("report_id"))
    for candidate in candidates:
        text = _text(candidate)
        if text:
            return text
    return ""


def _text(value: Any, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default
