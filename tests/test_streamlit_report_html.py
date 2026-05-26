from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Optional

import re

from app.services.candidate_confidence import format_confidence_score


def load_report_helpers() -> dict:
    source = Path("streamlit_app.py").read_text()
    start = source.index("def markdown_section(")
    end = source.index("def render_reader_report(")
    namespace = {
        "escape": escape,
        "Optional": Optional,
        "re": re,
        "format_confidence_score": format_confidence_score,
    }
    exec(source[start:end], namespace)
    return namespace


def test_report_html_renders_comparison_matrix_cards() -> None:
    helpers = load_report_helpers()
    markdown = """
# AI 產業鏈 自動分析報告

## 個股比較矩陣
| 股票 | 判斷 | 升值 | 降值 | 估值位置 | 財務信心 | 核心提醒 |
|---|---|---:|---:|---|---|---|
| 3017 奇鋐 | 可小額分批研究 | 30% | 0% | 估值偏高 | 高 | 估值偏高，分批觀察 |
| 2382 廣達 | 觀察 / 等風險降低 | 30% | 7% | 估值低於同業 | 高 | 先追蹤降值風險 7% |

## 投資建議
| 股票 | 建議 | 理由 | 單檔上限 | 來源 |
|---|---|---|---:|---|
| 3017 奇鋐 | 可小額分批研究 | 測試 | 約 100,000 元 | 測試 |
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert html.count('class="matrix-card') == 2
    assert "可研究 1" in html
    assert "觀察 1" in html
    assert "decision-action" in html
    assert "decision-watch" in html
    assert "valuation-high" in html
    assert "risk-high" in html


def test_report_html_renders_quality_warnings() -> None:
    helpers = load_report_helpers()
    markdown = "# AI 產業鏈 自動分析報告\n"

    html = helpers["report_html"](
        markdown,
        {
            "report_id": 1,
            "quality_gate": {
                "status": "caution",
                "warnings": ["候選公司證據覆蓋率低於 60%，已由二次篩選收斂正式股票"],
                "blockers": [],
                "metrics": {"formal_confidence_min": 76, "formal_confidence_avg": 82.5},
                "remediation_actions": ["對弱證據候選補抓公司新聞、法說會與供應鏈資料後再做二次篩選。"],
                "action_policy": {"label": "需人工覆核"},
            },
        },
    )

    assert "品質警示" in html
    assert "警示：" in html
    assert "候選公司證據覆蓋率低於 60%" in html
    assert "建議補強" in html
    assert "弱證據候選補抓" in html
    assert "quality-issues" in html
    assert "最低信心" in html
    assert ">高 76<" in html


def test_report_html_labels_low_candidate_confidence() -> None:
    helpers = load_report_helpers()

    html = helpers["report_html"](
        "# AI 產業鏈 自動分析報告\n",
        {
            "report_id": 1,
            "quality_gate": {
                "status": "insufficient",
                "metrics": {"formal_confidence_min": 42},
                "blockers": ["正式分析股票含低信心證據公司"],
                "action_policy": {"label": "僅供研究，不允許投入資金"},
            },
        },
    )

    assert "最低信心" in html
    assert ">低 42<" in html


def test_maintenance_service_metrics_show_promotion_threshold() -> None:
    helpers = load_report_helpers()

    metrics = helpers["maintenance_service_metrics"](
        {"integrity": {"ok": True}},
        {
            "redis": {"ok": True},
            "gemini": {"key_count": 5},
            "finmind": {"mode": "public_or_limited"},
            "candidate_confidence": {"high_threshold": 75},
        },
    )

    assert metrics["資料庫"] == "正常"
    assert metrics["Redis"] == "正常"
    assert metrics["AI Key"] == 5
    assert metrics["市場資料"] == "可用"
    assert metrics["升格門檻"] == "高 75"


def test_report_html_renders_follow_up_tasks() -> None:
    helpers = load_report_helpers()
    markdown = """
# AI 產業鏈 自動分析報告

## 自動補強任務
| 任務 | 股票 | 優先級 | 頻率 | 觸發原因 |
|---|---|---|---|---|
| 刷新股價/量能 | 2330 | high | weekly | 領先訊號偏空，需重新檢查 |
| 刷新月營收 | 2382 | high | monthly | 補齊月營收與公司文本 |
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert "系統會自動補強" in html
    assert "刷新股價/量能" in html
    assert "刷新月營收" in html
    assert "task-card" in html


def test_report_html_renders_candidate_audit_from_markdown() -> None:
    helpers = load_report_helpers()
    markdown = """
# AI 產業鏈 自動分析報告

## 候選公司審計
| 項目 | 數量 |
|---|---:|
| AI 初始候選 | 3 |
| 正式分析 | 1 |

| 股票 | 產業位置 | 狀態 | 證據 | 排除 / 升格原因 | 下一步 |
|---|---|---|---:|---|---|
| 2382 廣達 | 系統組裝 | 正式分析 | 2 篇 / 2 來源 | 通過正式分析門檻 | 納入正式分析 |
| 3324 雙鴻 | 散熱模組 | 弱證據觀察 | 1 篇 / 1 來源 | 弱證據：來源不足 | 補抓公司新聞 |
| 2308 台達電 | 電源與散熱 | 待補證據 | 0 篇 / 0 來源 | 缺少公司主題證據 | 重新補抓 |
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert "候選公司審計" in html
    assert "正式分析 1" in html
    assert "弱證據 1" in html
    assert "待補證據 1" in html
    assert "3324 雙鴻" in html
    assert "audit-card audit-weak" in html


def test_report_html_renders_candidate_audit_from_result_payload() -> None:
    helpers = load_report_helpers()

    html = helpers["report_html"](
        "# AI 產業鏈 自動分析報告",
        {
            "report_id": 1,
            "quality_gate": {},
            "candidate_whitelist": [
                {
                    "ticker": "2382",
                    "name": "廣達",
                    "segment": "系統組裝",
                    "status": "evidence_supported",
                    "evidence_count": 2,
                    "evidence_source_count": 2,
                    "validation_reason": "通過正式分析門檻",
                    "next_action": "納入正式分析",
                    "evidence_sources": [
                        {
                            "title": "廣達 AI 伺服器訂單",
                            "publisher": "測試新聞",
                            "published_at": "2026-05-24",
                        }
                    ],
                    "evidence_confidence_score": 92,
                    "evidence_confidence_label": "高",
                },
                {
                    "ticker": "3324",
                    "name": "雙鴻",
                    "segment": "散熱模組",
                    "status": "weak_evidence",
                    "evidence_count": 1,
                    "evidence_source_count": 1,
                    "validation_reason": "弱證據：來源不足",
                    "next_action": "補抓公司新聞",
                },
            ],
        },
    )

    assert "候選公司審計" in html
    assert "候選清單</span><strong>2</strong>" in html
    assert "2382 廣達" in html
    assert "3324 雙鴻" in html
    assert "廣達 AI 伺服器訂單" in html
    assert "測試新聞" in html
    assert "高 92" in html


def test_candidate_revalidation_summary_counts_statuses() -> None:
    helpers = load_report_helpers()

    summary = helpers["candidate_revalidation_summary"](
        {
            "rerun_report": {
                "candidate_revalidation": {
                    "changed": True,
                    "promoted_tickers": ["2382", "3324"],
                    "document_query_count": 9,
                    "document_count": 24,
                    "newly_promoted": ["3324"],
                    "no_longer_promoted": [],
                    "status_changes": [
                        {
                            "ticker": "3324",
                            "previous_status": "weak_evidence",
                            "current_status": "evidence_supported",
                        }
                    ],
                    "candidate_whitelist": [
                        {
                            "ticker": "2382",
                            "name": "廣達",
                            "segment": "系統組裝",
                            "status": "evidence_supported",
                            "evidence_count": 2,
                            "evidence_source_count": 2,
                        },
                        {
                            "ticker": "3324",
                            "name": "雙鴻",
                            "segment": "散熱模組",
                            "status": "evidence_supported",
                            "evidence_count": 3,
                            "evidence_source_count": 2,
                        },
                        {
                            "ticker": "2308",
                            "name": "台達電",
                            "segment": "電源與散熱",
                            "status": "needs_evidence",
                            "evidence_count": 0,
                            "evidence_source_count": 0,
                        },
                    ],
                }
            }
        }
    )

    assert summary["changed"] is True
    assert summary["total"] == 3
    assert summary["promoted_count"] == 2
    assert summary["weak_count"] == 0
    assert summary["needs_evidence_count"] == 1
    assert summary["document_query_count"] == 9
    assert summary["document_count"] == 24
    assert summary["newly_promoted"] == ["3324"]
    assert summary["status_changes"][0]["previous_status"] == "weak_evidence"
    assert summary["rows"][1]["股票"] == "3324 雙鴻"


def test_follow_up_result_message_explains_skipped_rerun() -> None:
    helpers = load_report_helpers()

    level, message = helpers["follow_up_result_message"](
        {
            "rerun_report": {
                "status": "skipped",
                "reason": "補資料後仍有關鍵缺口，先不重新產生報告。",
                "blockers": ["公司公開文件仍不足：2382"],
            }
        },
        "執行 2 項任務，補入/更新 0 筆資料，錯誤 0 項",
    )

    assert level == "warning"
    assert "先不重新產生報告" in message
    assert "公司公開文件仍不足：2382" in message


def test_follow_up_result_message_reports_new_report() -> None:
    helpers = load_report_helpers()

    level, message = helpers["follow_up_result_message"](
        {"rerun_report": {"report_id": 9}},
        "執行 2 項任務",
    )

    assert level == "success"
    assert "新報告 #9" in message
