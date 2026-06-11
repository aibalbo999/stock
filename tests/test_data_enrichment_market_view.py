from __future__ import annotations

from app.ui.data_enrichment_market_view import (
    data_gap_action_map_html,
    market_cache_operator_summary_html,
    market_operation_readiness_html,
    market_submission_summary_html,
    pending_market_handoff_html,
)


def test_market_view_renders_data_gap_action_map_without_raw_route_ids() -> None:
    html = data_gap_action_map_html(
        [
            {
                "purpose": "required",
                "action_label": "刷新股價",
                "ticker": "2330",
                "impact": "刷新股價可改善股價與量能。",
                "post_action_hint": "完成後重跑最新版報告。",
                "route_hint": "data_enrichment:market_refresh:2330",
            }
        ]
    )

    assert "資料缺口行動地圖" in html
    assert "刷新股價可改善股價與量能。" in html
    assert "data_enrichment:market_refresh" not in html


def test_market_view_renders_preflight_and_handoff_sections() -> None:
    readiness_html = market_operation_readiness_html(
        [
            {
                "state": "ready",
                "selected": "yes",
                "label": "刷新股價",
                "disabled_reason": "可送出背景任務",
                "caption": "已選 1 檔",
                "impact": "更新股價",
                "post_action_hint": "完成後重跑",
            }
        ]
    )
    submission_html = market_submission_summary_html(
        {
            "state": "attention",
            "title": "準備送出刷新股價",
            "detail": "請確認股票與日期。",
            "next_step": "勾選確認後送出。",
            "quota_hint": "會消耗外部資料額度。",
        }
    )
    handoff_html = pending_market_handoff_html(
        {
            "state": "ready",
            "title": "已帶入刷新股價",
            "detail": "已選 2330。",
            "next_step": "確認背景任務後按「刷新股價」。",
        }
    )

    assert "market-operation-readiness" in readiness_html
    assert "is-ready is-selected" in readiness_html
    assert "market-submission-summary is-attention" in submission_html
    assert "外部資料額度" in submission_html
    assert "market-handoff-banner is-ready" in handoff_html


def test_market_view_renders_cache_summary_cards() -> None:
    html = market_cache_operator_summary_html(
        [
            {
                "state": "attention",
                "title": "股價快取",
                "value": "3 檔",
                "caption": "有資料落後",
                "action_label": "刷新股價",
            }
        ]
    )

    assert "市場快取新鮮度" in html
    assert "股價快取" in html
    assert "刷新股價" in html
