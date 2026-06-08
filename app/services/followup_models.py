from __future__ import annotations

from dataclasses import dataclass

from app.models.schemas import ReportRequest


ActionType = str
FOLLOW_UP_ACTION_LABELS = {
    "ingest_news": "補抓資料源",
    "ingest_company_filings": "補抓公司公開文件",
    "refresh_market": "刷新股價/量能",
    "refresh_monthly_revenue": "刷新月營收",
    "refresh_financial_metrics": "刷新五年財務",
    "refresh_valuations": "刷新估值",
    "rerun_discovery": "重跑主題拆解",
    "rerun_analysis": "重跑分析報告",
}


@dataclass(frozen=True)
class FollowUpAction:
    action_type: ActionType
    reason: str
    tickers: tuple[str, ...] = ()
    priority: str = "medium"
    frequency: str = "once"
    purpose: str = "required"

    def key(self) -> tuple[str, tuple[str, ...]]:
        return self.action_type, self.tickers

    def to_dict(self) -> dict:
        return {
            "action_type": self.action_type,
            "label": FOLLOW_UP_ACTION_LABELS.get(self.action_type, self.action_type),
            "reason": self.reason,
            "tickers": list(self.tickers),
            "priority": self.priority,
            "frequency": self.frequency,
            "purpose": self.purpose,
        }


def manual_tracking_follow_up_actions(request: ReportRequest) -> list[FollowUpAction]:
    tickers = tuple(request.tickers)
    return [
        FollowUpAction(
            "ingest_news",
            "使用者手動要求補抓資料，刷新主題與公司層級證據。",
            tickers,
            "medium",
            "once",
            "tracking",
        ),
        FollowUpAction(
            "rerun_analysis",
            "手動補抓資料後重跑分析，確認投資結論是否需要調整。",
            tickers,
            "high",
            "once",
            "tracking",
        ),
    ]
