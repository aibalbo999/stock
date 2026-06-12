# 報告資訊密度閱讀預算 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 HTML 報告的高資料量區塊預設只顯示高價值摘要，完整資料留在同區塊 `<details>` 展開區。

**Architecture:** 保持既有 Markdown 與資料產生流程不變，只在 UI renderer 層加入「閱讀預算」包裝。`report_html.py` 提供共用 wrapper 與排序 helper，`report_sections.py` 與 `report_candidate_audit.py` 回傳可分割的卡片清單，CSS 統一呈現摘要、剩餘數量與展開區。

**Tech Stack:** Python 3.11、Streamlit HTML iframe、pytest、原生 HTML `<details>` / `<summary>`、既有 `app/ui/styles/report_html.css`。

---

## File Structure

- Modify: `app/ui/report_html.py`
  - 新增 `READING_BUDGET_PREVIEW_LIMIT = 3`。
  - 新增 `reading_budget_section_html(...)`，統一組合摘要 HTML、剩餘提示與完整展開區。
  - 新增個股矩陣與投資建議排序 helper。
  - 改 `report_html(...)` 中長區塊渲染呼叫。
- Modify: `app/ui/report_sections.py`
  - 新增 `comparison_matrix_cards(...)`、`early_potential_radar_cards(...)`、`investment_thesis_cards(...)`、`follow_up_task_cards(...)`。
  - 保留現有 `comparison_matrix_html(...)`、`early_potential_radar_html(...)`、`investment_thesis_html(...)`、`follow_up_tasks_html(...)` 作為 join wrapper，降低相容風險。
  - 改 `next_steps_html(...)` 讓每個長群組使用閱讀預算。
- Modify: `app/ui/report_candidate_audit.py`
  - 新增 `candidate_audit_summary_and_cards(...)` 與 `candidate_audit_priority_key(...)`。
  - 保留 `candidate_audit_html(...)` 作為 summary + cards wrapper。
- Modify: `app/ui/styles/report_html.css`
  - 新增 `.reading-budget-*` 樣式。
  - 確保手機斷點下展開提示不擠壓文字。
- Modify: `tests/test_streamlit_report_html.py`
  - 新增閱讀預算行為測試。
  - 更新現有完整列數測試，改為檢查摘要卡片與展開區完整資料。

---

### Task 1: Add Shared Reading Budget Wrapper

**Files:**
- Modify: `app/ui/report_html.py`
- Test: `tests/test_streamlit_report_html.py`

- [ ] **Step 1: Write failing tests for the shared wrapper through comparison matrix output**

Add this test near `test_report_html_renders_all_comparison_matrix_rows` in `tests/test_streamlit_report_html.py`:

```python
def test_report_html_collapses_large_comparison_matrix_to_reading_budget() -> None:
    helpers = load_report_helpers()
    rows = "\n".join(
        f"| {1000 + index} 測試{index} | 觀察 / 等風險降低 | 2026-05-22 收盤 {index} | 等風險下降 | 20 分 | 7 分 | 目前估值接近同業 | 高 | 測試{index} |"
        for index in range(1, 21)
    )
    markdown = f"""
# AI 產業鏈 自動分析報告

## 個股比較矩陣
| 股票 | 判斷 | 最新可取得收盤價 | 追價風險標籤 | 目前情境升值分 | 目前情境降值分 | 目前估值位置 | 財務信心 | 核心提醒 |
|---|---|---|---|---:|---:|---|---|---|
{rows}
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert 'data-reading-budget="comparison-matrix"' in html
    assert "個股比較矩陣（20 檔）" in html
    assert "顯示 3 / 20" in html
    assert "另有 17 檔可展開" in html
    assert "展開全部 20 檔" in html
    assert html.count('class="matrix-card') == 23
    preview_html = html.split('data-reading-budget-preview="comparison-matrix"', 1)[1].split(
        'data-reading-budget-full="comparison-matrix"', 1
    )[0]
    assert preview_html.count('class="matrix-card') == 3
    assert "1020 測試20" in html
```

Update `test_report_html_renders_all_comparison_matrix_rows` so it expects the full data to exist in the document, not all cards to be visible in the preview:

```python
def test_report_html_renders_all_comparison_matrix_rows() -> None:
    helpers = load_report_helpers()
    rows = "\n".join(
        f"| {1000 + index} 測試{index} | 觀察 / 等風險降低 | 2026-05-22 收盤 {index} | 等風險下降 | 20 分 | 7 分 | 目前估值接近同業 | 高 | 測試 |"
        for index in range(1, 21)
    )
    markdown = f"""
# AI 產業鏈 自動分析報告

## 個股比較矩陣
| 股票 | 判斷 | 最新可取得收盤價 | 追價風險標籤 | 目前情境升值分 | 目前情境降值分 | 目前估值位置 | 財務信心 | 核心提醒 |
|---|---|---|---|---:|---:|---|---|---|
{rows}
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert html.count('class="matrix-card') == 23
    assert "共 20 檔" in html
    assert "觀察 20" in html
    assert "1020 測試20" in html
    assert 'data-reading-budget-full="comparison-matrix"' in html
```

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_streamlit_report_html.py::test_report_html_collapses_large_comparison_matrix_to_reading_budget tests/test_streamlit_report_html.py::test_report_html_renders_all_comparison_matrix_rows -q
```

Expected: the new test fails because `data-reading-budget="comparison-matrix"` and the wrapper strings do not exist yet.

- [ ] **Step 3: Add the shared wrapper to `app/ui/report_html.py`**

Add these imports and constants near the top of `app/ui/report_html.py`:

```python
from collections.abc import Callable

READING_BUDGET_PREVIEW_LIMIT = 3
```

Add this helper below `load_report_html_css()`:

```python
def reading_budget_section_html(
    *,
    section_id: str,
    title: str,
    noun: str,
    items: list[str],
    summary_html: str = "",
    preview_limit: int = READING_BUDGET_PREVIEW_LIMIT,
    preview_items: list[str] | None = None,
    empty_html: str = "<p class='muted'>目前沒有可呈現的資料。</p>",
    list_class: str = "",
) -> str:
    total = len(items)
    selected_preview = preview_items if preview_items is not None else items[:preview_limit]
    visible_count = min(len(selected_preview), total)
    title_with_count = f"{title}（{total} {noun}）" if total else title
    if total == 0:
        return f"<section class='panel' data-reading-budget='{escape(section_id)}'><h2>{escape(title)}</h2>{empty_html}</section>"

    preview_body = "".join(selected_preview) or empty_html
    preview_class = f"reading-budget-preview {list_class}".strip()
    if total <= preview_limit:
        return f"""
        <section class="panel reading-budget-section" data-reading-budget="{escape(section_id)}">
          <div class="reading-budget-head">
            <h2>{escape(title_with_count)}</h2>
            <span>顯示 {visible_count} / {total}</span>
          </div>
          {summary_html}
          <div class="{escape(preview_class)}" data-reading-budget-preview="{escape(section_id)}">{preview_body}</div>
        </section>
        """

    remaining = total - visible_count
    full_class = f"reading-budget-full {list_class}".strip()
    return f"""
    <section class="panel reading-budget-section" data-reading-budget="{escape(section_id)}">
      <div class="reading-budget-head">
        <h2>{escape(title_with_count)}</h2>
        <span>顯示 {visible_count} / {total}</span>
      </div>
      {summary_html}
      <div class="{escape(preview_class)}" data-reading-budget-preview="{escape(section_id)}">{preview_body}</div>
      <p class="reading-budget-more">另有 {remaining} {noun}可展開</p>
      <details class="reading-budget-details">
        <summary>展開全部 {total} {noun}</summary>
        <div class="{escape(full_class)}" data-reading-budget-full="{escape(section_id)}">{"".join(items)}</div>
      </details>
    </section>
    """
```

- [ ] **Step 4: Expose comparison matrix cards from `app/ui/report_sections.py`**

In `app/ui/report_sections.py`, rename the body of `comparison_matrix_html` into a new function and keep the old wrapper:

```python
def comparison_matrix_cards(markdown: str) -> tuple[str, list[str]]:
    rows = markdown_table_rows(markdown, "個股比較矩陣", limit=60)
    if not rows:
        return "", []
    cards = []
    action_count = 0
    watch_count = 0
    risk_count = 0
    for row in rows:
        if len(row) >= 9:
            stock_raw, decision_raw, price_raw, price_label_raw = row[0], row[1], row[2], row[3]
            upside_raw, downside_raw, valuation_raw, confidence_raw = row[4], row[5], row[6], row[7]
            reminder_raw = row[8]
        else:
            stock_raw = row[0] if len(row) > 0 else "-"
            decision_raw = row[1] if len(row) > 1 else "-"
            price_raw = "-"
            price_label_raw = "未標示"
            upside_raw = row[2] if len(row) > 2 else "-"
            downside_raw = row[3] if len(row) > 3 else "-"
            valuation_raw = row[4] if len(row) > 4 else "-"
            confidence_raw = row[5] if len(row) > 5 else "-"
            reminder_raw = row[6] if len(row) > 6 else ""
        stock = escape(stock_raw)
        decision = escape(decision_raw)
        price = escape(price_raw)
        price_label = escape(price_label_raw)
        upside = escape(upside_raw)
        downside = escape(downside_raw)
        valuation = escape(valuation_raw)
        confidence = escape(confidence_raw)
        reminder = escape(reminder_raw)
        decision_class = decision_badge_class(decision_raw)
        valuation_class = valuation_badge_class(valuation_raw)
        downside_class = downside_badge_class(downside_raw)
        price_class = current_price_badge_class(price_label_raw)
        if decision_class == "decision-action":
            action_count += 1
        elif decision_class == "decision-risk":
            risk_count += 1
        else:
            watch_count += 1
        cards.append(
            f"""
            <article class="matrix-card {decision_class}">
              <div class="matrix-top">
                <div>
                  <div class="ticker">{stock}</div>
                  <div class="reason">{reminder}</div>
                </div>
                <span class="decision {decision_class}">{decision}</span>
              </div>
              <div class="mini-grid">
                <div><span>最新可取得收盤價</span><strong>{price}</strong></div>
                <div class="{price_class}"><span>追價風險標籤</span><strong>{price_label}</strong></div>
                <div><span>目前情境升值分</span><strong>{upside}</strong></div>
                <div class="{downside_class}"><span>目前情境降值分</span><strong>{downside}</strong></div>
                <div class="{valuation_class}"><span>目前估值</span><strong>{valuation}</strong></div>
                <div><span>信心</span><strong>{confidence}</strong></div>
              </div>
            </article>
            """
        )
    summary = (
        f"<div class='matrix-summary'>"
        f"<span>共 {len(rows)} 檔</span>"
        f"<span>可研究 {action_count}</span>"
        f"<span>觀察 {watch_count}</span>"
        f"<span>風險 {risk_count}</span>"
        f"</div>"
    )
    return summary, cards


def comparison_matrix_html(markdown: str) -> str:
    summary, cards = comparison_matrix_cards(markdown)
    return summary + "".join(cards) if cards else ""
```

- [ ] **Step 5: Wire comparison matrix through the wrapper**

Update the import in `app/ui/report_html.py`:

```python
from app.ui.report_sections import (
    company_analysis_html,
    comparison_matrix_cards,
    credibility_html,
    detail_html,
    early_potential_radar_html,
    follow_up_tasks_html,
    investment_thesis_html,
    next_steps_html,
)
```

Replace:

```python
comparison_html = comparison_matrix_html(markdown)
```

with:

```python
comparison_summary_html, comparison_cards = comparison_matrix_cards(markdown)
```

Replace the comparison matrix section in the returned HTML:

```python
{"<section class='panel'><h2>個股比較矩陣</h2><div class='matrix-list'>" + comparison_html + "</div></section>" if comparison_html else ""}
```

with:

```python
{reading_budget_section_html(
    section_id="comparison-matrix",
    title="個股比較矩陣",
    noun="檔",
    items=comparison_cards,
    summary_html=comparison_summary_html,
    list_class="matrix-list",
) if comparison_cards else ""}
```

- [ ] **Step 6: Run the focused tests until green**

Run:

```bash
.venv/bin/python -m pytest tests/test_streamlit_report_html.py::test_report_html_collapses_large_comparison_matrix_to_reading_budget tests/test_streamlit_report_html.py::test_report_html_renders_all_comparison_matrix_rows -q
```

Expected: both tests pass.

- [ ] **Step 7: Commit Task 1**

```bash
git add app/ui/report_html.py app/ui/report_sections.py tests/test_streamlit_report_html.py
git commit -m "Add report reading budget wrapper"
```

---

### Task 2: Apply Reading Budget To Investment, Radar, Thesis, And Follow-Up Tasks

**Files:**
- Modify: `app/ui/report_html.py`
- Modify: `app/ui/report_sections.py`
- Test: `tests/test_streamlit_report_html.py`

- [ ] **Step 1: Write failing tests for short and long sections**

Add these tests to `tests/test_streamlit_report_html.py`:

```python
def test_report_html_does_not_wrap_short_sections_with_extra_details() -> None:
    helpers = load_report_helpers()
    markdown = """
# AI 產業鏈 自動分析報告

## 投資建議
| 股票 | 最新可取得收盤價 | 追價風險標籤 | 建議 | 理由 | 單檔上限 | 來源 |
|---|---|---|---|---|---:|---|
| 2330 台積電 | 2026-05-22 收盤 100 | 可研究但勿追高 | 可小額分批研究 | 測試 | 約 100,000 元 | 測試 |
| 2382 廣達 | 2026-05-22 收盤 80 | 等風險下降 | 觀察 / 等風險降低 | 測試 | 0 元 | 測試 |
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert 'data-reading-budget="investment-advice"' in html
    assert "顯示 2 / 2" in html
    assert "另有" not in html
    assert "展開全部 2 檔" not in html
```

```python
def test_report_html_collapses_follow_up_tasks_to_reading_budget() -> None:
    helpers = load_report_helpers()
    rows = "\n".join(
        f"| 任務{index} | 2330 | high | weekly | 補強原因{index} |"
        for index in range(1, 7)
    )
    markdown = f"""
# AI 產業鏈 自動分析報告

## 自動補強任務
| 任務 | 股票 | 優先級 | 頻率 | 觸發原因 |
|---|---|---|---|---|
{rows}
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert 'data-reading-budget="follow-up-tasks"' in html
    assert "系統會自動補強（6 項）" in html
    assert "顯示 3 / 6" in html
    assert "另有 3 項可展開" in html
    preview_html = html.split('data-reading-budget-preview="follow-up-tasks"', 1)[1].split(
        'data-reading-budget-full="follow-up-tasks"', 1
    )[0]
    assert preview_html.count('class="task-card"') == 3
    assert "任務6" in html
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_streamlit_report_html.py::test_report_html_does_not_wrap_short_sections_with_extra_details tests/test_streamlit_report_html.py::test_report_html_collapses_follow_up_tasks_to_reading_budget -q
```

Expected: both fail because investment advice and follow-up tasks are not routed through `reading_budget_section_html`.

- [ ] **Step 3: Add card-list helpers to `app/ui/report_sections.py`**

Replace `follow_up_tasks_html` with a card helper plus wrapper:

```python
def follow_up_task_cards(markdown: str) -> list[str]:
    rows = markdown_table_rows(markdown, "自動補強任務", limit=30)
    if not rows:
        return []
    cards = []
    for row in rows:
        task = escape(row[0]) if len(row) > 0 else "-"
        tickers = escape(row[1]) if len(row) > 1 else "-"
        purpose = escape(row[2]) if len(row) > 5 else "追蹤更新"
        priority = escape(row[3]) if len(row) > 5 else escape(row[2]) if len(row) > 2 else "-"
        frequency = escape(row[4]) if len(row) > 5 else escape(row[3]) if len(row) > 3 else "-"
        reason = escape(row[5]) if len(row) > 5 else escape(row[4]) if len(row) > 4 else ""
        cards.append(
            f"""
            <article class="task-card">
              <div>
                <div class="ticker">{task}</div>
                <div class="reason">{reason}</div>
              </div>
              <div class="task-meta">
                <span>{tickers}</span>
                <span>{purpose}</span>
                <span>{priority}</span>
                <span>{frequency}</span>
              </div>
            </article>
            """
        )
    return cards


def follow_up_tasks_html(markdown: str) -> str:
    return "".join(follow_up_task_cards(markdown))
```

Add helpers for radar and thesis by wrapping existing card creation loops:

```python
def early_potential_radar_cards(markdown: str) -> list[str]:
    rows = markdown_table_rows(markdown, "早期潛力雷達", limit=30)
    if not rows:
        return []
    cards = []
    for row in rows:
        if not row or row[0] in {"目前無足夠數據判斷", "目前無足夠數據判斷。"}:
            continue
        stock = escape(row[0]) if len(row) > 0 else "-"
        score = escape(row[1]) if len(row) > 1 else "-"
        attention_raw = row[2] if len(row) > 2 else "-"
        attention = escape(attention_raw)
        upside = escape(row[3]) if len(row) > 3 else "-"
        downside_raw = row[4] if len(row) > 4 else "-"
        downside = escape(downside_raw)
        reason = escape(row[5]) if len(row) > 5 else ""
        source = escape(row[6]) if len(row) > 6 else ""
        attention_class = (
            "attention-low"
            if any(term in attention_raw for term in ["報導較少", "報導偏少", "低關注"])
            else "attention-known"
        )
        cards.append(
            f"""
            <article class="radar-card {attention_class}">
              <div class="matrix-top">
                <div>
                  <div class="ticker">{stock}</div>
                  <div class="reason">{reason}</div>
                </div>
                <span class="decision {attention_class}">{attention}</span>
              </div>
              <div class="mini-grid">
                <div><span>早期線索分</span><strong>{score}</strong></div>
                <div><span>目前情境升值分</span><strong>{upside}</strong></div>
                <div class="{downside_badge_class(downside_raw)}"><span>目前情境降值分</span><strong>{downside}</strong></div>
              </div>
              <div class="thesis-source">{source or "目前無足夠代表來源。"}</div>
            </article>
            """
        )
    return cards


def early_potential_radar_html(markdown: str) -> str:
    return "".join(early_potential_radar_cards(markdown))
```

For `investment_thesis_html`, extract the existing cards into:

```python
def investment_thesis_cards(markdown: str) -> list[str]:
    section = markdown_section_or_none(markdown, "投資理由地圖")
    if not section:
        return []
    company_blocks = re.split(r"(?m)^### (?=\d{4}\s)", section)
    cards = []
    for block in company_blocks[1:]:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        title = lines[0].replace("**", "")
        facts = {}
        for line in lines[1:]:
            if not line.startswith("- "):
                continue
            text = line[2:].replace("**", "").strip()
            if "：" not in text:
                continue
            key, value = text.split("：", 1)
            facts[key.strip()] = value.strip()
        source_text = facts.get("代表性來源", "目前無足夠公司層級來源。")
        if facts.get("風險來源"):
            source_text = f"{source_text}｜風險來源：{facts['風險來源']}"
        cards.append(
            f"""
            <article class="thesis-card">
              <div class="thesis-head">
                <div>
                  <div class="ticker">{escape(title)}</div>
                  <div class="reason">{escape(facts.get("目前判斷", "先看資料品質，再決定是否研究。"))}</div>
                </div>
              </div>
              <div class="thesis-body">
                <div><span>值得研究的理由</span><p>{escape(facts.get("具體投資理由", "目前投資理由尚未完整。"))}</p></div>
                <div><span>成長假設</span><p>{escape(facts.get("成長假設", "目前無足夠數據判斷。"))}</p></div>
                <div><span>主要風險</span><p>{escape(facts.get("主要風險", "目前無足夠數據判斷。"))}</p></div>
                {"<div><span>營收口徑提醒</span><p>" + escape(facts.get("營收口徑提醒", "")) + "</p></div>" if facts.get("營收口徑提醒") else ""}
                <div><span>需要再確認</span><p>{escape(facts.get("需要再確認", "等待下一批資料確認。"))}</p></div>
              </div>
              <div class="thesis-source">{escape(source_text)}</div>
            </article>
            """
        )
    return cards


def investment_thesis_html(markdown: str) -> str:
    return "".join(investment_thesis_cards(markdown))
```

- [ ] **Step 4: Add investment card helper in `app/ui/report_html.py`**

Add this helper near `reading_budget_section_html`:

```python
def investment_advice_cards(markdown: str) -> list[str]:
    investment_rows = markdown_table_rows(markdown, "投資建議", limit=60)
    cards = []
    for row in investment_rows:
        if len(row) >= 7:
            ticker_raw, price_raw, price_label_raw, decision_raw, reason_raw = row[0], row[1], row[2], row[3], row[4]
        else:
            ticker_raw = row[0] if len(row) > 0 else "-"
            price_raw = "-"
            price_label_raw = "未標示"
            decision_raw = row[1] if len(row) > 1 else "-"
            reason_raw = row[2] if len(row) > 2 else ""
        ticker = escape(ticker_raw)
        price = escape(price_raw)
        price_label = escape(price_label_raw)
        decision = escape(decision_raw)
        reason = escape(reason_raw)
        price_class = current_price_badge_class(price_label_raw)
        cards.append(
            f"""
            <article class="stock-card">
              <div>
                <div class="ticker">{ticker}</div>
                <div class="stock-meta">
                  <span>{price}</span>
                  <strong class="{price_class}">{price_label}</strong>
                </div>
                <div class="reason">{reason}</div>
              </div>
              <span class="decision">{decision}</span>
            </article>
            """
        )
    return cards
```

Remove the old inline `investment_rows` card-building loop from `report_html(...)` and replace it with:

```python
investment_cards = investment_advice_cards(markdown)
```

- [ ] **Step 5: Wire all supported sections through reading budget**

Update the `report_sections` import in `app/ui/report_html.py`:

```python
from app.ui.report_sections import (
    company_analysis_html,
    comparison_matrix_cards,
    credibility_html,
    detail_html,
    early_potential_radar_cards,
    follow_up_task_cards,
    investment_thesis_cards,
    next_steps_html,
)
```

Replace section variables:

```python
early_radar_html = early_potential_radar_html(markdown)
thesis_html = investment_thesis_html(markdown)
follow_up_html = follow_up_tasks_html(markdown)
```

with:

```python
early_radar_cards = early_potential_radar_cards(markdown)
thesis_cards = investment_thesis_cards(markdown)
follow_up_cards = follow_up_task_cards(markdown)
```

Replace the corresponding HTML sections with:

```python
{reading_budget_section_html(
    section_id="follow-up-tasks",
    title="系統會自動補強",
    noun="項",
    items=follow_up_cards,
    list_class="stock-list",
) if follow_up_cards else ""}
```

```python
{reading_budget_section_html(
    section_id="early-potential-radar",
    title="早期潛力雷達",
    noun="檔",
    items=early_radar_cards,
    summary_html="<p class='muted'>專看截至目前報導較少、但近況訊號轉強的研究線索；不是買賣指令，也不是自選股狀態。</p>",
    list_class="matrix-list",
) if early_radar_cards else ""}
```

```python
{reading_budget_section_html(
    section_id="investment-thesis",
    title="投資理由地圖",
    noun="張",
    items=thesis_cards,
    list_class="thesis-list",
) if thesis_cards else ""}
```

```python
{reading_budget_section_html(
    section_id="investment-advice",
    title="個股建議",
    noun="檔",
    items=investment_cards,
    empty_html="<p class='muted'>目前沒有可呈現的個股建議。</p>",
    list_class="stock-list",
)}
```

- [ ] **Step 6: Run focused and compatibility tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_streamlit_report_html.py::test_report_html_does_not_wrap_short_sections_with_extra_details tests/test_streamlit_report_html.py::test_report_html_collapses_follow_up_tasks_to_reading_budget tests/test_streamlit_report_html.py::test_report_html_renders_follow_up_tasks tests/test_streamlit_report_html.py::test_report_html_renders_investment_thesis_cards tests/test_streamlit_report_html.py::test_report_html_renders_early_potential_radar_cards -q
```

Expected: all listed tests pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add app/ui/report_html.py app/ui/report_sections.py tests/test_streamlit_report_html.py
git commit -m "Apply reading budget to report sections"
```

---

### Task 3: Prioritize Candidate Audit And Next-Step Groups

**Files:**
- Modify: `app/ui/report_candidate_audit.py`
- Modify: `app/ui/report_sections.py`
- Test: `tests/test_streamlit_report_html.py`

- [ ] **Step 1: Write failing tests for priority previews**

Add this candidate audit test:

```python
def test_report_html_collapses_candidate_audit_to_priority_preview() -> None:
    helpers = load_report_helpers()
    html = helpers["report_html"](
        "# AI 產業鏈 自動分析報告",
        {
            "report_id": 1,
            "quality_gate": {},
            "candidate_whitelist": [
                {"ticker": "2382", "name": "廣達", "segment": "系統組裝", "status": "evidence_supported", "evidence_count": 2, "evidence_source_count": 2, "validation_reason": "通過正式分析門檻", "next_action": "納入正式分析"},
                {"ticker": "3324", "name": "雙鴻", "segment": "散熱模組", "status": "weak_evidence", "evidence_count": 1, "evidence_source_count": 1, "validation_reason": "弱證據：來源不足", "next_action": "補抓公司新聞"},
                {"ticker": "2308", "name": "台達電", "segment": "電源", "status": "needs_evidence", "evidence_count": 0, "evidence_source_count": 0, "validation_reason": "缺少公司主題證據", "next_action": "重新補抓"},
                {"ticker": "3059", "name": "華晶科", "segment": "相機", "status": "evidence_limited", "evidence_count": 4, "evidence_source_count": 2, "validation_reason": "補查後未升格", "next_action": "等待公告"},
                {"ticker": "8046", "name": "南電", "segment": "PCB", "status": "evidence_unavailable", "evidence_count": 0, "evidence_source_count": 0, "validation_reason": "資料不足排除", "next_action": "排除"},
            ],
        },
    )

    assert 'data-reading-budget="candidate-audit"' in html
    assert "候選公司審計（5 張）" in html
    preview_html = html.split('data-reading-budget-preview="candidate-audit"', 1)[1].split(
        'data-reading-budget-full="candidate-audit"', 1
    )[0]
    assert "3324 雙鴻" in preview_html
    assert "2308 台達電" in preview_html
    assert "3059 華晶科" in preview_html
    assert "2382 廣達" not in preview_html
    assert "8046 南電" in html
```

Add this next-step test:

```python
def test_report_html_collapses_next_step_groups() -> None:
    helpers = load_report_helpers()
    watch_rows = "\n".join(
        f"- {1000 + index} 測試{index}：觀察 / 等風險降低；下一步補查 等待新證據。"
        for index in range(1, 8)
    )
    markdown = f"""
# AI 產業鏈 自動分析報告

## 下一步行動
1. 先處理資料缺口。
2. 只把資料完整且通過門檻的股票放進研究清單。

### 待補資料 / 觀察
{watch_rows}
"""

    html = helpers["report_html"](markdown, {"report_id": 1, "quality_gate": {}})

    assert 'data-next-step-group="待補資料 / 觀察"' in html
    assert "待補資料 / 觀察（7 項）" in html
    assert "另有 4 項可展開" in html
    group_preview = html.split('data-next-step-preview="待補資料 / 觀察"', 1)[1].split(
        'data-next-step-full="待補資料 / 觀察"', 1
    )[0]
    assert "1001 測試1" in group_preview
    assert "1003 測試3" in group_preview
    assert "1004 測試4" not in group_preview
    assert "1007 測試7" in html
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_streamlit_report_html.py::test_report_html_collapses_candidate_audit_to_priority_preview tests/test_streamlit_report_html.py::test_report_html_collapses_next_step_groups -q
```

Expected: both fail because candidate audit is not priority-previewed and next-step groups still show all items directly.

- [ ] **Step 3: Refactor candidate audit into summary and cards**

In `app/ui/report_candidate_audit.py`, add this helper:

```python
def candidate_audit_priority_key(card: str) -> int:
    if "audit-weak" in card:
        return 0
    if "audit-needs" in card:
        return 1
    if "audit-limited" in card:
        return 2
    if "audit-unavailable" in card:
        return 3
    return 4
```

Change the end of `candidate_audit_html` by extracting the row-to-card logic into:

```python
def candidate_audit_summary_and_cards(markdown: str, result: Optional[dict] = None) -> tuple[str, list[str]]:
    candidates = result.get("candidate_whitelist", []) if result else []
    rows = []
    if candidates:
        status_labels = {
            "evidence_supported": "正式分析",
            "weak_evidence": "弱證據觀察",
            "needs_evidence": "待補證據",
            "evidence_limited": "補查後未升格",
            "evidence_unavailable": "資料不足排除",
        }
        for candidate in candidates:
            raw_sources = candidate.get("evidence_sources") or []
            evidence_sources = [
                source
                for source in raw_sources
                if candidate_source_matches_display_entity(candidate, source)
            ]
            filtered_source_count = max(0, len(raw_sources) - len(evidence_sources))
            filtered_note = (
                f"已排除 {filtered_source_count} 筆疑似同名或非本公司的來源。"
                if filtered_source_count
                else ""
            )
            source_summary = "；".join(
                " / ".join(
                    part
                    for part in [
                        str(source.get("title") or ""),
                        str(source.get("publisher") or ""),
                        str(source.get("published_at") or ""),
                    ]
                    if part
                )
                for source in evidence_sources[:2]
            )
            rows.append(
                [
                    f"{candidate.get('ticker')} {candidate.get('name')}",
                    candidate.get("segment") or "未分類",
                    status_labels.get(candidate.get("status"), "待補證據"),
                    (
                        f"{int(candidate.get('evidence_count') or 0)} 篇 / "
                        f"{int(candidate.get('evidence_source_count') or 0)} 來源"
                        + (f"（排除 {filtered_source_count}）" if filtered_source_count else "")
                    ),
                    normalize_candidate_audit_display_text(
                        f"{candidate_payload_stale_note(candidate)}"
                        f"{filtered_note}"
                        f"{candidate.get('validation_reason') or ''}"
                    ),
                    normalize_candidate_audit_display_text(candidate.get("next_action") or ""),
                    source_summary,
                    candidate_payload_confidence_text(candidate),
                ]
            )
    else:
        rows = markdown_table_rows_by_header(markdown, "候選公司審計", "股票", limit=30)
    if not rows:
        return "", []
    supported = [row for row in rows if len(row) > 2 and "正式分析" in row[2]]
    weak = [row for row in rows if len(row) > 2 and "弱證據" in row[2]]
    needs = [row for row in rows if len(row) > 2 and "待補" in row[2]]
    limited = [row for row in rows if len(row) > 2 and "補查後未升格" in row[2]]
    unavailable = [row for row in rows if len(row) > 2 and "資料不足排除" in row[2]]
    cards = []
    for row in rows:
        stock = escape(row[0]) if len(row) > 0 else "-"
        segment = escape(row[1]) if len(row) > 1 else "-"
        status_raw = row[2] if len(row) > 2 else "待補證據"
        status = escape(status_raw)
        evidence = escape(row[3]) if len(row) > 3 else "-"
        reason = escape(row[4]) if len(row) > 4 else ""
        next_action = escape(row[5]) if len(row) > 5 else ""
        source_summary = escape(row[6]) if candidates and len(row) > 6 else ""
        confidence = escape(row[7] if candidates and len(row) > 7 else row[6] if not candidates and len(row) > 6 else "")
        status_class = (
            "audit-supported"
            if "正式分析" in status_raw
            else "audit-weak"
            if "弱證據" in status_raw
            else "audit-limited"
            if "補查後未升格" in status_raw
            else "audit-unavailable"
            if "資料不足排除" in status_raw
            else "audit-needs"
        )
        cards.append(
            f"""
            <article class="audit-card {status_class}">
              <div>
                <div class="ticker">{stock}</div>
                <div class="reason">{segment}</div>
                <div class="audit-reason">{reason}</div>
                <div class="audit-next">{next_action}</div>
                {"<div class='audit-source'>" + source_summary + "</div>" if source_summary else ""}
              </div>
              <div class="audit-meta">
                <span>{status}</span>
                <span>{evidence}</span>
                {"<span>" + confidence + "</span>" if confidence else ""}
              </div>
            </article>
            """
        )
    summary = (
        "<div class='audit-summary'>"
        f"<span>候選卡片 {len(rows)}</span>"
        f"<span>正式分析 {len(supported)}</span>"
        f"<span>弱證據 {len(weak)}</span>"
        f"<span>待補證據 {len(needs)}</span>"
        f"<span>補查後未升格 {len(limited)}</span>"
        f"<span>資料不足排除 {len(unavailable)}</span>"
        "</div>"
    )
    return summary, cards


def candidate_audit_html(markdown: str, result: Optional[dict] = None) -> str:
    summary, cards = candidate_audit_summary_and_cards(markdown, result)
    return summary + "".join(cards) if cards else ""
```

- [ ] **Step 4: Wire candidate audit through reading budget**

Update `app/ui/report_html.py` import:

```python
from app.ui.report_candidate_audit import (
    candidate_audit_priority_key,
    candidate_audit_summary_and_cards,
)
```

Replace:

```python
audit_html = candidate_audit_html(markdown, result)
```

with:

```python
audit_summary_html, audit_cards = candidate_audit_summary_and_cards(markdown, result)
audit_preview_cards = sorted(
    enumerate(audit_cards),
    key=lambda indexed: (candidate_audit_priority_key(indexed[1]), indexed[0]),
)[:READING_BUDGET_PREVIEW_LIMIT]
audit_preview_html = [card for _, card in audit_preview_cards]
```

Replace candidate audit section with:

```python
{reading_budget_section_html(
    section_id="candidate-audit",
    title="候選公司審計",
    noun="張",
    items=audit_cards,
    summary_html=audit_summary_html,
    preview_items=audit_preview_html,
    list_class="stock-list",
) if audit_cards else ""}
```

- [ ] **Step 5: Collapse next-step groups in `app/ui/report_sections.py`**

Inside `next_steps_html`, replace each group block creation with:

```python
    for group in groups:
        items = group["items"]
        if not isinstance(items, list) or not items:
            continue
        title = str(group["title"])
        preview = items[:3]
        preview_body = "".join(f"<li>{escape(item)}</li>" for item in preview)
        full_body = "".join(f"<li>{escape(item)}</li>" for item in items)
        remaining = len(items) - len(preview)
        if remaining > 0:
            blocks.append(
                f"""
                <div class="next-step-group" data-next-step-group="{escape(title)}">
                  <strong>{escape(title)}（{len(items)} 項）</strong>
                  <ul data-next-step-preview="{escape(title)}">{preview_body}</ul>
                  <p class="reading-budget-more">另有 {remaining} 項可展開</p>
                  <details class="reading-budget-details">
                    <summary>展開全部 {len(items)} 項</summary>
                    <ul data-next-step-full="{escape(title)}">{full_body}</ul>
                  </details>
                </div>
                """
            )
        else:
            blocks.append(
                f"""
                <div class="next-step-group" data-next-step-group="{escape(title)}">
                  <strong>{escape(title)}（{len(items)} 項）</strong>
                  <ul data-next-step-preview="{escape(title)}">{preview_body}</ul>
                </div>
                """
            )
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_streamlit_report_html.py::test_report_html_collapses_candidate_audit_to_priority_preview tests/test_streamlit_report_html.py::test_report_html_collapses_next_step_groups tests/test_streamlit_report_html.py::test_report_html_renders_candidate_audit_from_result_payload tests/test_streamlit_report_html.py::test_report_html_renders_full_next_step_groups -q
```

Expected: all listed tests pass. `test_report_html_renders_full_next_step_groups` should still pass because the final item exists in the full `<details>` block.

- [ ] **Step 7: Commit Task 3**

```bash
git add app/ui/report_html.py app/ui/report_candidate_audit.py app/ui/report_sections.py tests/test_streamlit_report_html.py
git commit -m "Prioritize report reading budget previews"
```

---

### Task 4: Add Report HTML Styles And Run Focused Regression

**Files:**
- Modify: `app/ui/styles/report_html.css`
- Test: `tests/test_streamlit_report_html.py`
- Test: `tests/test_streamlit_ui_contract.py`
- Test: `tests/test_status_frontend.py`

- [ ] **Step 1: Add CSS contract assertions**

Add this test to `tests/test_streamlit_report_html.py`:

```python
def test_report_html_embeds_reading_budget_styles() -> None:
    helpers = load_report_helpers()
    html = helpers["report_html"]("# AI 產業鏈 自動分析報告\n", {"report_id": 1, "quality_gate": {}})

    assert ".reading-budget-section" in html
    assert ".reading-budget-head" in html
    assert ".reading-budget-more" in html
    assert ".reading-budget-details" in html
```

- [ ] **Step 2: Run style test and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_streamlit_report_html.py::test_report_html_embeds_reading_budget_styles -q
```

Expected: fails because the CSS classes are not defined yet.

- [ ] **Step 3: Add CSS to `app/ui/styles/report_html.css`**

Append this block after the `.panel` rules:

```css
.reading-budget-section { position:relative; }
.reading-budget-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; margin-bottom:10px; }
.reading-budget-head h2 { margin:0; }
.reading-budget-head span { display:inline-flex; align-items:center; border:1px solid #D7DEE8; border-radius:999px; padding:5px 9px; color:#344054; background:#F4F7FB; font-size:12px; font-weight:800; white-space:nowrap; }
.reading-budget-preview { margin-top:8px; }
.reading-budget-more { margin:10px 0 0; color:#53657D; font-size:13px; font-weight:700; }
.reading-budget-details { margin-top:10px; background:#FFFFFF; }
.reading-budget-details summary { color:#1D4ED8; }
.reading-budget-full { margin-top:10px; }
```

Update the mobile media rule:

```css
@media (max-width:760px) { .grid,.trust-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .matrix-list,.thesis-body,.credibility-grid { grid-template-columns:1fr; } .stock-card,.task-card,.audit-card,.matrix-top,.credibility-head,.reading-budget-head { display:block; } .decision,.task-meta,.audit-meta,.credibility-badge,.reading-budget-head span { display:inline-flex; margin-top:10px; justify-content:flex-start; min-width:0; } }
```

- [ ] **Step 4: Run focused report HTML tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_streamlit_report_html.py -q
```

Expected: all report HTML tests pass.

- [ ] **Step 5: Run UI contract and frontend status tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_streamlit_ui_contract.py tests/test_status_frontend.py -q
```

Expected: both files pass. If a source-inspection test expects old imports, update it to accept the new helper names while preserving the renderer extraction contract.

- [ ] **Step 6: Commit Task 4**

```bash
git add app/ui/styles/report_html.css tests/test_streamlit_report_html.py tests/test_streamlit_ui_contract.py tests/test_status_frontend.py
git commit -m "Style report reading budget sections"
```

---

### Task 5: Browser QA And Final Verification

**Files:**
- Modify only if verification exposes layout issues: `app/ui/styles/report_html.css`
- Test: runtime-generated HTML from `app/ui/report_html.py`

- [ ] **Step 1: Generate a local HTML fixture for visual QA**

Run:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from app.ui.report_html import report_html

rows = "\n".join(
    f"| {1000 + index} 測試{index} | {'可小額分批研究' if index in (1, 2) else '觀察 / 等風險降低'} | 2026-05-22 收盤 {index} | {'可研究但勿追高' if index in (1, 2) else '等風險下降'} | 20 分 | 7 分 | 目前估值接近同業 | 高 | 測試提醒{index} |"
    for index in range(1, 13)
)
markdown = f"""
# AI 產業鏈 自動分析報告

## 一頁摘要
| 項目 | 結果 |
|---|---|
| 本次股票範圍 | 12 檔 |
| 可小額研究 | 2 檔 |
| 觀察/待補 | 10 檔 |

## 個股比較矩陣
| 股票 | 判斷 | 最新可取得收盤價 | 追價風險標籤 | 目前情境升值分 | 目前情境降值分 | 目前估值位置 | 財務信心 | 核心提醒 |
|---|---|---|---|---:|---:|---|---|---|
{rows}

## 自動補強任務
| 任務 | 股票 | 優先級 | 頻率 | 觸發原因 |
|---|---|---|---|---|
| 刷新股價/量能 | 2330 | high | weekly | 領先訊號偏空，需重新檢查 |
| 刷新月營收 | 2382 | high | monthly | 補齊月營收與公司文本 |
| 補抓新聞 | 3324 | medium | weekly | 弱證據候選補強 |
| 補抓公告 | 2308 | low | monthly | 等待官方文件 |
"""
Path("/tmp/report-reading-budget-qa.html").write_text(
    report_html(markdown, {"report_id": 99, "quality_gate": {"status": "ready"}}),
    encoding="utf-8",
)
print("/tmp/report-reading-budget-qa.html")
PY
```

Expected: prints `/tmp/report-reading-budget-qa.html`.

- [ ] **Step 2: Open the fixture with Browser**

Use the Browser plugin and navigate to:

```text
file:///tmp/report-reading-budget-qa.html
```

Expected visual checks:

- First viewport shows hero metrics, decision rail, and the beginning of the concise report.
- Long sections show `顯示 3 / N` badges.
- Preview cards do not overlap.
- The text `另有 N 檔可展開` is visible below previews.
- Opening `<summary>展開全部 N 檔</summary>` reveals the full card list.

- [ ] **Step 3: Check mobile viewport**

Set Browser viewport to a mobile width around 390px and reload the fixture.

Expected visual checks:

- Reading budget badge wraps below the heading instead of overflowing.
- Cards stack into one column.
- `<summary>` text fits within the details container.
- No button, badge, or stock label overlaps adjacent content.

- [ ] **Step 4: Fix visual issues if found**

If text overlaps or the badge overflows, adjust only `app/ui/styles/report_html.css`. Use this safe fallback:

```css
.reading-budget-head span { white-space:normal; text-align:left; }
```

Run:

```bash
.venv/bin/python -m pytest tests/test_streamlit_report_html.py -q
```

Expected: tests still pass after any CSS adjustment.

- [ ] **Step 5: Run full focused verification**

Run:

```bash
.venv/bin/python -m pytest tests/test_streamlit_report_html.py tests/test_report_center_document_panel.py tests/test_streamlit_ui_contract.py tests/test_status_frontend.py -q
```

Expected: all listed tests pass.

- [ ] **Step 6: Commit QA fixes if any**

If Step 4 changed CSS, commit it:

```bash
git add app/ui/styles/report_html.css
git commit -m "Polish report reading budget layout"
```

If Step 4 made no changes, do not create an empty commit.

---

## Self-Review

Spec coverage:

- Consistent summary, priority 3, remaining count, and full details are covered by Tasks 1-4.
- Long sections from the spec are covered: comparison matrix, investment advice, candidate audit, follow-up tasks, investment thesis, early radar, and next-step groups.
- Default collapsed supporting detail sections remain covered by existing `detail_html(...)` behavior.
- No data-generation or Markdown-template changes are included.
- Downloaded HTML and Streamlit iframe share `report_html(...)`, so both surfaces receive the same reading budget.

Placeholder scan:

- No `TBD`, `TODO`, `fill in details`, or unspecified implementation steps are intentionally present.
- Code steps provide concrete snippets, exact file paths, commands, and expected outcomes.

Type consistency:

- `reading_budget_section_html(...)` accepts `items: list[str]` and optional `preview_items: list[str]`.
- Section helpers return either `list[str]` or `(summary_html, list[str])` consistently.
- Candidate audit priority receives rendered card HTML, matching the planned sort point in `report_html.py`.
