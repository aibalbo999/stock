from __future__ import annotations

import json
from html import escape
from typing import Any

import streamlit as st

from app.services.report_quality import parse_quality_gate_from_markdown
from app.ui.api_actions import run_api_action_or_none
from app.ui.api_client import api_delete
from app.ui.api_loaders import load_api_json_or_default
from app.ui.dashboard_core import render_section_header
from app.ui.operator_route_controls import render_operator_route_button
from app.ui.report_health import latest_report_health_summary
from app.ui.report_lifecycle import latest_report_lifecycle
from app.ui.report_panels import (
    candidate_rows,
    render_company_data_audit,
    render_quality_gate,
    render_reader_report,
)
from app.ui.report_follow_up_controls import render_follow_up_controls, render_follow_up_flash
from app.ui.report_html import report_html
from app.ui.report_state import parse_json_object
from app.ui.task_status_panel import render_task_status_panel


def render_report_center() -> None:
    render_section_header(
        "報告中心", "查看每個主題的最新版 HTML 報告；舊版內容只保留在執行紀錄中追蹤。"
    )
    render_follow_up_flash()
    reports = load_api_json_or_default(
        "/reports?limit=5",
        [],
        error_message="讀取報告清單失敗",
    )
    task_summary = (
        {}
        if reports
        else load_api_json_or_default(
            "/tasks/summary?days=7&limit=10",
            {},
            error_message="讀取報告中心任務狀態失敗",
            notify="warning",
        )
    )
    pending_report_id = st.session_state.pop("pending_selected_report_id", None)
    picker = latest_report_picker_state(
        reports,
        pending_report_id=pending_report_id,
        current_report_id=st.session_state.get("selected_report_id"),
        task_summary=task_summary,
    )
    report_options = picker["options"]

    if report_options:
        report_ids = [report["id"] for report in report_options]
        selected_id = picker["selected_id"]
        st.session_state["selected_report_id"] = selected_id
        _render_latest_report_picker_summary(picker)
        if picker["mode"] == "multi_topic_latest":
            selected_id = st.selectbox(
                picker["selector_label"],
                options=report_ids,
                key="selected_report_id",
                format_func=lambda report_id: next(
                    report["label"] for report in report_options if report["id"] == report_id
                ),
            )
    else:
        selected_id = None
        _render_latest_report_picker_summary(picker)
        st.info(str(picker.get("summary_detail") or "尚無最新版報告。"))

    report_markdown = None
    report_title = "report"
    history_result = None
    if selected_id:
        report_payload = load_api_json_or_default(
            f"/reports/{int(selected_id)}",
            {},
            error_message="讀取報告內容失敗",
        )
        if isinstance(report_payload, dict) and report_payload:
            report_markdown = report_payload.get("markdown")
            report_title = report_payload.get("title") or "report"
            history_result = {
                "report_id": selected_id,
                "title": report_payload.get("title"),
                "topic": report_payload.get("topic"),
                "generated_at": report_payload.get("generated_at"),
                "tickers": report_payload.get("tickers") or [],
                "request": report_payload.get("request") or {},
                "quality_gate": report_payload.get("quality_gate")
                or parse_quality_gate_from_markdown(report_markdown or ""),
                "auto_follow_up": report_payload.get("auto_follow_up"),
                "candidate_whitelist": report_payload.get("candidate_whitelist") or [],
                "candidate_audit": report_payload.get("candidate_audit") or {},
            }
        if report_markdown:
            history_result = history_result or {
                "report_id": selected_id,
                "title": report_title,
                "quality_gate": parse_quality_gate_from_markdown(report_markdown),
            }

    if selected_id and report_markdown:
        follow_up_plan = load_api_json_or_default(
            f"/reports/{int(selected_id)}/follow-up/plan",
            {},
            error_message="讀取補強計畫失敗",
            notify="warning",
        )
        lifecycle = latest_report_lifecycle(history_result or {}, follow_up_plan)
        _render_report_lifecycle_strip(lifecycle)
        _render_report_lifecycle_action(lifecycle)
        _render_report_health_strip(
            latest_report_health_summary(history_result or {}, follow_up_plan)
        )
        history_html = report_html(report_markdown, history_result)
        report_download_cols = st.columns(2, gap="small")
        with report_download_cols[0]:
            st.download_button(
                "下載 HTML",
                data=history_html,
                file_name=f"report_{selected_id}.html",
                mime="text/html",
            )
        with report_download_cols[1]:
            st.download_button(
                "下載 Markdown",
                data=report_markdown,
                file_name=f"report_{selected_id}.md",
                mime="text/markdown",
            )

        history_tabs = st.tabs(["重點報告", "資料查核", "完整文字"])
        with history_tabs[0]:
            render_reader_report(report_markdown, history_result)
        with history_tabs[1]:
            if history_result:
                render_quality_gate(history_result)
                render_company_data_audit(int(selected_id))
                render_follow_up_controls(int(selected_id), report_markdown, scope="history_report")
                candidates = history_result.get("candidate_whitelist") or []
                if candidates:
                    with st.expander("候選公司審計"):
                        st.dataframe(candidate_rows(candidates), width="stretch", hide_index=True)
            else:
                st.info("此份報告尚無可解析的品質門檻。")
        with history_tabs[2]:
            st.markdown(report_markdown)
    else:
        st.markdown(
            f"""
                <div class="result-shell">
                <div class="section-title">{escape(str(picker.get("summary_title") or "尚未選擇報告"))}</div>
                <div class="section-note">{escape(str(picker.get("summary_detail") or "建立分析後，這裡會顯示目前保留的最新版報告。"))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        _render_empty_report_action(picker)

    with st.expander("疑難排解：執行紀錄"):
        render_section_header(
            "執行紀錄", "一般閱讀報告不需要查看；舊版報告與背景任務只在這裡查錯或追蹤。"
        )
        if selected_id is not None:
            st.markdown("#### 報告管理")
            st.caption("進階操作，只在需要移除最新版報告時使用。")
            if st.button("刪除此報告", key=f"delete_report_{selected_id}"):
                deleted = run_api_action_or_none(
                    lambda: api_delete(f"/reports/{int(selected_id)}"),
                    error_message="刪除失敗",
                )
                if isinstance(deleted, dict):
                    st.success(f"已刪除報告 #{selected_id}｜{report_title}")
                    st.rerun()
            st.divider()
        runs = load_api_json_or_default(
            "/runs?limit=20",
            [],
            error_message="讀取執行紀錄失敗",
        )
        run_rows = []
        for run in runs:
            if not isinstance(run, dict):
                continue
            payload = parse_json_object(run.get("payload") or "{}")
            run_rows.append(
                {
                    "id": run.get("id"),
                    "source": run.get("source"),
                    "status": run.get("status"),
                    "report_id": run.get("report_id"),
                    "celery_task_id": payload.get("celery_task_id"),
                    "started_at": run.get("started_at"),
                    "finished_at": run.get("finished_at"),
                    "error": run.get("error"),
                }
            )
        if run_rows:
            st.dataframe(
                run_rows,
                width="stretch",
                hide_index=True,
            )
            selected_run_id = st.selectbox(
                "查看 run",
                options=[row["id"] for row in run_rows],
                format_func=lambda run_id: f"紀錄 #{run_id}",
            )
            selected_run = load_api_json_or_default(
                f"/runs/{int(selected_run_id)}",
                {},
                error_message="讀取紀錄失敗",
            )
            if isinstance(selected_run, dict):
                selected_run_payload = selected_run.get("payload") or "{}"
                selected_run_error = selected_run.get("error")
            else:
                selected_run_payload = "{}"
                selected_run_error = None
            selected_payload = parse_json_object(selected_run_payload)
            selected_task_id = selected_payload.get("celery_task_id")
            with st.expander("原始紀錄內容"):
                try:
                    st.json(json.loads(selected_run_payload))
                except json.JSONDecodeError:
                    st.code(selected_run_payload)
            if selected_task_id:
                with st.expander("背景任務狀態", expanded=False):
                    render_task_status_panel(
                        task_id=str(selected_task_id),
                        refresh_key=f"history_run_task_status_{selected_run_id}",
                    )
            if selected_run_error:
                st.error(selected_run_error)
            if st.button("刪除此分析紀錄"):
                deleted = run_api_action_or_none(
                    lambda: api_delete(f"/runs/{int(selected_run_id)}"),
                    error_message="刪除失敗",
                )
                if isinstance(deleted, dict):
                    st.success(f"已刪除分析紀錄 #{selected_run_id}")
                    st.rerun()
        else:
            st.info("尚無任務執行紀錄。")


def latest_report_picker_state(
    reports: list[dict] | None,
    *,
    pending_report_id: Any = None,
    current_report_id: Any = None,
    task_summary: dict | None = None,
) -> dict[str, Any]:
    options = _latest_report_options(reports)
    if not options:
        latest_running_task = _latest_task_running(task_summary)
        if latest_running_task:
            return {
                "mode": "running",
                "options": [],
                "selected_id": None,
                "selector_label": "",
                "summary_title": "最新版報告生成中",
                "summary_detail": "最新任務正在背景執行；完成前不需要重複建立分析。",
                "action_label": "查看任務",
                "route_hint": _task_route_hint(latest_running_task),
            }
        return {
            "mode": "empty",
            "options": [],
            "selected_id": None,
            "selector_label": "",
            "summary_title": "尚無最新版報告",
            "summary_detail": "建立分析後，這裡會顯示目前保留的最新版報告。",
        }

    selected_id = (
        _matching_report_id(options, pending_report_id)
        or _matching_report_id(options, current_report_id)
        or options[0]["id"]
    )
    if len(options) == 1:
        return {
            "mode": "single_latest",
            "options": options,
            "selected_id": selected_id,
            "selector_label": "",
            "summary_title": "目前最新版報告",
            "summary_detail": options[0]["summary_detail"],
        }

    return {
        "mode": "multi_topic_latest",
        "options": options,
        "selected_id": selected_id,
        "selector_label": "選擇主題最新版報告",
        "summary_title": "每個主題的最新版",
        "summary_detail": f"共 {len(options)} 份主題最新版，預設讀取最新產生的一份。",
    }


def _latest_report_options(reports: list[dict] | None) -> list[dict[str, Any]]:
    if not isinstance(reports, list):
        return []
    options: list[dict[str, Any]] = []
    for report in reports:
        if not isinstance(report, dict) or report.get("id") is None:
            continue
        generated_at = _format_generated_at(report.get("generated_at"))
        title = _text(report.get("title") or report.get("topic"), default="未命名報告")
        topic = _text(report.get("topic") or report.get("title"), default="未命名主題")
        options.append(
            {
                "id": report["id"],
                "label": f"{generated_at}｜{title}",
                "summary_detail": f"{topic}｜{generated_at}",
            }
        )
    return options


def _matching_report_id(options: list[dict[str, Any]], report_id: Any) -> Any:
    report_id_text = _text(report_id)
    if not report_id_text:
        return None
    for option in options:
        if _text(option.get("id")) == report_id_text:
            return option["id"]
    return None


def _latest_task_running(task_summary: dict | None) -> dict:
    task = _latest_task(task_summary)
    return task if _task_running(task) else {}


def _latest_task(task_summary: dict | None) -> dict:
    if not isinstance(task_summary, dict):
        return {}
    for key in ("latest", "latest_task"):
        value = task_summary.get(key)
        if isinstance(value, dict):
            return value
    recent = task_summary.get("recent")
    if isinstance(recent, list):
        for row in recent:
            if isinstance(row, dict):
                return row
    return {}


def _task_running(task: dict) -> bool:
    if _task_successful(task) or _task_failed(task):
        return False
    if task.get("running") is True:
        return True
    status = _text(task.get("status")).casefold()
    celery_status = _text(task.get("celery_status")).casefold()
    return status in {
        "pending",
        "queued",
        "received",
        "retry",
        "running",
        "started",
        "in_progress",
        "processing",
        "submitted",
        "scheduled",
    } or celery_status in {
        "pending",
        "queued",
        "received",
        "retry",
        "running",
        "started",
    }


def _task_successful(task: dict) -> bool:
    if task.get("successful") is True:
        return True
    status = _text(task.get("status")).casefold()
    celery_status = _text(task.get("celery_status")).casefold()
    return status in {"success", "successful", "succeeded", "completed", "done"} or celery_status in {
        "success",
        "successful",
        "succeeded",
    }


def _task_failed(task: dict) -> bool:
    status = _text(task.get("status")).casefold()
    celery_status = _text(task.get("celery_status")).casefold()
    if status in {"failed", "failure", "cancelled", "error"}:
        return True
    if celery_status in {"failed", "failure", "revoked"}:
        return True
    return bool(task.get("error") or task.get("error_category"))


def _task_route_hint(task: dict) -> str:
    task_id = _text(task.get("task_id"))
    return f"task:{task_id}" if task_id else "settings:maintenance"


def _format_generated_at(value: Any) -> str:
    text = _text(value)
    if not text:
        return "未標示時間"
    return text[:16].replace("T", " ")


def _text(value: Any, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _render_latest_report_picker_summary(picker: dict[str, Any]) -> None:
    st.markdown(
        f"""<section class="latest-report-picker is-{escape(picker.get("mode", "empty"))}" aria-label="最新版報告範圍">
<span>{escape(picker.get("summary_title", "-"))}</span>
<strong>{escape(picker.get("summary_detail", ""))}</strong>
</section>""",
        unsafe_allow_html=True,
    )


def _render_report_lifecycle_strip(lifecycle: dict) -> None:
    stage_html = "\n".join(
        _report_lifecycle_stage_html(stage) for stage in lifecycle.get("stage_cards") or []
    )
    st.markdown(
        f"""<section class="report-lifecycle-strip is-{escape(lifecycle.get("overall_state", "attention"))}" aria-label="報告生命週期">
<div class="report-lifecycle-summary">
<span>報告生命週期</span>
<strong>{escape(lifecycle.get("trust_label", "-"))}</strong>
<p>{escape(lifecycle.get("trust_explanation", ""))}</p>
<em>{escape(lifecycle.get("primary_action", ""))}</em>
<small>{escape(lifecycle.get("primary_action_detail", ""))}</small>
</div>
<div class="report-lifecycle-steps">
{stage_html}
</div>
</section>""",
        unsafe_allow_html=True,
    )


def _render_report_lifecycle_action(lifecycle: dict) -> None:
    route_hint = lifecycle.get("route_hint")
    primary_action = lifecycle.get("primary_action")
    if not route_hint or not primary_action:
        return
    st.markdown(
        """<section class="report-lifecycle-action" aria-label="報告生命週期操作">
<span>建議操作</span>
<strong>依照生命週期狀態開啟下一步</strong>
</section>""",
        unsafe_allow_html=True,
    )
    render_operator_route_button(
        {
            "action_label": primary_action,
            "route_hint": route_hint,
        },
        key="report_lifecycle_primary_action",
        primary=True,
        show_caption=True,
    )


def _render_empty_report_action(picker: dict[str, Any]) -> None:
    action_label = _text(picker.get("action_label"))
    route_hint = _text(picker.get("route_hint"))
    if not action_label or not route_hint:
        return
    st.markdown(
        """<section class="report-lifecycle-action" aria-label="報告空狀態操作">
<span>建議操作</span>
<strong>先確認背景任務進度</strong>
</section>""",
        unsafe_allow_html=True,
    )
    render_operator_route_button(
        {
            "action_label": action_label,
            "route_hint": route_hint,
        },
        key="report_empty_state_primary_action",
        primary=True,
        show_caption=True,
    )


def _report_lifecycle_stage_html(stage: dict) -> str:
    return f"""<article class="report-lifecycle-step is-{escape(stage.get("state", "unknown"))}">
<span>{escape(stage.get("title", "-"))}</span>
<strong>{escape(stage.get("label", "-"))}</strong>
<p>{escape(stage.get("detail", ""))}</p>
</article>"""


def _render_report_health_strip(summary: dict[str, str]) -> None:
    st.markdown(
        f"""<section class="report-health-strip is-{escape(summary.get("state", "attention"))}">
<article class="report-health-card">
<span>最新版</span>
<strong>{escape(summary.get("report_label", "-"))}</strong>
<em>{escape(summary.get("report_meta_label", ""))}</em>
</article>
<article class="report-health-card">
<span>品質門檻</span>
<strong>{escape(summary.get("quality_label", "-"))}</strong>
</article>
<article class="report-health-card">
<span>股票範圍</span>
<strong>{escape(summary.get("candidate_label", "-"))}</strong>
</article>
<article class="report-health-card">
<span>補強狀態</span>
<strong>{escape(summary.get("follow_up_label", "-"))}</strong>
</article>
<article class="report-health-card report-health-action is-{escape(summary.get("follow_up_state", "unknown"))}">
<span>建議操作</span>
<strong>{escape(summary.get("action_label", "-"))}</strong>
</article>
</section>""",
        unsafe_allow_html=True,
    )
