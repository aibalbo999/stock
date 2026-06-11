from __future__ import annotations

from app.ui.analysis_operator_presenter import (
    operator_card_html,
    operator_decision_html,
    operator_source_text,
)


def test_operator_presenter_hides_route_ids_and_uses_captions() -> None:
    html = operator_decision_html(
        {
            "title": "閱讀最新版報告",
            "reason": "最新版報告可閱讀。",
            "risk": "仍需查核。",
            "impact": "直接進入報告中心。",
            "action_label": "讀報告",
            "route_hint": "report:15",
            "source_ids": ["report:15"],
            "state": "ready",
        },
        [
            {
                "title": "補強資料",
                "detail": "補抓公司文件",
                "state": "attention",
                "route_hint": "data_enrichment:company_filings_fetch:2330",
            }
        ],
    )

    assert "開啟報告中心並選取報告 #15" in html
    assert "開啟資料補強，準備補抓公司文件：2330" in html
    assert "report:15" not in html
    assert "data_enrichment:" not in html


def test_operator_presenter_labels_optimization_sources() -> None:
    source_text = operator_source_text(
        [
            "optimization:auto_local_defaults",
            "optimization:company_filing_structured_api_fallback",
            "services_status",
        ]
    )

    assert source_text == "本機 defaults 優化缺口、公司文件結構化 API 選配、系統狀態"
    assert "optimization:" not in source_text


def test_operator_card_html_escapes_values() -> None:
    html = operator_card_html(
        {
            "state": "attention",
            "title": "<品質>",
            "value": "需確認",
            "caption": "候選不足",
            "action_label": "查看",
        }
    )

    assert "&lt;品質&gt;" in html
    assert "<品質>" not in html
    assert "operator-status-card" in html
