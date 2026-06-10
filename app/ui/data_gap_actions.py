from __future__ import annotations

from typing import Any


ACTION_OPERATION_MAP = {
    "refresh_market": {
        "gap_type": "price",
        "action_label": "刷新股價",
        "operation": "market_refresh",
        "route_hint": "data_enrichment:market",
    },
    "refresh_financial_metrics": {
        "gap_type": "financials",
        "action_label": "刷新 5 年財報",
        "operation": "fundamentals_refresh",
        "route_hint": "data_enrichment:market",
    },
    "refresh_monthly_revenue": {
        "gap_type": "financials",
        "action_label": "刷新月營收",
        "operation": "fundamentals_refresh",
        "route_hint": "data_enrichment:market",
    },
    "refresh_valuations": {
        "gap_type": "valuation",
        "action_label": "刷新估值",
        "operation": "valuation_refresh",
        "route_hint": "data_enrichment:market",
    },
    "ingest_company_filings": {
        "gap_type": "filing",
        "action_label": "補抓公司文件",
        "operation": "company_filings_fetch",
        "route_hint": "data_enrichment:market",
    },
    "ingest_news": {
        "gap_type": "news",
        "action_label": "匯入新聞/研究摘要",
        "operation": "manual_ingest",
        "route_hint": "data_enrichment:manual",
    },
    "rerun_analysis": {
        "gap_type": "rag",
        "action_label": "補強後重跑報告",
        "operation": "report_follow_up",
        "route_hint": "report_center",
    },
}


def data_gap_action_items(
    report_result: dict | None,
    follow_up_plan: dict | None,
) -> list[dict[str, Any]]:
    report = _dict_value(report_result)
    plan = _dict_value(follow_up_plan)
    request = _dict_value(plan.get("request"))
    report_id = report.get("report_id") or report.get("id") or plan.get("report_id")
    topic = report.get("topic") or request.get("topic") or "最新版報告"
    items = []
    for row in _list_value(plan.get("next_actions")):
        action = _text(row.get("action"))
        metadata = ACTION_OPERATION_MAP.get(action)
        if not metadata:
            continue
        tickers = _tickers(row, request)
        route_hint = metadata["route_hint"]
        if action == "rerun_analysis" and report_id is not None:
            route_hint = f"report:{report_id}"
        items.append(
            {
                "report_id": report_id,
                "topic": topic,
                "ticker": "、".join(tickers) if tickers else "全部",
                "tickers": tickers,
                "gap_type": metadata["gap_type"],
                "action_label": metadata["action_label"],
                "operation": metadata["operation"],
                "impact": _impact(row, metadata["action_label"]),
                "post_action_hint": _post_action_hint(action),
                "route_hint": route_hint,
                "purpose": _text(row.get("purpose") or row.get("priority"), default="tracking"),
                "priority": _text(row.get("priority") or row.get("purpose"), default="tracking"),
            }
        )
    return _dedupe_items(items)


def data_gap_action_summary(items: list[dict]) -> dict[str, str]:
    if not items:
        return {
            "state": "ready",
            "label": "目前沒有必要資料缺口",
            "detail": "最新版報告沒有必補資料行動。",
        }
    required_count = sum(1 for item in items if item.get("purpose") == "required")
    tracking_count = len(items) - required_count
    return {
        "state": "attention" if required_count else "ready",
        "label": f"必補 {required_count} 項｜追蹤 {tracking_count} 項",
        "detail": "先處理必補資料，再重跑最新版報告。"
        if required_count
        else "目前只有追蹤型資料更新，可排在主要閱讀流程之後。",
    }


def _impact(row: dict, action_label: str) -> str:
    target = _text(row.get("target"))
    reason = _text(row.get("reason"))
    if target and reason:
        return f"{action_label}可改善「{target}」：{reason}"
    if target:
        return f"{action_label}可改善「{target}」。"
    return _text(row.get("next_step"), default=f"{action_label}可改善最新版報告資料缺口。")


def _post_action_hint(action: str) -> str:
    if action == "rerun_analysis":
        return "補強完成後重跑報告"
    return "補完後建議重跑報告"


def _tickers(row: dict, request: dict) -> list[str]:
    tickers = row.get("tickers")
    if not isinstance(tickers, list):
        tickers = request.get("tickers")
    if not isinstance(tickers, list):
        return []
    return [str(ticker).strip() for ticker in tickers if str(ticker).strip()]


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = []
    seen = set()
    for item in items:
        key = (item.get("operation"), tuple(item.get("tickers") or []), item.get("purpose"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _text(value: Any, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default
