from __future__ import annotations

import json

import requests
import streamlit as st

from app.services.report_quality import parse_quality_gate_from_markdown
from app.ui.api_client import api_delete, api_get, request_error_message
from app.ui.dashboard_core import (
    candidate_rows,
    render_company_data_audit,
    render_follow_up_controls,
    render_follow_up_flash,
    render_quality_gate,
    render_reader_report,
    render_section_header,
)
from app.ui.report_html import report_html
from app.ui.report_state import parse_json_object


def render_report_center() -> None:
    render_section_header("報告中心", "查看每個主題的最新版 HTML 報告；舊版內容只保留在執行紀錄中追蹤。")
    render_follow_up_flash()
    try:
        reports = api_get("/reports?limit=20")
    except requests.RequestException as exc:
        reports = []
        st.error(f"讀取報告清單失敗：{request_error_message(exc)}")
    report_options = [
        {
            "id": report.get("id"),
            "label": f"{str(report.get('generated_at') or '')[:16].replace('T', ' ')}｜{report.get('title') or '未命名報告'}",
        }
        for report in reports
        if isinstance(report, dict) and report.get("id") is not None
    ]

    if report_options:
        report_ids = [report["id"] for report in report_options]
        pending_report_id = st.session_state.pop("pending_selected_report_id", None)
        if pending_report_id in report_ids:
            st.session_state["selected_report_id"] = pending_report_id
        if st.session_state.get("selected_report_id") not in report_ids:
            st.session_state["selected_report_id"] = report_ids[0]
        selected_id = st.selectbox(
            "選擇最新版報告",
            options=report_ids,
            key="selected_report_id",
            format_func=lambda report_id: next(
                report["label"] for report in report_options if report["id"] == report_id
            ),
        )
    else:
        selected_id = None
        st.info("尚無最新版報告。")

    report_markdown = None
    report_title = "report"
    history_result = None
    if selected_id:
        try:
            report_payload = api_get(f"/reports/{int(selected_id)}")
            report_markdown = report_payload.get("markdown")
            report_title = report_payload.get("title") or "report"
            history_result = {
                "report_id": selected_id,
                "topic": report_payload.get("topic"),
                "tickers": report_payload.get("tickers") or [],
                "request": report_payload.get("request") or {},
                "quality_gate": report_payload.get("quality_gate") or parse_quality_gate_from_markdown(report_markdown or ""),
                "auto_follow_up": report_payload.get("auto_follow_up"),
                "candidate_whitelist": report_payload.get("candidate_whitelist") or [],
                "candidate_audit": report_payload.get("candidate_audit") or {},
            }
        except requests.RequestException:
            st.error("讀取報告內容失敗，請確認 API 服務狀態。")
        if report_markdown:
            history_result = history_result or {
                "report_id": selected_id,
                "quality_gate": parse_quality_gate_from_markdown(report_markdown),
            }

    if selected_id and report_markdown:
        history_html = report_html(report_markdown, history_result)
        report_action_cols = st.columns([0.16, 0.16, 0.68], gap="small")
        with report_action_cols[0]:
            st.download_button(
                "下載 HTML",
                data=history_html,
                file_name=f"report_{selected_id}.html",
                mime="text/html",
            )
        with report_action_cols[1]:
            st.download_button(
                "下載 Markdown",
                data=report_markdown,
                file_name=f"report_{selected_id}.md",
                mime="text/markdown",
            )
        with report_action_cols[2]:
            with st.expander("報告管理"):
                if st.button("刪除此報告"):
                    try:
                        api_delete(f"/reports/{int(selected_id)}")
                        st.success(f"已刪除報告 #{selected_id}｜{report_title}")
                        st.rerun()
                    except requests.RequestException as exc:
                        st.error(f"刪除失敗：{request_error_message(exc)}")

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
            """
                <div class="result-shell">
                <div class="section-title">尚未選擇報告</div>
                <div class="section-note">上方選擇一份最新版報告後，這裡會顯示 HTML 重點版。</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with st.expander("疑難排解：執行紀錄"):
        render_section_header("執行紀錄", "一般閱讀報告不需要查看；舊版報告與背景任務只在這裡查錯或追蹤。")
        try:
            runs = api_get("/runs?limit=20")
        except requests.RequestException as exc:
            runs = []
            st.error(f"讀取執行紀錄失敗：{request_error_message(exc)}")
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
            try:
                selected_run = api_get(f"/runs/{int(selected_run_id)}")
            except requests.RequestException as exc:
                selected_run = {}
                st.error(f"讀取紀錄失敗：{request_error_message(exc)}")
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
            if selected_task_id and st.button("查詢背景任務狀態"):
                try:
                    st.json(api_get(f"/tasks/{selected_task_id}"))
                except requests.RequestException as exc:
                    st.error(f"查詢失敗：{request_error_message(exc)}")
            if selected_run_error:
                st.error(selected_run_error)
            if st.button("刪除此分析紀錄"):
                try:
                    api_delete(f"/runs/{int(selected_run_id)}")
                    st.success(f"已刪除分析紀錄 #{selected_run_id}")
                    st.rerun()
                except requests.RequestException as exc:
                    st.error(f"刪除失敗：{request_error_message(exc)}")
        else:
            st.info("尚無任務執行紀錄。")
