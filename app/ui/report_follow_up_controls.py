from __future__ import annotations

import streamlit as st

from app.ui.api_loaders import load_api_json_or_default
from app.ui.background_tasks import submit_api_task
from app.ui.follow_up_status import (
    candidate_revalidation_summary,
    follow_up_blocker_action_rows,
    follow_up_result_message,
)
from app.ui.report_markdown import markdown_table_rows
from app.ui.task_status_panel import render_task_status_panel


def render_follow_up_controls(report_id: int, markdown: str, scope: str = "report") -> None:
    key_suffix = f"{scope}_{report_id}"
    rows = markdown_table_rows(markdown, "自動補強任務", limit=20)
    planned_actions = []
    plan_next_actions = []
    plan_error = None
    plan = load_api_json_or_default(
        f"/reports/{report_id}/follow-up/plan",
        {"_load_error": True},
        error_message="讀取補強任務預覽失敗",
        notify="none",
    )
    if isinstance(plan, dict) and plan.get("_load_error"):
        plan_error = "load_failed"
        freshness = {}
    elif isinstance(plan, dict):
        planned_actions = plan.get("actions") or []
        plan_next_actions = plan.get("next_actions") or []
        freshness = plan.get("freshness") or {}
    else:
        plan_error = "invalid_response"
        freshness = {}
    st.markdown("**自動補強**")
    if planned_actions:
        required_count = sum(1 for action in planned_actions if action.get("purpose") == "required")
        tracking_count = sum(1 for action in planned_actions if action.get("purpose") == "tracking")
        st.caption(f"資料缺口補強 {required_count} 項，追蹤更新 {tracking_count} 項。")
        st.dataframe(
            [
                {
                    "任務": action.get("label") or action.get("action_type", "-"),
                    "股票": "、".join(action.get("tickers") or []) or "全主題",
                    "性質": "資料缺口補強" if action.get("purpose") == "required" else "追蹤更新",
                    "優先級": action.get("priority", "-"),
                    "頻率": action.get("frequency", "-"),
                    "觸發原因": action.get("reason", "-"),
                }
                for action in planned_actions
            ],
            width="stretch",
            hide_index=True,
        )
        if plan_next_actions:
            st.caption("預計補強重點")
            st.dataframe(
                [
                    {
                        "股票": "、".join(action.get("tickers") or []) or "全主題",
                        "下一步": action.get("next_step"),
                        "補強目標": action.get("target") or "-",
                        "完成條件": action.get("completion_criteria") or "-",
                        "優先級": action.get("priority", "-"),
                        "原因": action.get("reason", "-"),
                    }
                    for action in plan_next_actions
                ],
                width="stretch",
                hide_index=True,
            )
    elif rows:
        st.dataframe(
            [
                {
                    "任務": row[0] if len(row) > 0 else "-",
                    "股票": row[1] if len(row) > 1 else "-",
                    "性質": row[2] if len(row) > 5 else "追蹤更新",
                    "優先級": row[3] if len(row) > 5 else row[2] if len(row) > 2 else "-",
                    "頻率": row[4] if len(row) > 5 else row[3] if len(row) > 3 else "-",
                    "觸發原因": row[5] if len(row) > 5 else row[4] if len(row) > 4 else "-",
                }
                for row in rows
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("目前沒有明確補強任務；仍可重新刷新資料並重跑一次，確認結論是否改變。")
        skipped = freshness.get("skipped_actions") or []
        if skipped:
            st.caption(f"已略過 {len(skipped)} 項追蹤更新，原因是相關資料仍在新鮮範圍內。")
            with st.expander("查看已略過的追蹤更新"):
                skipped_details = freshness.get("skipped_details") or []
                st.dataframe(
                    [
                        {
                            "任務": action.get("label") or action.get("action_type", "-"),
                            "股票": "、".join(action.get("tickers") or []) or "全主題",
                            "最新日期": "、".join(
                                f"{ticker}:{date_value}"
                                for ticker, date_value in (
                                    (action.get("freshness") or {}).get("latest_dates") or {}
                                ).items()
                            )
                            or "-",
                            "新鮮門檻": f"{(action.get('freshness') or {}).get('max_age_days')} 天"
                            if (action.get("freshness") or {}).get("max_age_days") is not None
                            else "-",
                            "原因": "資料仍在新鮮範圍內",
                        }
                        for action in (skipped_details or skipped)
                    ],
                    width="stretch",
                    hide_index=True,
                )
        if plan_error:
            st.caption("暫時無法讀取後端任務預覽。")
    skipped_actions = (
        (freshness.get("skipped_actions") or []) if isinstance(freshness, dict) else []
    )
    force_refresh = False
    if skipped_actions:
        force_refresh = st.checkbox(
            "忽略新鮮度，強制更新已略過的追蹤資料",
            value=False,
            key=f"followup_force_refresh_{key_suffix}",
        )
    purpose_options = {
        "全部任務": "all",
        "只補資料缺口": "required",
        "只做追蹤更新": "tracking",
    }
    default_purpose = (
        "只補資料缺口"
        if planned_actions
        and any(action.get("purpose") == "required" for action in planned_actions)
        else "只做追蹤更新"
    )
    selected_purpose_label = st.radio(
        "執行範圍",
        options=list(purpose_options.keys()),
        index=list(purpose_options.keys()).index(default_purpose),
        horizontal=True,
        key=f"followup_purpose_{key_suffix}",
    )
    selected_purpose = purpose_options[selected_purpose_label]
    action_pool = planned_actions + skipped_actions if force_refresh else planned_actions
    if selected_purpose == "all":
        executable_actions = action_pool
    else:
        executable_actions = [
            action for action in action_pool if action.get("purpose") == selected_purpose
        ]
    manual_tracking_available = not planned_actions and not rows and plan_error is None
    manual_tracking_selected = manual_tracking_available and selected_purpose in {"all", "tracking"}
    has_executable_actions = bool(executable_actions or rows or manual_tracking_selected)
    if planned_actions and not executable_actions:
        st.caption("目前選擇的範圍沒有可執行任務。")
    elif manual_tracking_selected:
        st.caption("本次將執行：手動追蹤補抓資料；完成後可重新產生報告。")
    elif manual_tracking_available:
        st.caption("目前沒有資料缺口任務；可切換到追蹤更新後手動補抓資料。")
    elif executable_actions:
        selected_required = sum(
            1 for action in executable_actions if action.get("purpose") == "required"
        )
        selected_tracking = sum(
            1 for action in executable_actions if action.get("purpose") == "tracking"
        )
        st.caption(
            f"本次將執行：資料缺口補強 {selected_required} 項，追蹤更新 {selected_tracking} 項。"
        )
    cols = st.columns([0.62, 0.38])
    rerun_report = cols[0].checkbox(
        "完成後重新產生一份報告", value=True, key=f"followup_rerun_{key_suffix}"
    )
    news_limit = cols[1].number_input(
        "補抓資料量",
        min_value=10,
        max_value=100,
        value=30,
        step=10,
        key=f"followup_news_limit_{key_suffix}",
    )
    button_label = (
        "補資料缺口並重跑"
        if selected_purpose == "required"
        else "執行追蹤更新並重跑"
        if selected_purpose == "tracking"
        else "執行全部補強並重跑"
    )
    if st.button(
        button_label,
        type="primary",
        key=f"followup_run_{key_suffix}",
        disabled=not has_executable_actions,
    ):
        submit_api_task(
            f"/reports/{report_id}/follow-up/run_async",
            {
                "rerun_report": bool(rerun_report),
                "news_limit": int(news_limit),
                "purpose": selected_purpose,
                "force_refresh": bool(force_refresh or manual_tracking_selected),
            },
            task_state_key="last_follow_up_task_id",
            status_state_keys=(f"refresh_followup_task_{key_suffix}_status",),
            success_message="已送出補強背景任務",
            error_message="自動補強任務送出失敗",
        )

    last_follow_up_task_id = st.session_state.get("last_follow_up_task_id")
    if last_follow_up_task_id:
        with st.expander("背景補強任務狀態", expanded=True):
            task_id = st.text_input(
                "補強任務編號",
                value=last_follow_up_task_id,
                key=f"followup_task_lookup_{key_suffix}",
            )
            task_status = render_task_status_panel(
                task_id=task_id,
                refresh_key=f"refresh_followup_task_{key_suffix}",
                task_state_key="last_follow_up_task_id",
            )
            result = (task_status or {}).get("result") if isinstance(task_status, dict) else None
            if isinstance(result, dict) and st.button(
                "套用背景補強結果", key=f"apply_followup_task_{key_suffix}"
            ):
                st.session_state["last_follow_up_result"] = result
                selected_summary = (result.get("summary") or {}).get("selected") or {}
                execution_summary = (result.get("summary") or {}).get("execution") or {}
                summary_text = (
                    f"執行 {selected_summary.get('total_count', len(result.get('actions') or []))} 項任務"
                    f"（資料缺口 {selected_summary.get('required_count', 0)}、"
                    f"追蹤更新 {selected_summary.get('tracking_count', 0)}）"
                )
                if execution_summary:
                    summary_text += (
                        f"，補入/更新 {execution_summary.get('stored_count', 0)} 筆資料"
                        f"，錯誤 {execution_summary.get('error_count', 0)} 項"
                    )
                message_level, message_text = follow_up_result_message(result, summary_text)
                st.session_state["follow_up_flash"] = {
                    "level": message_level,
                    "message": message_text,
                    "result": result,
                }
                new_report = result.get("rerun_report") or {}
                if new_report.get("report_id"):
                    st.session_state["pending_selected_report_id"] = int(new_report["report_id"])
                st.rerun()


def render_follow_up_flash() -> None:
    flash = st.session_state.get("follow_up_flash")
    if not isinstance(flash, dict):
        return
    message = flash.get("message", "補強任務已完成。")
    if flash.get("level") == "warning":
        st.warning(message)
    else:
        st.success(message)
    result = flash.get("result") or {}
    blocker_rows = follow_up_blocker_action_rows(result)
    if blocker_rows:
        with st.expander("查看重跑前需要處理的項目", expanded=True):
            st.dataframe(blocker_rows, width="stretch", hide_index=True)
    execution = (result.get("summary") or {}).get("execution") or {}
    items = execution.get("items") or []
    if items:
        with st.expander("查看本次補強結果"):
            st.dataframe(
                [
                    {
                        "任務": item.get("task"),
                        "更新筆數": item.get("stored_count", 0),
                        "錯誤數": item.get("error_count", 0),
                        "完成狀態": "達標"
                        if (item.get("completion") or {}).get("completed")
                        else "未達標",
                        "來源": item.get("source") or "-",
                    }
                    for item in items
                ],
                width="stretch",
                hide_index=True,
            )
    revalidation = candidate_revalidation_summary(result)
    if revalidation["total"]:
        with st.expander("查看候選重新驗證結果", expanded=revalidation["changed"]):
            cols = st.columns(4)
            cols[0].metric("候選", revalidation["total"])
            cols[1].metric("正式", revalidation["promoted_count"])
            cols[2].metric("弱證據", revalidation["weak_count"])
            cols[3].metric("待補", revalidation["needs_evidence_count"])
            st.caption(
                f"本次重新驗證使用 {revalidation['document_query_count']} 組公司/主題查詢、"
                f"{revalidation['document_count']} 筆去重後文件。"
            )
            if revalidation["newly_promoted"]:
                st.success("新升格為正式分析：" + "、".join(revalidation["newly_promoted"]))
            if revalidation["no_longer_promoted"]:
                st.warning("降回觀察/待補：" + "、".join(revalidation["no_longer_promoted"]))
            st.dataframe(revalidation["rows"], width="stretch", hide_index=True)
    if st.button("關閉補強結果", key="dismiss_follow_up_flash"):
        st.session_state.pop("follow_up_flash", None)
        st.rerun()
