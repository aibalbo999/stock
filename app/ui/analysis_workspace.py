from __future__ import annotations

import streamlit as st

from app.core.time import today_taipei
from app.services.whitelist import SupplyChainWhitelist
from app.ui.api_loaders import load_api_json_or_default
from app.ui.background_tasks import submit_api_task
from app.ui.analysis_operator_presenter import (
    latest_report_id as _latest_report_id,
    looks_like_operator_route as _looks_like_operator_route,
    operator_card_html as _operator_card_html,
    operator_decision_html as _operator_decision_html,
    operator_secondary_actions_html as _operator_secondary_actions_html,
    operator_source_label as _operator_source_label,
    operator_source_text as _operator_source_text,
    secondary_action_html as _secondary_action_html,
)
from app.ui.analysis_workspace_presenter import (
    analysis_submission_quota_pressure,
    analysis_submission_ready,
    analysis_submission_summary,
)
from app.ui.analysis_workspace_view import (
    analysis_form_intro_html,
    analysis_submission_summary_html,
    empty_analysis_result_html,
    operator_action_controls_html,
    operator_status_grid_html,
    operator_workbench_header_html,
    workspace_flow_html,
    workspace_topbar_html,
)
from app.ui.dashboard_core import render_section_header
from app.ui.operator_decisions import (
    MAX_SECONDARY_ACTIONS,
    operator_next_best_action,
    operator_secondary_actions,
)
from app.ui.operator_route_controls import render_operator_route_button
from app.ui.operator_status import (
    operator_status_cards,
    operator_status_overall,
)
from app.ui.report_panels import (
    candidate_rows,
    render_company_data_audit,
    render_market_errors,
    render_quality_gate,
    render_reader_report,
    render_source_audit,
)
from app.ui.report_follow_up_controls import render_follow_up_controls
from app.ui.report_formatters import metric_count_from_payload
from app.ui.report_html import report_html
from app.ui.report_state import hydrate_active_report_result
from app.ui.task_status_panel import render_task_status_panel


__all__ = [
    "analysis_submission_quota_pressure",
    "analysis_submission_ready",
    "analysis_submission_summary",
    "_looks_like_operator_route",
    "_operator_card_html",
    "_operator_decision_html",
    "_operator_secondary_actions_html",
    "_operator_source_label",
    "_operator_source_text",
    "_secondary_action_html",
    "render_analysis_workspace",
]


def render_analysis_workspace() -> None:
    st.markdown(
        workspace_topbar_html(today_taipei().isoformat()),
        unsafe_allow_html=True,
    )
    _render_operator_workbench()
    st.markdown(workspace_flow_html(), unsafe_allow_html=True)
    render_section_header(
        "建立一次分析", "預設使用 AI 拆解主題並抓取國內外資料；不確定時維持預設即可。"
    )
    analysis_config_col, analysis_result_col = st.columns([0.36, 0.64], gap="large")
    with analysis_config_col:
        with st.form("analysis_form"):
            st.markdown("#### 分析設定")
            st.markdown(analysis_form_intro_html(), unsafe_allow_html=True)
            topic = st.text_input("分析主題", value="AI 產業鏈")
            lookback_days = st.slider("新聞與市場資料回看天數", min_value=7, max_value=60, value=14)
            investor_capital = st.number_input(
                "可投入總資金",
                min_value=10000,
                max_value=100000000,
                value=1000000,
                step=10000,
            )
            profile_label = st.selectbox(
                "投資人設定",
                options=["新手保守", "一般穩健", "積極成長"],
                index=0,
            )
            profile_map = {"新手保守": "beginner", "一般穩健": "balanced", "積極成長": "aggressive"}
            investor_profile = profile_map[profile_label]
            beginner_mode = investor_profile == "beginner"

            st.markdown("#### 風險與資金")
            max_position_pct = st.slider(
                "單檔上限", min_value=1, max_value=20, value=10, format="%d%%"
            )
            cash_reserve_pct = st.slider(
                "保留現金", min_value=10, max_value=80, value=30, format="%d%%"
            )
            discovery_limit = st.slider("資料抓取強度", min_value=2, max_value=20, value=5)

            with st.expander("進階選項"):
                ai_discovery_mode = st.checkbox("由 AI 拆解主題與建立候選清單", value=True)
                analysis_mode_label = st.radio(
                    "分析強度",
                    options=["快速預覽", "標準研究", "深度研究"],
                    index=1,
                    horizontal=True,
                )
                analysis_mode_map = {"快速預覽": "fast", "標準研究": "standard", "深度研究": "deep"}
                analysis_mode = analysis_mode_map[analysis_mode_label]
                deep_analysis = analysis_mode == "deep"
                include_international = st.checkbox("納入國際資料源", value=True)
                evidence_limit = st.slider(
                    "報告引用資料量",
                    min_value=40,
                    max_value=200,
                    value=180
                    if analysis_mode == "deep"
                    else 120
                    if analysis_mode == "standard"
                    else 80,
                    step=20,
                )
                tickers = st.multiselect(
                    "手動模式個股範圍",
                    options=sorted(SupplyChainWhitelist().allowed_tickers()),
                    default=[],
                )
                st.caption("分析會在背景執行，送出後可用任務編號查詢進度。")

            analysis_quota_confirmed = st.checkbox(
                "我了解這會送出分析背景任務並消耗 AI/API 額度",
                value=False,
                key="confirm_analysis_submission_quota_usage",
            )
            if not topic.strip():
                st.caption("請先輸入分析主題。")
            elif not analysis_quota_confirmed:
                st.caption("避免誤觸與免費額度消耗；確認主題、分析強度與資料抓取強度後才會送出。")
            submission_summary = analysis_submission_summary(
                topic=topic,
                analysis_mode_label=analysis_mode_label,
                discovery_limit=int(discovery_limit),
                evidence_limit=int(evidence_limit),
                lookback_days=int(lookback_days),
                ai_discovery_mode=bool(ai_discovery_mode),
                manual_tickers=tickers,
                quota_confirmed=bool(analysis_quota_confirmed),
            )
            _render_analysis_submission_summary(submission_summary)
            run_sync = st.form_submit_button(
                "執行分析",
                type="primary",
                disabled=not analysis_submission_ready(
                    topic,
                    analysis_quota_confirmed,
                    ai_discovery_mode=bool(ai_discovery_mode),
                    manual_tickers=tickers,
                ),
            )

        if run_sync:
            if ai_discovery_mode:
                payload = {
                    "topic": topic,
                    "limit_per_query": int(discovery_limit),
                    "lookback_days": int(lookback_days),
                    "evidence_limit": int(evidence_limit),
                    "analysis_mode": analysis_mode,
                    "deep_analysis": bool(deep_analysis),
                    "include_international": bool(include_international),
                    "investor_capital": int(investor_capital),
                    "beginner_mode": bool(beginner_mode),
                    "investor_profile": investor_profile,
                    "max_position_pct": float(max_position_pct) / 100,
                    "cash_reserve_pct": float(cash_reserve_pct) / 100,
                }
                submit_api_task(
                    "/pipeline/run_discovered_async",
                    payload,
                    task_state_key="last_async_task_id",
                    status_state_keys=("refresh_analysis_task_status_status",),
                    success_message="已送出 AI 探索背景任務",
                    error_message="AI 探索背景任務送出失敗",
                    task_type_state_key="last_analysis_task_type",
                    task_type="discovered",
                )
            elif not tickers:
                st.warning("手動模式背景執行請至少選擇一檔白名單股票。")
            else:
                payload = {
                    "topic": topic,
                    "tickers": tickers,
                    "lookback_days": int(lookback_days),
                    "evidence_limit": int(evidence_limit),
                    "investor_capital": int(investor_capital),
                    "beginner_mode": bool(beginner_mode),
                    "investor_profile": investor_profile,
                    "max_position_pct": float(max_position_pct) / 100,
                    "cash_reserve_pct": float(cash_reserve_pct) / 100,
                }
                submit_api_task(
                    "/reports/generate_async",
                    payload,
                    task_state_key="last_async_task_id",
                    status_state_keys=("refresh_analysis_task_status_status",),
                    success_message="已送出分析背景任務",
                    error_message="分析背景任務送出失敗",
                    task_type_state_key="last_analysis_task_type",
                    task_type="manual",
                )

        with st.expander("疑難排解：查詢背景分析"):
            last_task_id = st.session_state.get("last_async_task_id")
            task_id = st.text_input("背景分析編號", value=last_task_id or "")
            render_task_status_panel(
                task_id=task_id,
                refresh_key="refresh_analysis_task_status",
                apply_result_key="apply_analysis_task_result",
                task_state_key="last_async_task_id",
            )
            if st.button("查詢紀錄", key="lookup_analysis_task_run"):
                if not task_id:
                    st.warning("請輸入任務編號。")
                else:
                    task_run = load_api_json_or_default(
                        f"/tasks/{task_id}/run",
                        None,
                        error_message="查詢失敗",
                        not_found_message="尚未找到對應紀錄；任務剛送出時可能需要等待。",
                    )
                    if task_run is not None:
                        st.json(task_run)

    with analysis_result_col:
        result = st.session_state.get("last_analysis_result")
        if result:
            result = hydrate_active_report_result(result)
            report_markdown = result["report"]["markdown"]
            analysis_metrics = (result.get("quality_gate") or {}).get("metrics") or {}
            metric_cols = st.columns(4)
            metric_cols[0].metric("報告", f"#{result['report_id']}")
            metric_cols[1].metric(
                "正式分析股票",
                metric_count_from_payload(
                    result, "promoted_tickers", analysis_metrics, "promoted_count", 0
                ),
            )
            metric_cols[2].metric("候選清單", len(result.get("candidate_whitelist", [])))
            metric_cols[3].metric("設定總資金", f"{int(investor_capital):,}")
            render_market_errors(result)

            render_section_header("本次分析結果", "先看重點報告；資料細節只在需要查核時展開。")
            result_tabs = st.tabs(["重點報告", "資料查核"])
            with result_tabs[0]:
                st.download_button(
                    "下載 HTML 報告",
                    data=report_html(report_markdown, result),
                    file_name=f"report_{result['report_id']}.html",
                    mime="text/html",
                )
                render_reader_report(report_markdown, result)
            with result_tabs[1]:
                render_quality_gate(result)
                render_company_data_audit(int(result["report_id"]))
                render_follow_up_controls(
                    int(result["report_id"]), report_markdown, scope="analysis_result"
                )
                with st.expander("資料來源概況"):
                    render_source_audit(result)
                if result.get("candidate_whitelist"):
                    st.markdown("**候選清單驗證**")
                    st.dataframe(
                        candidate_rows(result["candidate_whitelist"]),
                        width="stretch",
                        hide_index=True,
                    )
                with st.expander("進階：原始報告文字"):
                    st.markdown(report_markdown)
        else:
            st.markdown(empty_analysis_result_html(), unsafe_allow_html=True)


def _render_analysis_submission_summary(summary: dict[str, str]) -> None:
    st.markdown(analysis_submission_summary_html(summary), unsafe_allow_html=True)


def _render_operator_workbench() -> None:
    service_snapshot = load_api_json_or_default(
        "/services/status",
        {},
        error_message="讀取系統狀態失敗",
        notify="warning",
    )
    task_summary = load_api_json_or_default(
        "/tasks/summary?days=7&limit=10",
        {},
        error_message="讀取任務摘要失敗",
        notify="warning",
    )
    quota = load_api_json_or_default(
        "/llm/quota",
        {},
        error_message="讀取模型額度失敗",
        notify="warning",
    )
    reports = load_api_json_or_default(
        "/reports?limit=5",
        [],
        error_message="讀取最新版報告失敗",
        notify="warning",
    )
    if not isinstance(reports, list):
        reports = []
    latest_report_id = _latest_report_id(reports)
    latest_report_payload = {}
    latest_follow_up_plan = {}
    if latest_report_id is not None:
        latest_report_payload = load_api_json_or_default(
            f"/reports/{int(latest_report_id)}",
            {},
            error_message="讀取首頁報告狀態失敗",
            notify="warning",
        )
        latest_follow_up_plan = load_api_json_or_default(
            f"/reports/{int(latest_report_id)}/follow-up/plan",
            {},
            error_message="讀取首頁補強計畫失敗",
            notify="warning",
        )
    primary_action = operator_next_best_action(
        service_snapshot,
        task_summary,
        quota,
        reports,
        latest_report_payload,
        latest_follow_up_plan,
    )
    secondary_actions = operator_secondary_actions(
        service_snapshot,
        task_summary,
        quota,
        reports,
        latest_report_payload,
        latest_follow_up_plan,
        primary_action=primary_action,
    )
    overall = operator_status_overall(service_snapshot, task_summary, reports)
    cards = operator_status_cards(service_snapshot, task_summary, quota, reports)
    card_html = "\n".join(_operator_card_html(card) for card in cards)
    st.markdown(
        _operator_decision_html(primary_action, [], include_secondary=False),
        unsafe_allow_html=True,
    )
    _render_operator_primary_action_control(primary_action)
    if secondary_actions:
        st.markdown(_operator_secondary_actions_html(secondary_actions), unsafe_allow_html=True)
    _render_operator_action_controls(secondary_actions)
    st.markdown(operator_workbench_header_html(overall), unsafe_allow_html=True)
    st.markdown(operator_status_grid_html(card_html), unsafe_allow_html=True)


def _render_operator_primary_action_control(primary_action: dict) -> None:
    st.markdown(operator_action_controls_html(primary=True), unsafe_allow_html=True)
    _render_operator_route_button(
        primary_action,
        key="operator_route_primary_action",
        primary=True,
        show_caption=False,
    )


def _render_operator_action_controls(secondary_actions: list[dict]) -> None:
    if not secondary_actions:
        return
    st.markdown(operator_action_controls_html(), unsafe_allow_html=True)
    actions = secondary_actions[:MAX_SECONDARY_ACTIONS]
    columns = st.columns(len(actions), gap="small")
    for index, action in enumerate(actions):
        with columns[index]:
            _render_operator_route_button(
                action,
                key=f"operator_route_action_{index}",
            )


def _render_operator_route_button(
    action: dict,
    *,
    key: str,
    primary: bool = False,
    show_caption: bool = True,
) -> None:
    render_operator_route_button(
        action,
        key=key,
        primary=primary,
        show_caption=show_caption,
    )
