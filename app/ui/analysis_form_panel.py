from __future__ import annotations

import streamlit as st

from app.services.whitelist import SupplyChainWhitelist
from app.ui.analysis_workspace_presenter import (
    analysis_submission_ready,
    analysis_submission_summary,
)
from app.ui.analysis_workspace_view import (
    analysis_form_intro_html,
    analysis_submission_summary_html,
)
from app.ui.background_tasks import submit_api_task


def render_analysis_form_panel() -> int:
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

    return int(investor_capital)


def _render_analysis_submission_summary(summary: dict[str, str]) -> None:
    st.markdown(analysis_submission_summary_html(summary), unsafe_allow_html=True)
