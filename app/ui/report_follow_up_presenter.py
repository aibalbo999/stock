from __future__ import annotations

from html import escape
from typing import Any

from app.services.followup_models import FOLLOW_UP_ACTION_LABELS

PURPOSE_LABELS = {
    "all": "全部任務",
    "required": "只補資料缺口",
    "tracking": "只做追蹤更新",
}

FOLLOW_UP_PRIORITY_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
}

FOLLOW_UP_FREQUENCY_LABELS = {
    "once": "一次",
    "daily": "每日",
    "weekly": "每週",
    "monthly": "每月",
}

FOLLOW_UP_TARGET_LABELS = {
    "formal_filings": "正式文件",
    "market_data": "股價/量能",
    "monthly_revenue": "月營收",
    "financial_metrics": "五年財務",
    "valuation": "估值",
    "news": "新聞與產業資料",
    "candidate_evidence": "候選證據",
}

FOLLOW_UP_REASON_LABELS = {
    "candidate_evidence_gap": "候選證據缺口",
    "formal_filing_gap": "正式文件缺口",
    "market_freshness_gap": "股價/量能過期",
    "tracking_refresh": "追蹤更新",
}


def follow_up_submission_summary_html(summary: dict[str, str]) -> str:
    return f"""<section class="follow-up-submission-summary is-{escape(summary.get("state", "attention"))}" aria-label="自動補強送出前摘要">
<span>送出前摘要</span>
<strong>{escape(summary.get("title", ""))}</strong>
<p>{escape(summary.get("detail", ""))}</p>
<em>{escape(summary.get("next_step", ""))}</em>
<small>{escape(summary.get("quota_hint", ""))}</small>
</section>"""


def planned_follow_up_rows(actions: list[dict]) -> list[dict[str, str]]:
    return [
        {
            "任務": follow_up_task_label(action),
            "股票": "、".join(action.get("tickers") or []) or "全主題",
            "性質": "資料缺口補強" if action.get("purpose") == "required" else "追蹤更新",
            "優先級": labeled_value(action.get("priority"), FOLLOW_UP_PRIORITY_LABELS),
            "頻率": labeled_value(action.get("frequency"), FOLLOW_UP_FREQUENCY_LABELS),
            "觸發原因": labeled_value(action.get("reason"), FOLLOW_UP_REASON_LABELS),
        }
        for action in actions
    ]


def plan_next_action_rows(actions: list[dict]) -> list[dict[str, str]]:
    return [
        {
            "股票": "、".join(action.get("tickers") or []) or "全主題",
            "下一步": str(action.get("next_step") or ""),
            "補強目標": labeled_value(action.get("target"), FOLLOW_UP_TARGET_LABELS),
            "完成條件": str(action.get("completion_criteria") or "-"),
            "優先級": labeled_value(action.get("priority"), FOLLOW_UP_PRIORITY_LABELS),
            "原因": labeled_value(action.get("reason"), FOLLOW_UP_REASON_LABELS),
        }
        for action in actions
    ]


def markdown_follow_up_rows(rows: list) -> list[dict[str, str]]:
    return [
        {
            "任務": row[0] if len(row) > 0 else "-",
            "股票": row[1] if len(row) > 1 else "-",
            "性質": row[2] if len(row) > 5 else "追蹤更新",
            "優先級": row[3] if len(row) > 5 else row[2] if len(row) > 2 else "-",
            "頻率": row[4] if len(row) > 5 else row[3] if len(row) > 3 else "-",
            "觸發原因": row[5] if len(row) > 5 else row[4] if len(row) > 4 else "-",
        }
        for row in rows
    ]


def skipped_follow_up_rows(actions: list[dict]) -> list[dict[str, str]]:
    return [
        {
            "任務": follow_up_task_label(action),
            "股票": "、".join(action.get("tickers") or []) or "全主題",
            "最新日期": _latest_dates_text(action),
            "新鮮門檻": _freshness_threshold_text(action),
            "原因": "資料仍在新鮮範圍內",
        }
        for action in actions
    ]


def follow_up_task_label(action: dict[str, Any]) -> str:
    action_type = _text(action.get("action_type") or action.get("action"))
    label = _text(action.get("label"))
    if label and label != action_type:
        return label
    return FOLLOW_UP_ACTION_LABELS.get(action_type, action_type or "-")


def labeled_value(value: Any, labels: dict[str, str]) -> str:
    text = _text(value)
    return labels.get(text, text or "-")


def _latest_dates_text(action: dict) -> str:
    latest_dates = (action.get("freshness") or {}).get("latest_dates") or {}
    return (
        "、".join(f"{ticker}:{date_value}" for ticker, date_value in latest_dates.items())
        or "-"
    )


def _freshness_threshold_text(action: dict) -> str:
    max_age_days = (action.get("freshness") or {}).get("max_age_days")
    return f"{max_age_days} 天" if max_age_days is not None else "-"


def _text(value: Any) -> str:
    return str(value or "").strip()
