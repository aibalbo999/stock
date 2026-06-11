from __future__ import annotations

from app.ui.report_follow_up_presenter import (
    follow_up_submission_summary_html,
    markdown_follow_up_rows,
    plan_next_action_rows,
    planned_follow_up_rows,
    skipped_follow_up_rows,
)


def test_report_follow_up_presenter_labels_planned_actions_for_operators() -> None:
    rows = planned_follow_up_rows(
        [
            {
                "action_type": "fetch_filings",
                "label": "補抓公司文件",
                "tickers": ["2330", "2317"],
                "purpose": "required",
                "priority": "high",
                "frequency": "once",
                "reason": "formal_filing_gap",
            }
        ]
    )
    next_rows = plan_next_action_rows(
        [
            {
                "tickers": ["2330"],
                "next_step": "補抓法說會",
                "target": "formal_filings",
                "completion_criteria": "至少 1 份正式文件",
                "priority": "high",
                "reason": "formal_filing_gap",
            }
        ]
    )

    assert rows == [
        {
            "任務": "補抓公司文件",
            "股票": "2330、2317",
            "性質": "資料缺口補強",
            "優先級": "高",
            "頻率": "一次",
            "觸發原因": "正式文件缺口",
        }
    ]
    assert next_rows[0]["補強目標"] == "正式文件"
    assert next_rows[0]["原因"] == "正式文件缺口"


def test_report_follow_up_presenter_renders_legacy_and_skipped_rows() -> None:
    assert markdown_follow_up_rows([["任務 A", "2330", "high", "once", "news"]]) == [
        {
            "任務": "任務 A",
            "股票": "2330",
            "性質": "追蹤更新",
            "優先級": "high",
            "頻率": "once",
            "觸發原因": "news",
        }
    ]
    assert skipped_follow_up_rows(
        [
            {
                "label": "刷新股價",
                "tickers": ["2330"],
                "freshness": {"latest_dates": {"2330": "2026-06-12"}, "max_age_days": 3},
            }
        ]
    ) == [
        {
            "任務": "刷新股價",
            "股票": "2330",
            "最新日期": "2330:2026-06-12",
            "新鮮門檻": "3 天",
            "原因": "資料仍在新鮮範圍內",
        }
    ]


def test_report_follow_up_presenter_escapes_submission_summary_html() -> None:
    html = follow_up_submission_summary_html(
        {
            "state": 'ready" onclick="bad',
            "title": "<b>可以送出</b>",
            "detail": "範圍 > 全部",
            "next_step": "按下送出",
            "quota_hint": "可能消耗 <AI> 額度",
        }
    )

    assert "follow-up-submission-summary" in html
    assert "<b>" not in html
    assert "&lt;b&gt;可以送出&lt;/b&gt;" in html
    assert "範圍 &gt; 全部" in html
    assert "可能消耗 &lt;AI&gt; 額度" in html
