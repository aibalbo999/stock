from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Optional

import re


def load_report_helpers() -> dict:
    source = Path("streamlit_app.py").read_text()
    start = source.index("def markdown_section(")
    end = source.index("def render_reader_report(")
    namespace = {
        "escape": escape,
        "Optional": Optional,
        "re": re,
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
                "action_policy": {"label": "需人工覆核"},
            },
        },
    )

    assert "品質警示" in html
    assert "警示：" in html
    assert "候選公司證據覆蓋率低於 60%" in html
    assert "quality-issues" in html
