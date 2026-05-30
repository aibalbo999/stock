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


def test_streamlit_app_defers_annotation_evaluation_for_python39() -> None:
    source = Path("streamlit_app.py").read_text()

    assert source.startswith("from __future__ import annotations")


def test_streamlit_shell_uses_operational_workspace_header() -> None:
    source = Path("streamlit_app.py").read_text()

    assert "workspace-topbar" in source
    assert "workflow-strip" in source
    assert "workspace-ledger" in source
    assert "credibility_html" in source
    assert "credibility-grid" in source
    assert '[data-baseweb="tab"] p' in source
    assert 'tabs = st.tabs(["1 建立分析", "2 報告中心", "3 資料與補充", "4 設定與維護"])' in source
    assert 'data_tabs = st.tabs(["市場快取與刷新", "手動補充", "RSS 匯入"])' in source
    assert 'settings_tabs = st.tabs(["股票範圍", "自動排程", "維護"])' in source
    assert '"匯入新聞/研究摘要"' in source
    assert '"匯入 RAG"' not in source
    assert "manual_news_ready = bool(title.strip() and text.strip())" in source
    assert "schedule_ready = (not schedule_enabled) or (bool(schedule_topic.strip()) and bool(schedule_tickers))" in source
    assert '"產業分類篩選"' in source
    assert 'st.columns([0.20, 0.80], gap="medium")' not in source
    assert "report_action_cols = st.columns([0.16, 0.16, 0.68], gap=\"small\")" in source
    assert ".report {{ max-width:1360px" in source
    assert ".report-grid {{ display:block" in source
    assert "grid-template-columns:minmax(240px,0.28fr)" not in source
    assert "上方選擇一份歷史報告後" in source
    assert 'flex-wrap: wrap' in source
    assert 'button[data-testid^="stBaseButton"]' in source
    assert '[data-testid="stSliderThumbValue"]' in source
    assert '[data-baseweb="tag"]' in source
    assert 'min-height: 40px !important' in source
    assert 'svg[role="button"]' in source
    assert '[data-testid="stWidgetLabel"]' in source
    assert '[data-testid="stDateInputField"]' in source
    assert '[data-testid="stNumberInputField"]' in source
    assert '[data-baseweb="input"]' in source
    assert 'border-color: #64748b' in source
    assert '[data-testid="stJson"] *' in source
    assert '[data-testid="stCode"] pre' in source
    assert "white-space: pre-wrap" in source
    assert 'button[data-testid^="stBaseButton"][disabled]' in source
    assert "input:focus" in source
    assert 'key="confirm_maintenance_cleanup"' in source
    assert "避免手機或滑鼠誤觸" in source
    assert "disabled=not cleanup_confirmed" in source
    assert "正式分析不等於買進" in source
    assert "letter-spacing: -" not in source
    assert "stock-hero" not in source
    assert "https://fonts.googleapis.com" not in source


def test_follow_up_controls_use_scoped_widget_keys() -> None:
    source = Path("streamlit_app.py").read_text()

    assert 'def render_follow_up_controls(report_id: int, markdown: str, scope: str = "report")' in source
    assert 'key_suffix = f"{scope}_{report_id}"' in source
    assert 'key=f"followup_purpose_{key_suffix}"' in source
    assert 'scope="analysis_result"' in source
    assert 'scope="history_report"' in source
    assert 'key=f"followup_purpose_{report_id}"' not in source


def test_report_html_renders_comparison_matrix_cards() -> None:
    helpers = load_report_helpers()
    markdown = """
# AI 產業鏈 自動分析報告

## 個股比較矩陣
| 股票 | 判斷 | 目前股價 | 當下股價標籤 | 目前情境升值分 | 目前情境降值分 | 目前估值位置 | 財務信心 | 核心提醒 |
|---|---|---|---|---:|---:|---|---|---|
| 3017 奇鋐 | 可小額分批研究 | 2026-05-22 收盤 100 | 可研究但勿追高 | 30 分 | 0 分 | 目前估值偏高 | 高 | 目前估值偏高，分批觀察 |
| 2382 廣達 | 觀察 / 等風險降低 | 2026-05-22 收盤 80 | 等風險下降 | 30 分 | 7 分 | 目前估值低於同業 | 高 | 先追蹤目前情境降值分 7 分 |

## 投資建議
| 股票 | 目前股價 | 當下股價標籤 | 建議 | 理由 | 單檔上限 | 來源 |
|---|---|---|---|---|---:|---|
| 3017 奇鋐 | 2026-05-22 收盤 100 | 可研究但勿追高 | 可小額分批研究 | 測試 | 約 100,000 元 | 測試 |
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in html
    assert html.count('class="matrix-card') == 2
    assert "可研究 1" in html
    assert "觀察 1" in html
    assert "decision-action" in html
    assert "decision-watch" in html
    assert "valuation-high" in html
    assert "risk-high" in html
    assert "當下股價標籤" in html
    assert "可研究但勿追高" in html
    assert "等風險下降" in html
    assert "price-watch" in html
    assert "price-risk" in html
    assert "目前情境升值分" in html
    assert "目前情境降值分" in html


def test_report_html_renders_credibility_panel() -> None:
    helpers = load_report_helpers()
    markdown = """
# AI 產業鏈 自動分析報告

## 一頁摘要
| 項目 | 結果 |
|---|---|
| 本次股票範圍 | 1 檔 |

## 可信度檢查
本段先檢查報告本身的可信度。

| 檢查項目 | 狀態 | 本次證據 | 對投資判斷的影響 |
|---|---|---|---|
| 可追溯來源 | 可追溯 | 共 12 筆文本 | 沒有來源時只保留主題觀察。 |
| 來源多樣性 | 多來源 | 5 個發布者 | 避免單一觀點誤導。 |

### 個股可信度核對
| 股票 | 可信度 | 公司文本 | 歸因證據 | 最近來源日期 | 主要限制 |
|---|---|---:|---:|---|---|
| 2330 台積電 | 高 | 3 筆 / 3 來源 | 2 筆 | 2026-05-21 | 未發現重大資料缺口 |

### 可信度判讀規則
- 高可信：資料大致齊備。
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert "可信度檢查" in html
    assert "credibility-card" in html
    assert "credibility-company" in html
    assert "可追溯來源" in html
    assert "2330 台積電" in html
    assert "可信度判讀規則" in html


def test_report_html_prioritizes_zero_allocation_and_all_investment_rows() -> None:
    helpers = load_report_helpers()
    markdown = """
# AI 產業鏈 自動分析報告

## 一頁摘要
| 項目 | 結果 |
|---|---|
| 本次股票範圍 | 8 檔 |
| 可小額研究 | 0 檔 |
| 觀察/待補 | 7 檔 |
| 避開/降低曝險 | 1 檔 |

## 投資建議
| 股票 | 建議 | 理由 | 單檔上限 | 來源 |
|---|---|---|---:|---|
| 1001 A | 觀察 | 測試 | 不適用 / 0 元 | 測試 |
| 1002 B | 觀察 | 測試 | 不適用 / 0 元 | 測試 |
| 1003 C | 觀察 | 測試 | 不適用 / 0 元 | 測試 |
| 1004 D | 觀察 | 測試 | 不適用 / 0 元 | 測試 |
| 1005 E | 觀察 | 測試 | 不適用 / 0 元 | 測試 |
| 1006 F | 觀察 | 測試 | 不適用 / 0 元 | 測試 |
| 2421 建準 | 避開 / 降低曝險 | 目前情境降值分仍高 | 不適用 / 0 元 | 測試 |
| 3037 欣興 | 觀察 | 測試 | 不適用 / 0 元 | 測試 |

## 資金控管建議
### 首筆配置草案
目前無可配置標的。
"""

    html = helpers["report_html"](
        markdown,
        {
            "report_id": 1,
            "quality_gate": {
                "status": "ready",
                "action_policy": {"label": "品質可用", "max_deployable_amount": 700000},
            },
        },
    )

    assert "本次配置" in html
    assert ">0 元<" in html
    assert "可小額研究：0 檔" in html
    assert "避開/降低曝險：1 檔" in html
    assert "2421 建準" in html
    assert "避開 / 降低曝險" in html


def test_report_html_renders_auto_follow_up_status_and_reader_rail() -> None:
    helpers = load_report_helpers()
    html = helpers["report_html"](
        "# AI 產業鏈 自動分析報告\n",
        {
            "report_id": 1,
            "quality_gate": {"status": "caution"},
            "auto_follow_up": {
                "status": "started",
                "summary": {
                    "selected": {"total_count": 2},
                    "execution": {"stored_count": 5},
                },
                "rerun_report": {"report_id": 8},
            },
        },
    )

    assert "已自動補強並產生新版報告" in html
    assert "報告 #8" in html
    assert "decision-rail" in html
    assert 'aria-label="閱讀提示"' in html
    assert "先看本次配置與可研究檔數" in html


def test_report_html_renders_auto_follow_up_unavailable_state() -> None:
    helpers = load_report_helpers()
    html = helpers["report_html"](
        "# AI 產業鏈 自動分析報告\n",
        {
            "report_id": 1,
            "quality_gate": {"status": "caution"},
            "auto_follow_up": {
                "status": "unavailable",
                "reason": "後端自動補強服務暫時無法連線。",
            },
        },
    )

    assert "自動補強暫時無法啟動" in html
    assert "後端自動補強服務暫時無法連線" in html


def test_report_html_accepts_legacy_auto_follow_up_bool_rerun_flag() -> None:
    helpers = load_report_helpers()
    html = helpers["report_html"](
        "# AI 產業鏈 自動分析報告\n",
        {
            "report_id": 1,
            "quality_gate": {"status": "caution"},
            "auto_follow_up": {
                "status": "running",
                "planned_actions": [{"action": "ingest_news"}],
                "rerun_report": True,
            },
        },
    )

    assert "自動補強執行中" in html
    assert "系統正在處理 1 項補強任務" in html


def test_report_html_renders_time_scope_panel_and_precise_metric_labels() -> None:
    helpers = load_report_helpers()
    markdown = """
# AI 產業鏈 自動分析報告

## 時間口徑說明
- 「目前」指本報告生成時間前已取得的資料，不代表未來一定維持。
- 「目前情境升值分／目前情境降值分」是排序分數，不是預期報酬率。
"""

    html = helpers["report_html"](
        markdown,
        {
            "report_id": 1,
            "request": {"lookback_days": 21},
            "quality_gate": {
                "metrics": {
                    "source_timestamp_coverage": 1,
                    "source_recent_coverage": 0.8,
                    "leading_signal_coverage": 0.5,
                }
            },
        },
    )

    assert "<h2>時間口徑</h2>" in html
    assert "近 21 天來源" in html
    assert "來源有日期" in html
    assert "近況訊號覆蓋" in html
    assert "不是預期報酬率" in html


def test_report_html_renders_investment_thesis_cards() -> None:
    helpers = load_report_helpers()
    markdown = """
# AI 產業鏈 自動分析報告

## 投資理由地圖
本段把每檔股票拆成「為什麼值得研究」與「為什麼可能不成立」。這是研究假設，不是報酬保證或買賣指令。

### 2330 台積電
- 目前判斷：可小額分批研究；資料等級：完整。
- 成長假設：有 3 筆公司相關文本，正向關鍵證據 2 項。
- 主要風險：風險證據未達 >5% 情境門檻。
- 具體投資理由：目前情境升值分 22 高於 10 的研究門檻。
- 需要再確認：下一期月營收、法說或官方文件是否延續目前假設
- 代表性來源：2026-05-20 測試新聞《台積電 AI 需求成長》
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert "投資理由地圖" in html
    assert 'class="thesis-card"' in html
    assert "值得研究的理由" in html
    assert "目前情境升值分 22" in html
    assert "不是未來報酬率、目標價或買賣指令" in html


def test_report_html_renders_early_potential_radar_cards() -> None:
    helpers = load_report_helpers()
    markdown = """
# AI 產業鏈早期潛力股 自動分析報告

## 早期潛力雷達
本段專門找「截至目前報導較少、但近況訊號轉強」的研究線索；報導較少不是利多。

| 股票 | 早期線索分 | 截至目前報導熱度 | 目前情境升值分 | 目前情境降值分 | 為什麼可能還早 | 代表來源 |
|---|---:|---|---:|---:|---|---|
| 2356 英業達 | 28 | 報導較少 | 28 分 | 9 分 | 公司文本 2 筆 / 2 來源；月營收年增 36.5% | 2026-05-06 測試新聞《英業達 AI 伺服器展望》 |
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert "早期潛力雷達" in html
    assert 'class="radar-card attention-low"' in html
    assert "截至目前報導較少、但近況訊號轉強" in html
    assert "不是買賣指令" in html
    assert "不是自選股狀態" in html
    assert "英業達" in html


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
                "metrics": {
                    "formal_confidence_min": 76,
                    "formal_confidence_avg": 82.5,
                    "discovery_plan_status": "ready",
                    "discovery_plan_score": 100,
                },
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
    assert "quality-warnings" in html
    assert "最低信心" in html
    assert ">高 76<" in html
    assert "拆解任務品質" in html
    assert ">完整（100 分）<" in html


def test_report_html_renders_observations_without_warning_title() -> None:
    helpers = load_report_helpers()
    markdown = "# AI 產業鏈 自動分析報告\n"

    html = helpers["report_html"](
        markdown,
        {
            "report_id": 1,
            "quality_gate": {
                "status": "ready",
                "warnings": [],
                "blockers": [],
                "observations": ["LLM 補充分析已完成，且仍受來源與白名單驗證約束"],
            },
        },
    )

    assert "品質觀察" in html
    assert "品質警示" not in html
    assert "quality-observations" in html
    assert "panel quality-issues quality-warnings" not in html
    assert "觀察：" in html
    assert "模型補充分析已完成" in html


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
    assert "quality-blockers" in html


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


def test_report_html_uses_quality_promoted_count_when_report_payload_has_no_promoted_list() -> None:
    helpers = load_report_helpers()

    html = helpers["report_html"](
        "# AI 產業鏈早期潛力股 自動分析報告",
        {
            "report_id": 1,
            "quality_gate": {
                "status": "ready",
                "metrics": {"promoted_count": 10},
            },
            "candidate_whitelist": [],
        },
    )

    assert "正式分析股票</span><strong>10</strong>" in html
    assert "正式分析只代表資料通過門檻，不等於買進名單" in html


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


def test_follow_up_blocker_action_rows_use_next_actions() -> None:
    helpers = load_report_helpers()

    rows = helpers["follow_up_blocker_action_rows"](
        {
            "results": {
                "ingest_company_filings:2382": {
                    "next_actions": [
                        {
                            "ticker": "2382",
                            "company_name": "廣達",
                            "action": "manual_company_filing_import",
                            "missing_required_types": ["annual_report"],
                            "missing_recommended_types": ["investor_presentation"],
                            "reason": "請補官方文件：annual_report",
                        }
                    ]
                }
            },
            "rerun_report": {"status": "skipped", "blockers": ["公司公開文件仍不足：2382"]},
        }
    )

    assert rows == [
        {
            "股票": "2382",
            "公司": "廣達",
            "下一步": "人工匯入官方文件",
            "缺必要文件": "annual_report",
            "缺建議文件": "investor_presentation",
            "目前": "-",
            "要求": "-",
            "原因": "請補官方文件：annual_report",
        }
    ]


def test_follow_up_blocker_action_rows_prefer_rerun_next_actions() -> None:
    helpers = load_report_helpers()

    rows = helpers["follow_up_blocker_action_rows"](
        {
            "results": {
                "ingest_company_filings:9999": {
                    "next_actions": [
                        {
                            "ticker": "9999",
                            "action": "manual_company_filing_import",
                            "reason": "舊結果",
                        }
                    ]
                }
            },
            "rerun_report": {
                "status": "skipped",
                "next_actions": [
                    {
                        "ticker": "2382",
                        "company_name": "廣達",
                        "action": "manual_company_filing_import",
                        "missing_required_types": ["annual_report"],
                        "reason": "請補官方文件：annual_report",
                    }
                ],
            },
        }
    )

    assert rows[0]["股票"] == "2382"
    assert rows[0]["原因"] == "請補官方文件：annual_report"


def test_follow_up_blocker_action_rows_show_completion_gap() -> None:
    helpers = load_report_helpers()

    rows = helpers["follow_up_blocker_action_rows"](
        {
            "rerun_report": {
                "status": "skipped",
                "next_actions": [
                    {
                        "ticker": "2330",
                        "action": "complete_follow_up_check",
                        "observed": {"stored_count": 90, "error_count": 1},
                        "required": {"min_days": 120, "error_count": 0},
                        "reason": "refresh_market:2330 未達完成條件",
                    }
                ],
            }
        }
    )

    assert rows[0]["下一步"] == "補齊未達標資料"
    assert rows[0]["目前"] == "已取得 90；錯誤 1"
    assert rows[0]["要求"] == "至少天數 120；錯誤 0"


def test_follow_up_check_value_text_formats_lists_and_booleans() -> None:
    helpers = load_report_helpers()

    text = helpers["follow_up_check_value_text"](
        {"blocked_tickers": ["2382", "3324"], "manual_review": True}
    )

    assert text == "仍缺公司 2382、3324；需人工覆核 是"


def test_follow_up_blocker_action_rows_fall_back_to_blockers() -> None:
    helpers = load_report_helpers()

    rows = helpers["follow_up_blocker_action_rows"](
        {"rerun_report": {"status": "skipped", "blockers": ["公司公開文件仍不足：2382"]}}
    )

    assert rows[0]["下一步"] == "補齊資料後再重跑"
    assert rows[0]["原因"] == "公司公開文件仍不足：2382"
