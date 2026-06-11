from __future__ import annotations

from pathlib import Path

from app.ui.data_enrichment_common_view import (
    allowlist_scope_summary_html,
    data_ingest_submission_summary_html,
    data_task_followup_summary_html,
)


def test_data_enrichment_common_view_is_streamlit_free() -> None:
    source = Path("app/ui/data_enrichment_common_view.py").read_text()

    assert "import streamlit" not in source
    assert "st." not in source


def test_allowlist_scope_summary_html_explains_static_scope_and_escapes() -> None:
    html = allowlist_scope_summary_html(
        {
            "state": "attention",
            "title": "目前使用靜態白名單",
            "detail": "可補強 2 檔｜來源：data/<scope>.json",
            "next_step": "若股票被白名單擋下，先到系統設定的股票範圍確認。",
        }
    )

    assert 'class="allowlist-scope-summary is-attention"' in html
    assert "資料補強白名單來源摘要" in html
    assert "目前使用靜態白名單" in html
    assert "data/&lt;scope&gt;.json" in html
    assert "系統設定的股票範圍" in html


def test_data_task_followup_summary_html_renders_followup_next_step() -> None:
    html = data_task_followup_summary_html(
        {
            "state": "ready",
            "title": "資料補強完成",
            "detail": "資料任務已完成；回報告中心確認最新版生命週期是否仍需重跑。",
            "next_step": "開啟報告中心確認資料、品質、補強、重跑與可讀狀態。",
        }
    )

    assert 'class="data-task-followup-summary is-ready"' in html
    assert "後續處理" in html
    assert "資料補強完成" in html
    assert "回報告中心確認最新版生命週期" in html


def test_data_ingest_submission_summary_html_renders_quota_context() -> None:
    html = data_ingest_submission_summary_html(
        {
            "state": "attention",
            "title": "準備送出手動資料",
            "detail": "會直接寫入資料庫。",
            "next_step": "確認內容後送出。",
            "quota_hint": "不會消耗 AI 額度。",
        }
    )

    assert 'class="data-ingest-submission-summary is-attention"' in html
    assert "資料送出前摘要" in html
    assert "準備送出手動資料" in html
    assert "不會消耗 AI 額度。" in html
