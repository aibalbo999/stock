from __future__ import annotations

from typing import Any

from app.ui.data_enrichment_market_operations import (
    MARKET_OPERATION_METADATA,
    MARKET_OPERATION_ORDER,
    market_data_operation_button_type,
    market_operation_disabled_reason,
    normalized_market_tickers,
    task_queue_block_reason,
)


def pending_market_selection_state(
    pending_tickers: object,
    allowed_tickers: list[str],
) -> dict[str, Any]:
    requested = normalized_market_tickers(pending_tickers)
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


def pending_market_handoff_summary(
    *,
    selected_market_tickers: list[str],
    pending_operation: str | None,
    selection_state: dict | None = None,
) -> dict[str, str]:
    operation = str(pending_operation or "").strip()
    if operation not in MARKET_OPERATION_METADATA:
        return {}

    metadata = MARKET_OPERATION_METADATA[operation]
    action_label = metadata["label"]
    selected = normalized_market_tickers(selected_market_tickers)
    ticker_label = "、".join(selected) if selected else "尚未選擇股票"
    rejected_detail = ""
    if isinstance(selection_state, dict) and selection_state.get("rejected"):
        rejected_detail = str(selection_state.get("detail") or "").strip()
    next_prefix = "先處理白名單提醒，再" if rejected_detail else ""
    return {
        "state": "attention" if rejected_detail else "ready",
        "title": f"已帶入{action_label}",
        "detail": f"股票：{ticker_label}｜{metadata['impact']}",
        "next_step": f"{next_prefix}確認背景任務後按「{action_label}」。",
        "action_label": action_label,
        "rejected_detail": rejected_detail,
    }


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
    queue_block_reason = task_queue_block_reason(task_queue)

    rows = []
    for operation in MARKET_OPERATION_ORDER:
        metadata = MARKET_OPERATION_METADATA[operation]
        disabled_reason = market_operation_disabled_reason(
            operation,
            has_market_selection=has_market_selection,
            has_valid_market_range=has_valid_market_range,
            task_queue_block_reason=queue_block_reason,
        )
        state = "blocked" if queue_block_reason else "ready" if not disabled_reason else "attention"
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


def market_submission_preflight_summary(
    *,
    selected_market_tickers: list[str],
    market_start: Any,
    market_end: Any,
    pending_operation: str | None,
    task_queue: dict | None,
    confirmed: bool,
) -> dict[str, str]:
    selected = normalized_market_tickers(selected_market_tickers)
    operation = str(pending_operation or "").strip()
    metadata = MARKET_OPERATION_METADATA.get(operation)
    operation_label = metadata["label"] if metadata else "資料補強"
    action_step = (
        f"按「{operation_label}」送出背景任務"
        if metadata
        else "選擇下方一個刷新操作送出背景任務"
    )
    confirmation_step = (
        f"再按「{operation_label}」送出背景任務"
        if metadata
        else "選擇下方一個刷新操作送出背景任務"
    )
    date_label = f"{_date_text(market_start)} → {_date_text(market_end)}"
    detail = f"股票：{_ticker_label(selected)}｜期間：{date_label}"

    queue_block_reason = task_queue_block_reason(task_queue)
    if queue_block_reason:
        return {
            "state": "blocked",
            "title": "背景任務暫時不可送出",
            "detail": detail,
            "next_step": f"{queue_block_reason}。",
            "quota_hint": "尚未送出任何資料補強；先修復背景任務可避免失敗重試浪費額度。",
        }
    if not selected:
        return {
            "state": "attention",
            "title": "資料補強尚未完整",
            "detail": detail,
            "next_step": "請先選擇至少一檔股票，再送出資料補強背景任務。",
            "quota_hint": "尚未送出任何資料補強；確認股票可避免空任務浪費排隊資源。",
        }
    if operation in {"market_refresh", "valuation_refresh"} and market_start > market_end:
        return {
            "state": "attention",
            "title": f"準備送出{operation_label}",
            "detail": detail,
            "next_step": "起始日期不可晚於結束日期；修正後再送出背景任務。",
            "quota_hint": "尚未送出任何資料補強；先修正日期可避免失敗重試浪費額度。",
        }
    if not confirmed:
        return {
            "state": "attention",
            "title": f"準備送出{operation_label}",
            "detail": detail,
            "next_step": f"勾選確認後，{confirmation_step}。",
            "quota_hint": "會使用背景任務與外部資料額度；送出後請等待狀態輪詢，避免重複送出。",
        }
    return {
        "state": "ready",
        "title": f"可以送出{operation_label}",
        "detail": detail,
        "next_step": f"{action_step}；完成後回報告中心確認最新版。",
        "quota_hint": "送出後本頁會輪詢任務狀態；完成前不要重複送出同類補強。",
    }


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


def _ticker_label(tickers: list[str]) -> str:
    return "、".join(tickers) if tickers else "尚未選擇股票"


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
