from __future__ import annotations

from datetime import timedelta
from html import escape
from typing import Any

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

MARKET_OPERATION_METADATA = {
    "market_refresh": {
        "label": "刷新股價",
        "impact": "更新最新版報告的股價與成交量判讀。",
        "date_mode": "range",
    },
    "fundamentals_refresh": {
        "label": "刷新 5 年財報",
        "impact": "補齊五年財務與品質門檻需要的財報資料。",
        "date_mode": "six_years",
    },
    "valuation_refresh": {
        "label": "刷新估值",
        "impact": "更新本益比、股價淨值比與殖利率判讀。",
        "date_mode": "range",
    },
    "company_filings_fetch": {
        "label": "補抓公司文件",
        "impact": "補齊公司文件、法說會或公開資訊缺口。",
        "date_mode": "none",
    },
}

MARKET_OPERATION_ORDER = [
    "market_refresh",
    "fundamentals_refresh",
    "valuation_refresh",
    "company_filings_fetch",
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
    task_queue_status = _task_queue_status_from_service_snapshot(service_snapshot)
    task_queue_blocks_submission = bool(_task_queue_block_reason(task_queue_status))
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

    refresh_cols = st.columns(4)
    refresh_price = refresh_cols[0].button(
        "刷新股價",
        type=market_data_operation_button_type(pending_operation, "market_refresh"),
        disabled=task_queue_blocks_submission
        or not (has_market_selection and has_valid_market_range),
    )
    refresh_financials = refresh_cols[1].button(
        "刷新 5 年財報",
        type=market_data_operation_button_type(pending_operation, "fundamentals_refresh"),
        disabled=task_queue_blocks_submission or not has_market_selection,
    )
    refresh_valuations = refresh_cols[2].button(
        "刷新估值",
        type=market_data_operation_button_type(pending_operation, "valuation_refresh"),
        disabled=task_queue_blocks_submission
        or not (has_market_selection and has_valid_market_range),
    )
    refresh_filings = refresh_cols[3].button(
        "補抓公司文件",
        type=market_data_operation_button_type(pending_operation, "company_filings_fetch"),
        disabled=task_queue_blocks_submission or not has_market_selection,
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


def pending_market_selection_state(
    pending_tickers: object,
    allowed_tickers: list[str],
) -> dict[str, Any]:
    requested = _normalized_pending_tickers(pending_tickers)
    allowed = {str(ticker).strip() for ticker in allowed_tickers if str(ticker).strip()}
    selected = [ticker for ticker in requested if ticker in allowed]
    rejected = [ticker for ticker in requested if ticker not in allowed]
    if rejected:
        selected_detail = (
            f"已先選取可用股票：{'、'.join(selected)}。"
            if selected
            else "目前沒有可用股票可自動選取。"
        )
        return {
            "selected": selected,
            "rejected": rejected,
            "state": "attention",
            "detail": f"建議股票未在目前白名單：{'、'.join(rejected)}。{selected_detail}",
            "action_label": "檢查股票範圍",
            "route_hint": "settings:scope",
        }
    return {
        "selected": selected,
        "rejected": [],
        "state": "ready",
        "detail": "",
        "action_label": "",
        "route_hint": "",
    }


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
        st.session_state["market_data_tickers"] = _default_market_tickers(allowed_tickers)
        return
    st.session_state["market_data_tickers"] = _allowed_pending_tickers(
        st.session_state.get("market_data_tickers"),
        allowed_tickers,
    )


def _render_pending_market_selection_notice() -> None:
    selection_state = st.session_state.get("pending_market_selection_state")
    if not isinstance(selection_state, dict) or not selection_state.get("rejected"):
        return
    st.markdown(
        f"""<section class="market-allowlist-warning is-{escape(selection_state.get("state", "attention"))}" aria-label="白名單提醒">
<span>白名單提醒</span>
<strong>{escape(str(selection_state.get("detail") or ""))}</strong>
</section>""",
        unsafe_allow_html=True,
    )
    render_operator_route_button(
        {
            "action_label": selection_state.get("action_label"),
            "route_hint": selection_state.get("route_hint"),
        },
        key="market_pending_allowlist_route",
        show_caption=True,
    )


def _normalized_pending_tickers(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    tickers = []
    seen = set()
    for ticker in value:
        text = str(ticker).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        tickers.append(text)
    return tickers


def market_data_operation_button_type(
    pending_operation: str | None,
    operation: str,
) -> str:
    pending = str(pending_operation or "").strip()
    if pending in MARKET_DATA_OPERATIONS:
        return "primary" if pending == operation else "secondary"
    return "primary" if operation == "market_refresh" else "secondary"


def market_operation_readiness_rows(
    *,
    selected_market_tickers: list[str],
    market_start: Any,
    market_end: Any,
    pending_operation: str | None,
    task_queue: dict | None = None,
) -> list[dict[str, str]]:
    selected_count = len([ticker for ticker in selected_market_tickers if str(ticker).strip()])
    has_market_selection = selected_count > 0
    has_valid_market_range = market_start <= market_end
    task_queue_block_reason = _task_queue_block_reason(task_queue)

    rows = []
    for operation in MARKET_OPERATION_ORDER:
        metadata = MARKET_OPERATION_METADATA[operation]
        disabled_reason = _market_operation_disabled_reason(
            operation,
            has_market_selection=has_market_selection,
            has_valid_market_range=has_valid_market_range,
            task_queue_block_reason=task_queue_block_reason,
        )
        state = "blocked" if task_queue_block_reason else "ready" if not disabled_reason else "attention"
        rows.append(
            {
                "operation": operation,
                "label": metadata["label"],
                "state": state,
                "selected": "yes" if str(pending_operation or "").strip() == operation else "no",
                "caption": _market_operation_caption(
                    selected_count,
                    date_mode=metadata["date_mode"],
                    market_start=market_start,
                    market_end=market_end,
                ),
                "disabled_reason": disabled_reason or "可送出背景任務",
                "impact": metadata["impact"],
                "post_action_hint": "完成後回報告中心確認是否需要重跑。",
                "button_type": market_data_operation_button_type(pending_operation, operation),
            }
        )
    return rows


def market_cache_operator_summary(cache_summary: dict) -> list[dict[str, str]]:
    ticker_count = _ticker_count(cache_summary)
    snapshots = _dict_rows(cache_summary.get("market_snapshots"))
    valuations = _dict_rows(cache_summary.get("valuations"))
    filings = _dict_rows(cache_summary.get("company_filings"))
    financial_count = _int_value(cache_summary.get("financial_metric_count"))

    return [
        _market_cache_row(
            title="股價快取",
            rows=snapshots,
            ticker_count=ticker_count,
            date_key="trade_date",
            missing_action="刷新股價",
            empty_caption="尚無股價快取；建議刷新股價。",
            ready_action="可沿用",
        ),
        _market_cache_row(
            title="估值快取",
            rows=valuations,
            ticker_count=ticker_count,
            date_key="trade_date",
            missing_action="刷新估值",
            empty_caption="尚無估值快取；建議刷新估值。",
            ready_action="可沿用",
        ),
        {
            "title": "財報快取",
            "value": f"{financial_count} 筆",
            "state": "ready" if financial_count else "attention",
            "caption": (
                f"財報三表科目快取 {financial_count} 筆。"
                if financial_count
                else "尚無財報三表科目快取；建議刷新 5 年財報。"
            ),
            "action_label": "可沿用" if financial_count else "刷新 5 年財報",
        },
        {
            "title": "公司文件",
            "value": f"{len(filings)} 筆",
            "state": "ready" if filings else "attention",
            "caption": (
                f"最新文件日期 {_latest_date(filings, 'published_at')}。"
                if filings and _latest_date(filings, "published_at")
                else (
                    f"公司文件快取 {len(filings)} 筆。"
                    if filings
                    else "尚無公司文件快取；若報告缺法說或公開資訊，請補抓公司文件。"
                )
            ),
            "action_label": "可沿用" if filings else "補抓公司文件",
        },
    ]


def _market_operation_disabled_reason(
    operation: str,
    *,
    has_market_selection: bool,
    has_valid_market_range: bool,
    task_queue_block_reason: str = "",
) -> str:
    if task_queue_block_reason:
        return task_queue_block_reason
    if not has_market_selection:
        return "請先選擇至少一檔股票"
    if operation in {"market_refresh", "valuation_refresh"} and not has_valid_market_range:
        return "起始日期不可晚於結束日期"
    return ""


def _task_queue_status_from_service_snapshot(service_snapshot: dict) -> dict:
    if not isinstance(service_snapshot, dict):
        return {}
    task_queue = service_snapshot.get("task_queue")
    return task_queue if isinstance(task_queue, dict) else {}


def _task_queue_block_reason(task_queue: dict | None) -> str:
    if task_queue is None:
        return ""
    if not isinstance(task_queue, dict) or not task_queue:
        return "尚未取得背景任務狀態"
    if not task_queue.get("ready"):
        return "背景任務未就緒，請先到維護頁檢查 Redis/Celery"
    if task_queue.get("worker_online") is False:
        return "背景任務未就緒，請先到維護頁檢查 Worker"
    if "processing_ready" in task_queue and not task_queue.get("processing_ready"):
        return "背景任務未就緒，請先到維護頁檢查 Worker"
    return ""


def _market_operation_caption(
    selected_count: int,
    *,
    date_mode: str,
    market_start: Any,
    market_end: Any,
) -> str:
    ticker_label = f"{selected_count} 檔" if selected_count else "尚未選擇股票"
    if date_mode == "range":
        return f"{ticker_label}｜{_date_text(market_start)} → {_date_text(market_end)}"
    if date_mode == "six_years":
        return f"{ticker_label}｜近 6 年至 {_date_text(market_end)}"
    return f"{ticker_label}｜不需日期範圍"


def _date_text(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _render_pending_operation_notice(selected_market_tickers: list[str]) -> str | None:
    pending_operation = st.session_state.pop("pending_data_enrichment_operation", None)
    if not pending_operation:
        return None
    operation_label = DATA_ENRICHMENT_OPERATION_LABELS.get(pending_operation, "資料補強")
    ticker_label = "、".join(selected_market_tickers) if selected_market_tickers else "尚未選擇股票"
    st.info(f"已依建議準備「{operation_label}」，股票：{ticker_label}。確認日期後按下對應按鈕送出背景任務。")
    return str(pending_operation)


def _render_market_operation_readiness(rows: list[dict[str, str]]) -> None:
    cards_html = "\n".join(_market_operation_readiness_card_html(row) for row in rows)
    st.markdown(
        f"""<section class="market-operation-readiness" aria-label="資料補強執行前檢查">
<div class="market-operation-readiness-head">
<div class="workspace-kicker">執行前檢查</div>
<h3>先確認能否送出背景任務</h3>
<p>每個刷新操作會先檢查背景任務、股票、日期與目前建議操作；可送出時再按下方按鈕。</p>
</div>
<div class="market-operation-readiness-list">
{cards_html}
</div>
</section>""",
        unsafe_allow_html=True,
    )


def _market_operation_readiness_card_html(row: dict[str, str]) -> str:
    selected_class = " is-selected" if row.get("selected") == "yes" else ""
    return f"""<article class="market-operation-card is-{escape(row.get("state", "attention"))}{selected_class}">
<span>{escape(row.get("label", "-"))}</span>
<strong>{escape(row.get("disabled_reason", ""))}</strong>
<em>{escape(row.get("caption", ""))}</em>
<small>{escape(row.get("impact", ""))} {escape(row.get("post_action_hint", ""))}</small>
</article>"""


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
    _render_market_cache_operator_summary(cache_summary)
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


def _render_market_cache_operator_summary(cache_summary: dict) -> None:
    rows = market_cache_operator_summary(cache_summary if isinstance(cache_summary, dict) else {})
    cards_html = "\n".join(_market_cache_card_html(row) for row in rows)
    st.markdown(
        f"""<section class="market-cache-readiness" aria-label="市場快取新鮮度">
<div class="market-cache-readiness-head">
<div class="workspace-kicker">市場快取新鮮度</div>
<h3>先刷新最會影響報告判讀的資料</h3>
<p>股價、估值、財報與公司文件會影響最新版報告的品質門檻與補強建議。</p>
</div>
<div class="market-cache-readiness-list">
{cards_html}
</div>
</section>""",
        unsafe_allow_html=True,
    )


def _market_cache_card_html(row: dict[str, str]) -> str:
    return f"""<article class="market-cache-card is-{escape(row.get("state", "attention"))}">
<span>{escape(row.get("title", "-"))}</span>
<strong>{escape(row.get("value", "-"))}</strong>
<em>{escape(row.get("caption", ""))}</em>
<small>{escape(row.get("action_label", ""))}</small>
</article>"""


def _market_cache_row(
    *,
    title: str,
    rows: list[dict],
    ticker_count: int,
    date_key: str,
    missing_action: str,
    empty_caption: str,
    ready_action: str,
) -> dict[str, str]:
    row_count = len(rows)
    value = _coverage_value(row_count, ticker_count)
    if not rows:
        return {
            "title": title,
            "value": value,
            "state": "attention",
            "caption": empty_caption,
            "action_label": missing_action,
        }

    missing_count = max(0, ticker_count - row_count) if ticker_count else 0
    stale = _has_stale_cache_source(rows)
    if stale or missing_count:
        reasons = []
        if stale:
            reasons.append("含快取救援資料")
        if missing_count:
            reasons.append(f"缺 {missing_count} 檔")
        return {
            "title": title,
            "value": value,
            "state": "attention",
            "caption": "，".join(reasons) + f"；建議{missing_action}。",
            "action_label": missing_action,
        }

    latest_date = _latest_date(rows, date_key)
    return {
        "title": title,
        "value": value,
        "state": "ready",
        "caption": f"最新交易日 {latest_date}。" if latest_date else f"已有 {row_count} 檔快取。",
        "action_label": ready_action,
    }


def _coverage_value(row_count: int, ticker_count: int) -> str:
    if ticker_count:
        return f"{row_count} / {ticker_count} 檔"
    return f"{row_count} 檔"


def _has_stale_cache_source(rows: list[dict]) -> bool:
    return any("cached-stale" in str(row.get("source") or "") for row in rows)


def _latest_date(rows: list[dict], key: str) -> str:
    dates = sorted(
        str(row.get(key) or "")[:10]
        for row in rows
        if isinstance(row, dict) and str(row.get(key) or "").strip()
    )
    return dates[-1] if dates else ""


def _ticker_count(cache_summary: dict) -> int:
    tickers = cache_summary.get("tickers") if isinstance(cache_summary, dict) else []
    return len(tickers) if isinstance(tickers, list) else 0


def _dict_rows(value: Any) -> list[dict]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _int_value(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
