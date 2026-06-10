from __future__ import annotations

from datetime import timedelta
from html import escape

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
    data_gap_action_summary,
)
from app.ui.data_enrichment_common import (
    DATA_TASK_STATUS_STATE_KEYS,
    render_last_data_task_status,
)
from app.ui.data_enrichment_runtime import (
    company_filing_runtime_rows,
    company_filing_visual_rag_model_chain_rows,
)
from app.ui.operator_route_controls import render_operator_route_button
from app.ui.operator_routes import DATA_ENRICHMENT_OPERATION_LABELS

MARKET_DATA_OPERATIONS = {
    "market_refresh",
    "fundamentals_refresh",
    "valuation_refresh",
    "company_filings_fetch",
}


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
    if not has_market_selection:
        st.caption("請先選擇至少一檔股票。")
    if not has_valid_market_range:
        st.error("起始日期不可晚於結束日期。")

    refresh_cols = st.columns(4)
    refresh_price = refresh_cols[0].button(
        "刷新股價",
        type=market_data_operation_button_type(pending_operation, "market_refresh"),
        disabled=not (has_market_selection and has_valid_market_range),
    )
    refresh_financials = refresh_cols[1].button(
        "刷新 5 年財報",
        type=market_data_operation_button_type(pending_operation, "fundamentals_refresh"),
        disabled=not has_market_selection,
    )
    refresh_valuations = refresh_cols[2].button(
        "刷新估值",
        type=market_data_operation_button_type(pending_operation, "valuation_refresh"),
        disabled=not (has_market_selection and has_valid_market_range),
    )
    refresh_filings = refresh_cols[3].button(
        "補抓公司文件",
        type=market_data_operation_button_type(pending_operation, "company_filings_fetch"),
        disabled=not has_market_selection,
    )
    st.markdown(
        """<div class="action-impact-grid" aria-label="資料補強影響">
<div><strong>刷新股價</strong><span>會更新最新版報告的股價與成交量判讀</span></div>
<div><strong>刷新 5 年財報</strong><span>會補齊五年財務與品質門檻需要的財報資料</span></div>
<div><strong>刷新估值</strong><span>會更新本益比、股價淨值比與殖利率判讀</span></div>
<div><strong>補抓公司文件</strong><span>會補齊公司文件、法說會或公開資訊缺口</span></div>
</div>""",
        unsafe_allow_html=True,
    )

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
    summary = data_gap_action_summary(items)
    cards_html = "\n".join(_data_gap_action_card_html(item) for item in items[:6])
    if not cards_html:
        cards_html = """<article class="data-gap-action-card is-ready">
<strong>目前沒有必要資料缺口</strong>
<span>最新版報告沒有必補資料行動。</span>
<em>可依例行需求刷新市場資料。</em>
</article>"""
    st.markdown(
        f"""<section class="data-gap-action-map is-{escape(summary.get("state", "ready"))}" aria-label="資料缺口行動地圖">
<div class="data-gap-action-head">
<div class="workspace-kicker">資料缺口行動地圖</div>
<h3>{escape(summary.get("label", "-"))}</h3>
<p>{escape(summary.get("detail", ""))}</p>
</div>
<div class="data-gap-action-list">
{cards_html}
</div>
</section>""",
        unsafe_allow_html=True,
    )
    _render_data_gap_action_controls(items)


def _data_gap_action_card_html(item: dict) -> str:
    return f"""<article class="data-gap-action-card is-{escape(item.get("purpose", "tracking"))}">
<strong>{escape(item.get("action_label", "-"))}</strong>
<span>{escape(item.get("ticker", "全部"))}｜{escape(item.get("impact", ""))}</span>
<em>{escape(item.get("post_action_hint", ""))}</em>
</article>"""


def _render_data_gap_action_controls(items: list[dict]) -> None:
    actionable_items = [item for item in items if item.get("route_hint")]
    if not actionable_items:
        return
    st.markdown(
        """<div class="data-gap-action-controls" aria-label="資料缺口快捷處理">
<span>可直接處理</span>
<strong>選一個缺口開始補強</strong>
</div>""",
        unsafe_allow_html=True,
    )
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
    selected_tickers = _allowed_pending_tickers(pending_tickers, allowed_tickers)
    if selected_tickers:
        st.session_state["market_data_tickers"] = selected_tickers
        return
    if "market_data_tickers" not in st.session_state:
        st.session_state["market_data_tickers"] = _default_market_tickers(allowed_tickers)
        return
    st.session_state["market_data_tickers"] = _allowed_pending_tickers(
        st.session_state.get("market_data_tickers"),
        allowed_tickers,
    )


def market_data_operation_button_type(
    pending_operation: str | None,
    operation: str,
) -> str:
    pending = str(pending_operation or "").strip()
    if pending in MARKET_DATA_OPERATIONS:
        return "primary" if pending == operation else "secondary"
    return "primary" if operation == "market_refresh" else "secondary"


def _render_pending_operation_notice(selected_market_tickers: list[str]) -> str | None:
    pending_operation = st.session_state.pop("pending_data_enrichment_operation", None)
    if not pending_operation:
        return None
    operation_label = DATA_ENRICHMENT_OPERATION_LABELS.get(pending_operation, "資料補強")
    ticker_label = "、".join(selected_market_tickers) if selected_market_tickers else "尚未選擇股票"
    st.info(f"已依建議準備「{operation_label}」，股票：{ticker_label}。確認日期後按下對應按鈕送出背景任務。")
    return str(pending_operation)


def _allowed_pending_tickers(value: object, allowed_tickers: list[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    allowed = set(allowed_tickers)
    return [str(ticker).strip() for ticker in value if str(ticker).strip() in allowed]


def _default_market_tickers(allowed_tickers: list[str]) -> list[str]:
    return ["2330"] if "2330" in allowed_tickers else allowed_tickers[:1]


def _render_cache_summary(allowed_tickers: list[str]) -> None:
    cache_summary = load_api_json_or_default(
        "/market/cache-summary?tickers=" + ",".join(allowed_tickers),
        {
            "market_snapshots": [],
            "valuations": [],
            "company_filings": [],
            "financial_metric_count": 0,
        },
        error_message="讀取市場快取失敗",
    )
    cached_snapshots = cache_summary.get("market_snapshots") or []
    cached_valuations = cache_summary.get("valuations") or []
    cached_filings = cache_summary.get("company_filings") or []
    cached_financial_count = cache_summary.get("financial_metric_count") or 0

    cache_tabs = st.tabs(["股價快取", "估值快取", "公司文件"])
    with cache_tabs[0]:
        if cached_snapshots:
            st.dataframe(
                [
                    {
                        "股票": snapshot.get("ticker"),
                        "交易日": snapshot.get("trade_date"),
                        "收盤價": snapshot.get("close"),
                        "漲跌": snapshot.get("spread"),
                        "成交量": snapshot.get("trading_volume"),
                        "來源": snapshot.get("source"),
                        "更新時間 UTC": snapshot.get("fetched_at"),
                    }
                    for snapshot in cached_snapshots
                    if isinstance(snapshot, dict)
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("尚無市場資料快取。")
        st.caption(f"目前財報三表科目快取：{cached_financial_count} 筆")
    with cache_tabs[1]:
        if cached_valuations:
            st.dataframe(
                [
                    {
                        "股票": valuation.get("ticker"),
                        "交易日": valuation.get("trade_date"),
                        "本益比": valuation.get("pe_ratio"),
                        "股價淨值比": valuation.get("pb_ratio"),
                        "殖利率": valuation.get("dividend_yield"),
                        "來源": valuation.get("source"),
                        "更新時間 UTC": valuation.get("fetched_at"),
                    }
                    for valuation in cached_valuations
                    if isinstance(valuation, dict)
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("尚無估值資料快取。")
    with cache_tabs[2]:
        if cached_filings:
            st.dataframe(
                [
                    {
                        "股票": filing.get("ticker"),
                        "類型": filing.get("document_type"),
                        "標題": filing.get("title"),
                        "來源": filing.get("publisher"),
                        "日期": filing.get("published_at"),
                    }
                    for filing in cached_filings
                    if isinstance(filing, dict)
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("尚無公司文件快取。")
