from __future__ import annotations

from html import escape

import streamlit as st

from app.core.time import today_taipei
from app.services.whitelist import SupplyChainWhitelist
from app.ui.api_loaders import load_api_json_or_default
from app.ui.background_tasks import submit_api_task
from app.ui.dashboard_core import render_section_header
from app.ui.operator_decisions import (
    MAX_SECONDARY_ACTIONS,
    operator_next_best_action,
    operator_secondary_actions,
)
from app.ui.operator_route_controls import render_operator_route_button
from app.ui.operator_routes import operator_route_target
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


def analysis_submission_ready(
    topic: str,
    quota_confirmed: bool,
    *,
    ai_discovery_mode: bool = True,
    manual_tickers: list[str] | None = None,
) -> bool:
    if not topic.strip() or not quota_confirmed:
        return False
    if not ai_discovery_mode and not _selected_manual_tickers(manual_tickers):
        return False
    return True


def analysis_submission_summary(
    *,
    topic: str,
    analysis_mode_label: str,
    discovery_limit: int,
    evidence_limit: int,
    lookback_days: int,
    ai_discovery_mode: bool,
    manual_tickers: list[str] | None,
    quota_confirmed: bool,
) -> dict[str, str]:
    topic_label = topic.strip() or "尚未輸入主題"
    manual_ticker_count = len(_selected_manual_tickers(manual_tickers))
    mode_parts = (
        [analysis_mode_label]
        if ai_discovery_mode
        else [f"手動個股 {manual_ticker_count} 檔", analysis_mode_label]
    )
    detail = "｜".join(
        [
            topic_label,
            *mode_parts,
            f"資料抓取 {int(discovery_limit)}",
            f"引用上限 {int(evidence_limit)}",
            f"回看 {int(lookback_days)} 天",
        ]
    )
    if not topic.strip():
        return {
            "state": "attention",
            "title": "先補齊送出條件",
            "detail": detail,
            "next_step": "請先輸入分析主題。",
            "disabled_reason": "尚未輸入分析主題",
        }
    if not quota_confirmed:
        return {
            "state": "attention",
            "title": "先確認額度消耗",
            "detail": detail,
            "next_step": "勾選額度確認後才能送出背景任務。",
            "disabled_reason": "尚未確認 AI/API 額度消耗",
        }
    if not ai_discovery_mode and manual_ticker_count == 0:
        return {
            "state": "attention",
            "title": "先補齊送出條件",
            "detail": detail,
            "next_step": "手動模式請先選擇至少一檔股票。",
            "disabled_reason": "手動模式尚未選擇股票",
        }
    return {
        "state": "ready",
        "title": "可送出分析背景任務",
        "detail": detail,
        "next_step": "按「執行分析」送出背景任務。",
        "disabled_reason": "",
    }


def render_analysis_workspace() -> None:
    st.markdown(
        """
        <section class="workspace-topbar is-compact">
            <div>
                <div class="workspace-kicker">AI 台股投資工作台</div>
                <h1>AI 台股操作者控制台</h1>
                <div class="workspace-subtitle">
                    先看系統建議，再決定讀最新版報告、補資料或重跑分析。
                </div>
            </div>
            <div class="workspace-meta">
                <span class="workspace-chip">Asia/Taipei {today}</span>
                <span class="workspace-chip">資料不足自動降級</span>
                <span class="workspace-chip is-accent">缺口自動補強</span>
            </div>
        </section>
        """.format(today=today_taipei().isoformat()),
        unsafe_allow_html=True,
    )
    _render_operator_workbench()
    st.markdown(
        """
        <section class="workflow-strip is-compact" aria-label="分析流程">
            <div class="workflow-step"><span>01</span><strong>主題拆解</strong></div>
            <div class="workflow-step"><span>02</span><strong>來源驗證</strong></div>
            <div class="workflow-step"><span>03</span><strong>個股評估</strong></div>
            <div class="workflow-step"><span>04</span><strong>補強與重跑</strong></div>
        </section>
        <section class="workspace-ledger is-compact" aria-label="報告判讀基準">
            <div class="ledger-item"><span>品質門檻</span><strong>未過門檻先標示，不包裝成建議</strong></div>
            <div class="ledger-item"><span>資料來源</span><strong>新聞、市場、財務、公司文件分開查核</strong></div>
            <div class="ledger-item"><span>投資口徑</span><strong>正式分析不等於買進，分數只用於排序</strong></div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    render_section_header(
        "建立一次分析", "預設使用 AI 拆解主題並抓取國內外資料；不確定時維持預設即可。"
    )
    analysis_config_col, analysis_result_col = st.columns([0.36, 0.64], gap="large")
    with analysis_config_col:
        with st.form("analysis_form"):
            st.markdown("#### 分析設定")
            st.markdown(
                '<div class="compact-note">輸入主題，系統會自行拆解子題並建立候選股票。</div>',
                unsafe_allow_html=True,
            )
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
                st.caption(
                    "分析任務一律交由 FastAPI / Celery 背景執行，送出後可用 task id 查詢進度。"
                )

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
                    st.warning("請輸入 task id。")
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
            st.markdown(
                """
                <div class="result-shell">
                    <div class="section-title">等待分析結果</div>
                    <div class="section-note">
                        左側完成設定後執行分析。結果會在這裡以 HTML 卡片報告呈現，資料來源與完整文字會收在次要區塊。
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def _selected_manual_tickers(manual_tickers: list[str] | None) -> list[str]:
    if not isinstance(manual_tickers, list):
        return []
    return [ticker for ticker in (str(value).strip() for value in manual_tickers) if ticker]


def _render_analysis_submission_summary(summary: dict[str, str]) -> None:
    st.markdown(
        f"""<section class="analysis-submission-summary is-{escape(summary.get("state", "attention"))}" aria-label="分析送出前確認">
<span>送出前確認</span>
<strong>{escape(summary.get("title", ""))}</strong>
<p>{escape(summary.get("detail", ""))}</p>
<em>{escape(summary.get("next_step", ""))}</em>
</section>""",
        unsafe_allow_html=True,
    )


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
    st.markdown(
        f"""<section class="operator-workbench" aria-label="今日狀態">
<div class="operator-workbench-head">
<div>
<div class="workspace-kicker">今日狀態</div>
<h2>{escape(overall["label"])}</h2>
<p>{escape(overall["detail"])}</p>
</div>
<span class="operator-state is-{escape(overall["state"])}">{escape(overall["state"])}</span>
</div>
</section>""",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""<section class="operator-status-grid" aria-label="狀態摘要">
{card_html}
</section>""",
        unsafe_allow_html=True,
    )


def _latest_report_id(reports: list[dict]) -> int | None:
    for report in reports:
        if not isinstance(report, dict) or report.get("id") is None:
            continue
        try:
            return int(report["id"])
        except (TypeError, ValueError):
            return None
    return None


def _operator_decision_html(
    primary_action: dict,
    secondary_actions: list[dict],
    *,
    include_secondary: bool = True,
) -> str:
    secondary_block = (
        _operator_secondary_actions_html(secondary_actions)
        if include_secondary and secondary_actions
        else ""
    )
    source_ids = primary_action.get("source_ids") or []
    source_text = _operator_source_text(source_ids)
    target = operator_route_target(primary_action.get("route_hint"))
    target_caption = str(target.get("caption") or "")
    return f"""<section class="operator-decision-card is-{escape(primary_action.get("state", "attention"))}">
<div class="operator-decision-copy">
<div class="workspace-kicker">下一步建議</div>
<h3>{escape(primary_action.get("title", "-"))}</h3>
<p>{escape(primary_action.get("reason", ""))}</p>
<div class="operator-decision-meta">
<span>風險：{escape(primary_action.get("risk", ""))}</span>
<span>影響：{escape(primary_action.get("impact", ""))}</span>
<span>來源：{escape(source_text)}</span>
</div>
</div>
<div class="operator-decision-action">
<strong>{escape(primary_action.get("action_label", "-"))}</strong>
<span>{escape(target_caption)}</span>
</div>
{secondary_block}
</section>"""


def _operator_secondary_actions_html(secondary_actions: list[dict]) -> str:
    secondary_html = "\n".join(_secondary_action_html(action) for action in secondary_actions)
    return f"""<div class="operator-secondary-actions" aria-label="次要建議">
{secondary_html}
</div>"""


def _operator_source_text(source_ids: object) -> str:
    if not isinstance(source_ids, list) or not source_ids:
        return "系統狀態"
    labels = []
    for source_id in source_ids:
        source_text = str(source_id).strip()
        if not source_text:
            continue
        if _looks_like_operator_route(source_text):
            labels.append(str(operator_route_target(source_text).get("caption") or source_text))
        else:
            labels.append(source_text)
    return "、".join(labels) if labels else "系統狀態"


def _looks_like_operator_route(value: str) -> bool:
    return bool(
        value in {"analysis", "data_enrichment", "report_center"}
        or value.startswith(("report:", "task:", "settings:", "data_enrichment:"))
    )


def _render_operator_primary_action_control(primary_action: dict) -> None:
    st.markdown(
        """<section class="operator-action-controls is-primary" aria-label="主要建議操作"></section>""",
        unsafe_allow_html=True,
    )
    _render_operator_route_button(
        primary_action,
        key="operator_route_primary_action",
        primary=True,
        show_caption=False,
    )


def _render_operator_action_controls(secondary_actions: list[dict]) -> None:
    if not secondary_actions:
        return
    st.markdown(
        """<section class="operator-action-controls" aria-label="建議操作">
<span>次要操作</span>
<strong>其他可開啟的處理頁面</strong>
</section>""",
        unsafe_allow_html=True,
    )
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


def _secondary_action_html(action: dict) -> str:
    target = operator_route_target(action.get("route_hint"))
    target_caption = str(target.get("caption") or "")
    return f"""<article class="operator-secondary-action is-{escape(action.get("state", "attention"))}">
<strong>{escape(action.get("title", "-"))}</strong>
<span>{escape(action.get("detail", ""))}</span>
<em>{escape(target_caption)}</em>
</article>"""


def _operator_card_html(card: dict[str, str]) -> str:
    return f"""<article class="operator-status-card is-{escape(card.get("state", "attention"))}">
<div class="operator-card-title">{escape(card.get("title", "-"))}</div>
<div class="operator-card-value">{escape(card.get("value", "-"))}</div>
<div class="operator-card-caption">{escape(card.get("caption", ""))}</div>
<div class="operator-card-action">{escape(card.get("action_label", ""))}</div>
</article>"""
