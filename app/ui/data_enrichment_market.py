from __future__ import annotations

from datetime import timedelta

import streamlit as st

from app.core.time import today_taipei
from app.ui.api_client import (
    API_TASK_PREFLIGHT_TIMEOUT_SECONDS,
    task_payload_dates,
)
from app.ui.api_loaders import load_api_json_or_default
from app.ui.background_tasks import submit_data_operation_task
from app.ui.dashboard_core import render_section_header
from app.ui.data_gap_actions import (
    data_gap_action_items,
)
from app.ui.data_enrichment_common import (
    DATA_TASK_STATUS_STATE_KEYS,
    render_last_data_task_status,
)
from app.ui.data_enrichment_runtime import (
    company_filing_runtime_rows,
    company_filing_visual_rag_model_chain_rows,
)
from app.ui.data_enrichment_market_operations import (
    allowed_market_tickers,
    default_market_tickers,
    market_data_operation_button_type,
    task_queue_block_reason,
    task_queue_status_from_service_snapshot,
)
from app.ui.data_enrichment_market_presenter import (
    market_cache_operator_summary,
    market_operation_readiness_rows,
    market_submission_preflight_summary,
    pending_market_handoff_summary,
    pending_market_selection_state,
)
from app.ui.data_enrichment_market_cache import render_market_cache_panel
from app.ui.data_enrichment_market_view import (
    data_gap_action_controls_html,
    data_gap_action_map_html,
    market_action_impact_grid_html,
    market_allowlist_warning_html,
    market_operation_readiness_html,
    market_submission_summary_html,
    pending_market_handoff_html,
)
from app.ui.operator_route_controls import render_operator_route_button

__all__ = [
    "market_cache_operator_summary",
    "render_market_data_tab",
]


def render_market_data_tab(allowed_tickers: list[str]) -> None:
    render_section_header(
        "市場資料", "刷新股價、五年財報與估值資料；這些資料會影響品質門檻與投資行動限制。"
    )
    status_snapshot = load_api_json_or_default(
        "/db/status",
        {"tables": {}},
        error_message="讀取資料庫狀態失敗",
    )
    table_counts = status_snapshot.get("tables", {})
    count_cols = st.columns(5)
    count_cols[0].metric(
        "股價快取", table_counts.get("stock_price_snapshots", {}).get("count") or 0
    )
    count_cols[1].metric(
        "月營收快取", table_counts.get("monthly_revenue_snapshots", {}).get("count") or 0
    )
    count_cols[2].metric(
        "財報三表快取", table_counts.get("financial_metric_snapshots", {}).get("count") or 0
    )
    count_cols[3].metric(
        "估值快取", table_counts.get("valuation_metric_snapshots", {}).get("count") or 0
    )
    count_cols[4].metric("公司文件", table_counts.get("company_filings", {}).get("count") or 0)

    service_snapshot = load_api_json_or_default(
        "/services/status",
        {},
        error_message="讀取公司文件能力狀態失敗",
        timeout=API_TASK_PREFLIGHT_TIMEOUT_SECONDS,
    )
    runtime_rows = company_filing_runtime_rows(service_snapshot)
    visual_rag_chain_rows = company_filing_visual_rag_model_chain_rows(service_snapshot)
    if runtime_rows:
        with st.expander("公司文件補抓能力", expanded=False):
            st.dataframe(runtime_rows, width="stretch", hide_index=True)
            if visual_rag_chain_rows:
                st.caption("Visual RAG 模型鏈")
                st.dataframe(visual_rag_chain_rows, width="stretch", hide_index=True)

    latest_report_payload, latest_follow_up_plan = _latest_report_follow_up_context()
    _render_data_gap_action_map(data_gap_action_items(latest_report_payload, latest_follow_up_plan))

    _apply_pending_market_data_selection(allowed_tickers)
    _render_pending_market_selection_notice()
    selected_market_tickers = st.multiselect(
        "選擇要刷新或補文件的股票",
        options=allowed_tickers,
        key="market_data_tickers",
    )
    pending_operation = _render_pending_operation_notice(selected_market_tickers)
    col_start, col_end = st.columns(2)
    with col_start:
        market_start = st.date_input(
            "起始日期", value=today_taipei().replace(day=1), key="market_start"
        )
    with col_end:
        market_end = st.date_input("結束日期", value=today_taipei(), key="market_end")

    has_market_selection = bool(selected_market_tickers)
    has_valid_market_range = market_start <= market_end
    task_queue_status = task_queue_status_from_service_snapshot(service_snapshot)
    task_queue_blocks_submission = bool(task_queue_block_reason(task_queue_status))
    operation_readiness = market_operation_readiness_rows(
        selected_market_tickers=selected_market_tickers,
        market_start=market_start,
        market_end=market_end,
        pending_operation=pending_operation,
        task_queue=task_queue_status,
    )
    if not has_market_selection:
        st.caption("請先選擇至少一檔股票。")
    if not has_valid_market_range:
        st.error("起始日期不可晚於結束日期。")
    _render_market_operation_readiness(operation_readiness)
    market_operation_confirmed = st.checkbox(
        "我了解這會送出資料補強背景任務",
        value=False,
        key="confirm_market_data_operation_submission",
    )
    _render_market_submission_summary(
        market_submission_preflight_summary(
            selected_market_tickers=selected_market_tickers,
            market_start=market_start,
            market_end=market_end,
            pending_operation=pending_operation,
            task_queue=task_queue_status,
            confirmed=market_operation_confirmed,
        )
    )
    if not market_operation_confirmed:
        st.caption("避免誤觸刷新；確認股票、日期與操作後才會送出背景任務。")

    refresh_cols = st.columns(4)
    refresh_price = refresh_cols[0].button(
        "刷新股價",
        type=market_data_operation_button_type(pending_operation, "market_refresh"),
        disabled=task_queue_blocks_submission
        or not market_operation_confirmed
        or not (has_market_selection and has_valid_market_range),
    )
    refresh_financials = refresh_cols[1].button(
        "刷新 5 年財報",
        type=market_data_operation_button_type(pending_operation, "fundamentals_refresh"),
        disabled=task_queue_blocks_submission
        or not market_operation_confirmed
        or not has_market_selection,
    )
    refresh_valuations = refresh_cols[2].button(
        "刷新估值",
        type=market_data_operation_button_type(pending_operation, "valuation_refresh"),
        disabled=task_queue_blocks_submission
        or not market_operation_confirmed
        or not (has_market_selection and has_valid_market_range),
    )
    refresh_filings = refresh_cols[3].button(
        "補抓公司文件",
        type=market_data_operation_button_type(pending_operation, "company_filings_fetch"),
        disabled=task_queue_blocks_submission
        or not market_operation_confirmed
        or not has_market_selection,
    )
    st.markdown(market_action_impact_grid_html(), unsafe_allow_html=True)

    data_task_payload = {
        "tickers": selected_market_tickers,
        **task_payload_dates(market_start, market_end),
    }
    if refresh_price:
        submit_data_operation_task(
            "market_refresh",
            data_task_payload,
            status_state_keys=DATA_TASK_STATUS_STATE_KEYS,
            success_message="已送出股價刷新背景任務",
            error_message="股價刷新任務送出失敗",
        )

    if refresh_financials:
        submit_data_operation_task(
            "fundamentals_refresh",
            {
                "tickers": selected_market_tickers,
                **task_payload_dates(market_end - timedelta(days=365 * 6), market_end),
            },
            status_state_keys=DATA_TASK_STATUS_STATE_KEYS,
            success_message="已送出財報刷新背景任務",
            error_message="財報刷新任務送出失敗",
        )

    if refresh_valuations:
        submit_data_operation_task(
            "valuation_refresh",
            data_task_payload,
            status_state_keys=DATA_TASK_STATUS_STATE_KEYS,
            success_message="已送出估值刷新背景任務",
            error_message="估值刷新任務送出失敗",
        )

    if refresh_filings:
        submit_data_operation_task(
            "company_filings_fetch",
            {"tickers": selected_market_tickers},
            status_state_keys=DATA_TASK_STATUS_STATE_KEYS,
            success_message="已送出公司文件補抓背景任務",
            error_message="公司文件補抓任務送出失敗",
        )

    render_last_data_task_status(
        label="refresh_data_task_status",
        key="data_task_id_lookup",
        expanded=True,
    )
    _render_cache_summary(allowed_tickers)


def _latest_report_follow_up_context() -> tuple[dict, dict]:
    reports = load_api_json_or_default(
        "/reports?limit=1",
        [],
        error_message="讀取最新版報告失敗",
        notify="warning",
    )
    if not isinstance(reports, list) or not reports:
        return {}, {}
    latest_report_id = reports[0].get("id") if isinstance(reports[0], dict) else None
    if latest_report_id is None:
        return {}, {}
    report_payload = load_api_json_or_default(
        f"/reports/{int(latest_report_id)}",
        {},
        error_message="讀取最新版報告內容失敗",
        notify="warning",
    )
    follow_up_plan = load_api_json_or_default(
        f"/reports/{int(latest_report_id)}/follow-up/plan",
        {},
        error_message="讀取最新版補強計畫失敗",
        notify="warning",
    )
    return (
        report_payload if isinstance(report_payload, dict) else {},
        follow_up_plan if isinstance(follow_up_plan, dict) else {},
    )


def _render_data_gap_action_map(items: list[dict]) -> None:
    st.markdown(data_gap_action_map_html(items), unsafe_allow_html=True)
    _render_data_gap_action_controls(items)


def _render_data_gap_action_controls(items: list[dict]) -> None:
    actionable_items = [item for item in items if item.get("route_hint")]
    if not actionable_items:
        return
    st.markdown(data_gap_action_controls_html(), unsafe_allow_html=True)
    columns = st.columns(min(3, len(actionable_items)))
    for index, item in enumerate(actionable_items[:3]):
        with columns[index]:
            render_operator_route_button(
                {
                    "action_label": item.get("action_label"),
                    "route_hint": item.get("route_hint"),
                },
                key=f"data_gap_action_{index}",
                primary=index == 0,
                show_caption=True,
            )


def _apply_pending_market_data_selection(allowed_tickers: list[str]) -> None:
    pending_tickers = st.session_state.pop("pending_data_enrichment_tickers", None)
    if pending_tickers is not None:
        selection_state = pending_market_selection_state(pending_tickers, allowed_tickers)
        st.session_state["market_data_tickers"] = selection_state["selected"]
        if selection_state["rejected"]:
            st.session_state["pending_market_selection_state"] = selection_state
        else:
            st.session_state.pop("pending_market_selection_state", None)
        return
    if "market_data_tickers" not in st.session_state:
        st.session_state["market_data_tickers"] = default_market_tickers(allowed_tickers)
        return
    st.session_state["market_data_tickers"] = allowed_market_tickers(
        st.session_state.get("market_data_tickers"),
        allowed_tickers,
    )


def _render_pending_market_selection_notice() -> None:
    selection_state = st.session_state.get("pending_market_selection_state")
    if not isinstance(selection_state, dict) or not selection_state.get("rejected"):
        return
    st.markdown(market_allowlist_warning_html(selection_state), unsafe_allow_html=True)
    render_operator_route_button(
        {
            "action_label": selection_state.get("action_label"),
            "route_hint": selection_state.get("route_hint"),
        },
        key="market_pending_allowlist_route",
        show_caption=True,
    )


def _render_pending_operation_notice(selected_market_tickers: list[str]) -> str | None:
    pending_operation = st.session_state.pop("pending_data_enrichment_operation", None)
    if not pending_operation:
        return None
    _render_pending_market_handoff(
        pending_market_handoff_summary(
            selected_market_tickers=selected_market_tickers,
            pending_operation=str(pending_operation),
            selection_state=st.session_state.get("pending_market_selection_state"),
        )
    )
    return str(pending_operation)


def _render_pending_market_handoff(summary: dict[str, str]) -> None:
    if not summary:
        return
    st.markdown(pending_market_handoff_html(summary), unsafe_allow_html=True)


def _render_market_operation_readiness(rows: list[dict[str, str]]) -> None:
    st.markdown(market_operation_readiness_html(rows), unsafe_allow_html=True)


def _render_market_submission_summary(summary: dict[str, str]) -> None:
    st.markdown(market_submission_summary_html(summary), unsafe_allow_html=True)


def _render_cache_summary(allowed_tickers: list[str]) -> None:
    render_market_cache_panel(allowed_tickers)
