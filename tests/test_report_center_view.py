from __future__ import annotations

from pathlib import Path

from app.ui.report_center_view import (
    empty_report_action_html,
    empty_report_result_html,
    latest_report_picker_html,
    report_health_strip_html,
    report_lifecycle_stage_html,
    report_lifecycle_strip_html,
    report_reader_decision_html,
)


def test_report_center_view_is_streamlit_free() -> None:
    source = Path("app/ui/report_center_view.py").read_text()

    assert "import streamlit" not in source
    assert "st." not in source


def test_latest_report_picker_html_escapes_latest_only_scope_note() -> None:
    html = latest_report_picker_html(
        {
            "mode": "multi_topic_latest",
            "summary_title": "每個主題的<最新版>",
            "summary_detail": "共 2 份 & 預設最新",
            "scope_note": '這不是"歷史版本清單"',
        }
    )

    assert 'class="latest-report-picker is-multi_topic_latest"' in html
    assert "每個主題的&lt;最新版&gt;" in html
    assert "共 2 份 &amp; 預設最新" in html
    assert "這不是&quot;歷史版本清單&quot;" in html
    assert "latest-report-picker-note" in html


def test_empty_report_result_and_action_html_render_operator_next_step() -> None:
    result_html = empty_report_result_html(
        {
            "summary_title": "尚無<最新版>",
            "summary_detail": "建立分析後 & 回來閱讀。",
        }
    )
    action_html = empty_report_action_html(
        {
            "state": "empty",
            "eyebrow": "建議操作",
            "title": "建立第一份最新版報告",
            "caption": "前往分析工作區建立報告；完成後回到這裡閱讀最新版。",
        }
    )

    assert "result-shell" in result_html
    assert "尚無&lt;最新版&gt;" in result_html
    assert "建立分析後 &amp; 回來閱讀。" in result_html
    assert 'class="report-lifecycle-action is-empty"' in action_html
    assert "建立第一份最新版報告" in action_html


def test_report_lifecycle_strip_html_renders_stage_cards_and_primary_detail() -> None:
    html = report_lifecycle_strip_html(
        {
            "overall_state": "attention",
            "trust_label": "可閱讀但需註記",
            "trust_explanation": "仍有 <1> 項必補缺口。",
            "primary_action": "刷新股價",
            "primary_action_detail": "刷新股價可改善「股價與量能」：缺少最新股價",
            "stage_cards": [
                {
                    "state": "attention",
                    "title": "資料",
                    "label": "缺口 1 項",
                    "detail": "先補資料再重跑。",
                }
            ],
        }
    )

    assert 'class="report-lifecycle-strip is-attention"' in html
    assert "仍有 &lt;1&gt; 項必補缺口。" in html
    assert "刷新股價可改善「股價與量能」：缺少最新股價" in html
    assert "report-lifecycle-step" in html
    assert "缺口 1 項" in html


def test_report_lifecycle_stage_html_escapes_stage_fields() -> None:
    html = report_lifecycle_stage_html(
        {
            "state": "blocked",
            "title": "品質<Gate>",
            "label": "正式分析 0 檔",
            "detail": "不要直接採信 & 先補強。",
        }
    )

    assert 'class="report-lifecycle-step is-blocked"' in html
    assert "品質&lt;Gate&gt;" in html
    assert "不要直接採信 &amp; 先補強。" in html


def test_report_reader_decision_html_renders_operator_decision_grid() -> None:
    html = report_reader_decision_html(
        {
            "state": "blocked",
            "eyebrow": "閱讀決策",
            "title": "暫停採信，先處理阻塞",
            "caption": "散熱產業鏈報告目前正式分析 0 檔。",
            "evidence": "#15｜散熱產業鏈｜2026-06-10 15:30",
            "quality": "品質 insufficient｜候選 2｜正式 0",
            "follow_up": "補強受阻",
            "action_label": "查看阻塞",
            "action_detail": "完成建議操作後再回來閱讀最新版。",
        }
    )

    assert 'class="report-reader-decision is-blocked"' in html
    assert "report-reader-decision-grid" in html
    assert "暫停採信，先處理阻塞" in html
    assert "品質 insufficient｜候選 2｜正式 0" in html


def test_report_health_strip_html_renders_latest_report_health_cards() -> None:
    html = report_health_strip_html(
        {
            "state": "ready",
            "report_label": "#15｜AI 產業鏈",
            "report_meta_label": "2026-06-10 15:30",
            "quality_label": "品質可讀",
            "candidate_label": "候選 2｜正式 2",
            "follow_up_label": "無必補缺口",
            "follow_up_state": "ready",
            "action_label": "閱讀最新版",
        }
    )

    assert 'class="report-health-strip is-ready"' in html
    assert "report-health-card" in html
    assert "#15｜AI 產業鏈" in html
    assert "閱讀最新版" in html
