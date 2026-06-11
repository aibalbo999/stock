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


RUN_SOURCE_LABELS = {
    "follow_up_api": "自動補強",
    "pipeline_api": "分析流程",
    "report_api": "報告生成",
    "topic_discovery": "主題探索",
    "manual": "手動操作",
}

RUN_STATUS_LABELS = {
    "completed": "完成",
    "success": "完成",
    "successful": "完成",
    "succeeded": "完成",
    "done": "完成",
    "failed": "失敗",
    "failure": "失敗",
    "error": "錯誤",
    "cancelled": "已取消",
    "running": "執行中",
    "started": "執行中",
    "in_progress": "執行中",
    "processing": "執行中",
    "queued": "排隊中",
    "pending": "排隊中",
    "submitted": "已送出",
}

RUN_ERROR_LABELS = {
    "task_queue_error": "背景任務佇列異常",
    "payload_validation": "輸入或白名單已擋下任務",
    "runtime_storage": "執行紀錄儲存異常",
    "timeout": "逾時",
}


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
        health_summary = latest_report_health_summary(history_result or {}, follow_up_plan)
        _render_report_lifecycle_strip(lifecycle)
        _render_report_reader_decision_summary(
            report_reader_decision_summary(lifecycle, health_summary)
        )
        _render_report_lifecycle_action(lifecycle)
        _render_report_health_strip(health_summary)
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
            st.caption("刪除報告會移除目前最新版報告與安全範圍內的報告檔；分析紀錄會保留。")
            report_delete_confirmed = st.checkbox(
                f"我了解會刪除目前選取的報告 #{selected_id}",
                value=False,
                key=f"confirm_delete_report_{selected_id}",
            )
            if not report_delete_confirmed:
                st.caption("勾選確認後才會啟用刪除此報告，避免誤觸。")
            if st.button(
                "刪除此報告",
                key=f"delete_report_{selected_id}",
                disabled=not report_delete_confirmed,
            ):
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
        run_rows = report_run_history_rows(runs)
        run_ids = report_run_history_ids(runs)
        if run_rows:
            st.dataframe(
                run_rows,
                width="stretch",
                hide_index=True,
            )
            selected_run_id = st.selectbox(
                "查看 run",
                options=run_ids,
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
            run_delete_confirmed = st.checkbox(
                f"我了解會刪除分析紀錄 #{selected_run_id}",
                value=False,
                key=f"confirm_delete_run_{selected_run_id}",
            )
            st.caption("刪除分析紀錄只會移除此筆執行歷史，不會刪除目前最新版報告。")
            if not run_delete_confirmed:
                st.caption("勾選確認後才會啟用刪除此分析紀錄，避免誤觸。")
            if st.button(
                "刪除此分析紀錄",
                key=f"delete_run_{selected_run_id}",
                disabled=not run_delete_confirmed,
            ):
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
                "scope_note": "完成後報告中心會只顯示可閱讀的最新版結果。",
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
            "scope_note": "報告中心不需要手動整理歷史版本；系統會保留最新可讀結果。",
            "action_label": "建立分析",
            "route_hint": "analysis",
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
            "scope_note": "此頁只顯示目前保留的最新版；舊版請到疑難排解的執行紀錄追蹤。",
        }

    return {
        "mode": "multi_topic_latest",
        "options": options,
        "selected_id": selected_id,
        "selector_label": "選擇主題最新版報告",
        "summary_title": "每個主題的最新版",
        "summary_detail": f"共 {len(options)} 份主題最新版，預設讀取最新產生的一份。",
        "scope_note": "這不是歷史版本清單；每個主題只顯示最新一份可讀報告。",
    }


def report_run_history_rows(runs: list[Any] | None) -> list[dict[str, Any]]:
    if not isinstance(runs, list):
        return []
    rows: list[dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict) or run.get("id") is None:
            continue
        payload = parse_json_object(run.get("payload") or "{}")
        rows.append(
            {
                "紀錄": f"#{run.get('id')}",
                "來源": _run_source_label(run.get("source")),
                "狀態": _run_status_label(run.get("status")),
                "報告": f"#{run.get('report_id')}" if run.get("report_id") else "-",
                "背景任務": payload.get("celery_task_id") or "-",
                "開始": _format_optional_time(run.get("started_at")),
                "完成": _format_optional_time(run.get("finished_at")),
                "錯誤": _run_error_label(run.get("error")),
            }
        )
    return rows


def report_run_history_ids(runs: list[Any] | None) -> list[Any]:
    if not isinstance(runs, list):
        return []
    return [run["id"] for run in runs if isinstance(run, dict) and run.get("id") is not None]


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


def _format_optional_time(value: Any) -> str:
    text = _text(value)
    return _format_generated_at(text) if text else "-"


def _run_source_label(value: Any) -> str:
    text = _text(value)
    return RUN_SOURCE_LABELS.get(text, text or "-")


def _run_status_label(value: Any) -> str:
    text = _text(value).casefold()
    return RUN_STATUS_LABELS.get(text, text or "-")


def _run_error_label(value: Any) -> str:
    text = _text(value)
    return RUN_ERROR_LABELS.get(text, text or "-")


def _text(value: Any, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _render_latest_report_picker_summary(picker: dict[str, Any]) -> None:
    st.markdown(
        f"""<section class="latest-report-picker is-{escape(picker.get("mode", "empty"))}" aria-label="最新版報告範圍">
<span>{escape(picker.get("summary_title", "-"))}</span>
<strong>{escape(picker.get("summary_detail", ""))}</strong>
<em class="latest-report-picker-note">{escape(picker.get("scope_note", ""))}</em>
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
    summary = empty_report_action_summary(picker)
    if not summary:
        return
    st.markdown(
        f"""<section class="report-lifecycle-action is-{escape(summary.get("state", "empty"))}" aria-label="報告空狀態操作">
<span>{escape(summary.get("eyebrow", "建議操作"))}</span>
<strong>{escape(summary.get("title", ""))}</strong>
<em>{escape(summary.get("caption", ""))}</em>
</section>""",
        unsafe_allow_html=True,
    )
    render_operator_route_button(
        {
            "action_label": summary["action_label"],
            "route_hint": summary["route_hint"],
        },
        key="report_empty_state_primary_action",
        primary=True,
        show_caption=True,
    )


def empty_report_action_summary(picker: dict[str, Any]) -> dict[str, str]:
    action_label = _text(picker.get("action_label"))
    route_hint = _text(picker.get("route_hint"))
    if not action_label or not route_hint:
        return {}
    if _text(picker.get("mode")) == "running":
        return {
            "state": "running",
            "eyebrow": "建議操作",
            "title": "先確認背景任務進度",
            "caption": "最新任務還在背景執行；完成前避免重複送出分析。",
            "action_label": action_label,
            "route_hint": route_hint,
        }
    return {
        "state": "empty",
        "eyebrow": "建議操作",
        "title": "建立第一份最新版報告",
        "caption": "前往分析工作區建立報告；完成後回到這裡閱讀最新版。",
        "action_label": action_label,
        "route_hint": route_hint,
    }


def report_reader_decision_summary(
    lifecycle: dict[str, Any],
    health_summary: dict[str, str],
) -> dict[str, str]:
    lifecycle_state = _text(lifecycle.get("overall_state"), default="attention")
    health_state = _text(health_summary.get("state"))
    state = _reader_decision_state(lifecycle_state, health_state)
    title = {
        "ready": "可以閱讀最新版",
        "running": "等待補強完成再閱讀",
        "attention": "可先閱讀，但投資判斷需標示限制",
        "blocked": "暫停採信，先處理阻塞",
    }.get(state, "需要人工確認後再閱讀")
    action_label = _reader_decision_action_label(lifecycle, health_summary, state)
    action_detail = _reader_decision_action_detail(lifecycle, state)
    return {
        "state": state,
        "eyebrow": "閱讀決策",
        "title": title,
        "caption": _text(
            lifecycle.get("trust_explanation"),
            default="請先確認報告生命週期與品質狀態。",
        ),
        "evidence": _text(
            health_summary.get("report_meta_label"),
            default="尚無報告時間",
        ),
        "quality": _reader_quality_label(health_summary),
        "follow_up": f"補強 {_text(health_summary.get('follow_up_label'), default='尚無狀態')}",
        "action_label": action_label,
        "action_detail": action_detail,
    }


def _reader_decision_state(lifecycle_state: str, health_state: str) -> str:
    priority = {"blocked": 4, "running": 3, "attention": 2, "ready": 1}
    candidates = [state for state in (lifecycle_state, health_state) if state]
    if not candidates:
        return "attention"
    return max(candidates, key=lambda state: priority.get(state, 0))


def _reader_decision_action_label(
    lifecycle: dict[str, Any],
    health_summary: dict[str, str],
    state: str,
) -> str:
    if state == "blocked":
        return _text(
            health_summary.get("action_label"),
            default=lifecycle.get("primary_action", "確認狀態"),
        )
    return _text(
        lifecycle.get("primary_action"),
        default=health_summary.get("action_label", "確認狀態"),
    )


def _reader_decision_action_detail(lifecycle: dict[str, Any], state: str) -> str:
    if state == "blocked":
        return "完成建議操作後再回來閱讀最新版。"
    return _text(
        lifecycle.get("primary_action_detail"),
        default="完成建議操作後再回來閱讀最新版。",
    )


def _reader_quality_label(health_summary: dict[str, str]) -> str:
    quality = _text(health_summary.get("quality_label"), default="-")
    candidates = _text(health_summary.get("candidate_label"), default="候選 0｜正式 0")
    return f"品質 {quality}｜{candidates}"


def _render_report_reader_decision_summary(summary: dict[str, str]) -> None:
    if not summary:
        return
    st.markdown(
        f"""<section class="report-reader-decision is-{escape(summary.get("state", "attention"))}" aria-label="報告閱讀決策摘要">
<div class="report-reader-decision-main">
<span>{escape(summary.get("eyebrow", "閱讀決策"))}</span>
<strong>{escape(summary.get("title", ""))}</strong>
<p>{escape(summary.get("caption", ""))}</p>
</div>
<div class="report-reader-decision-grid">
<article>
<span>最新版證據</span>
<strong>{escape(summary.get("evidence", ""))}</strong>
</article>
<article>
<span>品質與股票</span>
<strong>{escape(summary.get("quality", ""))}</strong>
</article>
<article>
<span>補強</span>
<strong>{escape(summary.get("follow_up", ""))}</strong>
</article>
<article>
<span>下一步</span>
<strong>{escape(summary.get("action_label", ""))}</strong>
<em>{escape(summary.get("action_detail", ""))}</em>
</article>
</div>
</section>""",
        unsafe_allow_html=True,
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
