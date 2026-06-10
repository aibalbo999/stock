# Operator Workbench UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an operator-first Streamlit workbench that shows readiness, latest report, recent failures, and free-tier model routing before the existing analysis form.

**Architecture:** Keep the current Streamlit MPA and FastAPI/Celery boundaries. Add pure UI summary helpers for operator status and report health, then render compact status bands in existing pages. Long-running work continues to use existing background task helpers and task-status polling.

**Tech Stack:** Python 3, Streamlit, FastAPI JSON endpoints, pytest, Ruff, existing CSS in `app/ui/styles/stock_dashboard.css`.

---

## File Structure

- Create `app/ui/operator_status.py`
  - Pure helper functions that convert service, task, quota, and report payloads into operator-facing cards and captions.
  - No Streamlit import in this file.

- Create `app/ui/report_health.py`
  - Pure helper functions that summarize selected latest report health.
  - No Streamlit import in this file.

- Create `tests/test_operator_status_ui.py`
  - Unit tests for readiness state, latest task state, quota summary, report summary, and failure action wording.

- Create `tests/test_report_health_ui.py`
  - Unit tests for report health summary and empty/missing payload behavior.

- Modify `tests/streamlit_ui_test_helpers.py`
  - Add the two new UI helper files to `UI_SOURCE_FILES`.

- Modify `tests/test_streamlit_ui_contract.py`
  - Assert new helper files, labels, CSS classes, and frontend API endpoints are present.

- Modify `app/ui/analysis_workspace.py`
  - Load `/services/status`, `/tasks/summary?days=7&limit=10`, `/llm/quota`, and `/reports?limit=5`.
  - Render "今日狀態" before the analysis form.

- Modify `app/ui/report_center.py`
  - Render compact latest-report health strip above download buttons and report tabs.

- Modify `app/ui/data_enrichment_market.py`
  - Add report-impact captions to the market refresh action area.

- Modify `app/ui/styles/stock_dashboard.css`
  - Add compact status-band, operator-card, report-health, and action-impact styles.

---

## Task 1: Operator Status Helpers

**Files:**
- Create: `app/ui/operator_status.py`
- Create: `tests/test_operator_status_ui.py`

- [ ] **Step 1: Write failing tests for operator summary helpers**

Add `tests/test_operator_status_ui.py`:

```python
from __future__ import annotations

from app.ui.operator_status import (
    operator_status_cards,
    operator_status_overall,
    quota_operator_summary,
    task_failure_action_summary,
)


def test_operator_status_overall_ready_when_queue_latest_task_and_report_are_ready() -> None:
    service_snapshot = {
        "task_queue": {
            "ready": True,
            "processing_ready": True,
            "worker_online": True,
        }
    }
    task_summary = {
        "totals": {"running_count": 0, "stale_running_count": 0},
        "recent": [{"status": "success", "operation": "market_refresh"}],
    }
    reports = [{"id": 15, "title": "記憶體產業鏈 自動分析報告"}]

    result = operator_status_overall(service_snapshot, task_summary, reports)

    assert result == {
        "state": "ready",
        "label": "可執行",
        "detail": "背景任務與最新版報告都可用。",
    }


def test_operator_status_overall_attention_for_historical_failure_with_healthy_queue() -> None:
    service_snapshot = {
        "task_queue": {
            "ready": True,
            "processing_ready": True,
            "worker_online": True,
        }
    }
    task_summary = {
        "totals": {"running_count": 0, "stale_running_count": 0},
        "recent": [
            {"status": "success", "operation": "market_refresh"},
            {
                "status": "failed",
                "operation": "follow_up_api",
                "error_category": "payload_validation",
                "retryable": True,
            },
        ],
    }
    reports = [{"id": 15, "title": "記憶體產業鏈 自動分析報告"}]

    result = operator_status_overall(service_snapshot, task_summary, reports)

    assert result["state"] == "attention"
    assert result["label"] == "有待處理紀錄"
    assert "最近任務可執行" in result["detail"]


def test_operator_status_cards_include_queue_quota_latest_report_and_failure_action() -> None:
    service_snapshot = {
        "task_queue": {
            "ready": True,
            "processing_ready": True,
            "worker_online": True,
        }
    }
    task_summary = {
        "recent": [
            {
                "id": 26,
                "status": "failed",
                "operation": "follow_up_api",
                "error_category": "payload_validation",
                "retryable": True,
                "task_id": "task-8150",
            }
        ]
    }
    quota = {
        "recommended_model": "gemini-3.5-flash",
        "model_order": ["gemini-3.5-flash", "gemini-2.5-flash", "gemma-4-31b-it"],
        "models": [
            {
                "model": "gemini-3.5-flash",
                "requests_remaining": 248,
                "request_budget": 250,
                "status": "available",
                "routing_tier": "primary",
            },
            {
                "model": "gemma-4-31b-it",
                "requests_remaining": 14400,
                "request_budget": 14400,
                "status": "available",
                "routing_tier": "high_quota_fallback",
            },
        ],
    }
    reports = [
        {
            "id": 15,
            "title": "記憶體產業鏈 自動分析報告",
            "topic": "記憶體產業鏈",
            "generated_at": "2026-06-06T16:31:24",
        }
    ]

    cards = operator_status_cards(service_snapshot, task_summary, quota, reports)

    assert [card["title"] for card in cards] == ["系統狀態", "最新版報告", "AI 額度", "待處理事項"]
    assert cards[0]["state"] == "ready"
    assert cards[1]["value"] == "#15"
    assert cards[2]["value"] == "gemini-3.5-flash"
    assert cards[3]["action_label"] == "可重試"


def test_quota_operator_summary_uses_high_quota_fallback_caption() -> None:
    result = quota_operator_summary(
        {
            "recommended_model": "gemini-2.5-flash",
            "models": [
                {
                    "model": "gemini-2.5-flash",
                    "requests_remaining": 120,
                    "request_budget": 250,
                    "status": "available",
                    "routing_tier": "fallback",
                },
                {
                    "model": "gemma-4-31b-it",
                    "requests_remaining": 14400,
                    "request_budget": 14400,
                    "status": "available",
                    "routing_tier": "high_quota_fallback",
                },
            ],
        }
    )

    assert result == {
        "recommended_model": "gemini-2.5-flash",
        "remaining": "120 / 250",
        "state": "ready",
        "caption": "高額度保底：gemma-4-31b-it",
    }


def test_task_failure_action_summary_maps_payload_validation_to_retryable_action() -> None:
    result = task_failure_action_summary(
        {
            "operation": "follow_up_api",
            "error_category": "payload_validation",
            "retryable": True,
            "task_id": "task-8150",
        }
    )

    assert result == {
        "state": "attention",
        "label": "輸入或白名單已擋下任務",
        "detail": "補強或重跑任務曾被 payload 驗證擋下；修正後可重試。",
        "action_label": "可重試",
        "route_hint": "task:task-8150",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_operator_status_ui.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.ui.operator_status'`.

- [ ] **Step 3: Implement `app/ui/operator_status.py`**

Create `app/ui/operator_status.py`:

```python
from __future__ import annotations

from typing import Any


def operator_status_overall(
    service_snapshot: dict,
    task_summary: dict,
    reports: list[dict],
) -> dict[str, str]:
    queue = _dict_value(service_snapshot.get("task_queue"))
    totals = _dict_value(task_summary.get("totals"))
    recent = _recent_items(task_summary)
    queue_ready = bool(queue.get("ready") and queue.get("processing_ready") and queue.get("worker_online"))
    if not queue_ready:
        return {
            "state": "blocked",
            "label": "背景任務未就緒",
            "detail": "請先到系統設定檢查 Redis/Celery worker。",
        }
    if int(totals.get("stale_running_count") or 0) > 0:
        return {
            "state": "blocked",
            "label": "有卡住任務",
            "detail": "有任務疑似卡住，請先到維護頁處理。",
        }
    has_failure = any(str(item.get("status") or "").lower() == "failed" for item in recent)
    if has_failure:
        return {
            "state": "attention",
            "label": "有待處理紀錄",
            "detail": "最近任務可執行，但仍有歷史失敗需要重試或確認。",
        }
    if not reports:
        return {
            "state": "attention",
            "label": "尚無最新版報告",
            "detail": "系統可執行，請先建立分析報告。",
        }
    return {
        "state": "ready",
        "label": "可執行",
        "detail": "背景任務與最新版報告都可用。",
    }


def operator_status_cards(
    service_snapshot: dict,
    task_summary: dict,
    quota: dict,
    reports: list[dict],
) -> list[dict[str, str]]:
    queue = _dict_value(service_snapshot.get("task_queue"))
    latest_report = _first_report(reports)
    quota_summary = quota_operator_summary(quota)
    failure_summary = _first_failure_summary(task_summary)
    queue_state = "ready" if queue.get("ready") and queue.get("worker_online") else "blocked"
    latest_report_value = f"#{latest_report.get('id')}" if latest_report else "-"
    latest_report_caption = (
        f"{latest_report.get('topic') or latest_report.get('title') or '未命名報告'}"
        if latest_report
        else "尚無最新版報告"
    )
    return [
        {
            "title": "系統狀態",
            "value": "可送任務" if queue_state == "ready" else "需維護",
            "caption": "Worker 線上" if queue.get("worker_online") else "Worker 離線",
            "state": queue_state,
            "action_label": "查看維護" if queue_state == "blocked" else "開始使用",
            "route_hint": "settings:maintenance" if queue_state == "blocked" else "analysis",
        },
        {
            "title": "最新版報告",
            "value": latest_report_value,
            "caption": latest_report_caption,
            "state": "ready" if latest_report else "attention",
            "action_label": "讀報告" if latest_report else "建立分析",
            "route_hint": f"report:{latest_report.get('id')}" if latest_report else "analysis",
        },
        {
            "title": "AI 額度",
            "value": quota_summary["recommended_model"],
            "caption": f"{quota_summary['remaining']}｜{quota_summary['caption']}",
            "state": quota_summary["state"],
            "action_label": "查看額度",
            "route_hint": "settings:ai_quota",
        },
        {
            "title": "待處理事項",
            "value": failure_summary["label"],
            "caption": failure_summary["detail"],
            "state": failure_summary["state"],
            "action_label": failure_summary["action_label"],
            "route_hint": failure_summary["route_hint"],
        },
    ]


def quota_operator_summary(quota: dict) -> dict[str, str]:
    recommended = str(quota.get("recommended_model") or "-")
    recommended_row = _model_row(quota, recommended)
    remaining = _remaining_text(recommended_row)
    high_quota = next(
        (
            str(row.get("model"))
            for row in quota.get("models") or []
            if isinstance(row, dict) and row.get("routing_tier") == "high_quota_fallback"
        ),
        "",
    )
    status = str(recommended_row.get("status") or quota.get("recommended_status") or "unknown")
    return {
        "recommended_model": recommended,
        "remaining": remaining,
        "state": "ready" if status == "available" else "attention",
        "caption": f"高額度保底：{high_quota}" if high_quota else "無高額度保底模型",
    }


def task_failure_action_summary(failure: dict) -> dict[str, str]:
    category = str(failure.get("error_category") or "unknown")
    retryable = bool(failure.get("retryable"))
    task_id = str(failure.get("task_id") or "").strip()
    if category == "payload_validation":
        return {
            "state": "attention",
            "label": "輸入或白名單已擋下任務",
            "detail": "補強或重跑任務曾被 payload 驗證擋下；修正後可重試。",
            "action_label": "可重試" if retryable else "檢查輸入",
            "route_hint": f"task:{task_id}" if task_id else "settings:maintenance",
        }
    if category == "vector_store":
        return {
            "state": "attention",
            "label": "RAG 向量檢索曾降級",
            "detail": "報告仍可用關鍵字檢索降級完成；修復索引後可重送任務。",
            "action_label": "查看維護",
            "route_hint": "settings:maintenance",
        }
    if category == "runtime_storage":
        return {
            "state": "blocked",
            "label": "本機儲存曾失敗",
            "detail": "請確認報告目錄、SQLite 或備份目錄可讀寫。",
            "action_label": "查看維護",
            "route_hint": "settings:maintenance",
        }
    return {
        "state": "attention",
        "label": "有失敗任務",
        "detail": str(failure.get("next_action") or "請到維護頁查看任務細節。"),
        "action_label": "查看維護",
        "route_hint": f"task:{task_id}" if task_id else "settings:maintenance",
    }


def _first_failure_summary(task_summary: dict) -> dict[str, str]:
    for item in _recent_items(task_summary):
        if str(item.get("status") or "").lower() == "failed":
            return task_failure_action_summary(item)
    return {
        "state": "ready",
        "label": "無阻塞",
        "detail": "最近任務沒有需要立即處理的失敗。",
        "action_label": "繼續",
        "route_hint": "analysis",
    }


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _recent_items(task_summary: dict) -> list[dict]:
    return [item for item in task_summary.get("recent") or [] if isinstance(item, dict)]


def _first_report(reports: list[dict]) -> dict:
    for report in reports:
        if isinstance(report, dict):
            return report
    return {}


def _model_row(quota: dict, model_name: str) -> dict:
    for row in quota.get("models") or []:
        if isinstance(row, dict) and row.get("model") == model_name:
            return row
    return {}


def _remaining_text(model: dict) -> str:
    remaining = model.get("requests_remaining")
    budget = model.get("request_budget")
    if remaining in {None, ""} or budget in {None, ""}:
        return "額度未追蹤"
    return f"{int(remaining)} / {int(budget)}"
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_operator_status_ui.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add app/ui/operator_status.py tests/test_operator_status_ui.py
git commit -m "Add operator status summary helpers"
```

---

## Task 2: Latest Report Health Helpers

**Files:**
- Create: `app/ui/report_health.py`
- Create: `tests/test_report_health_ui.py`

- [ ] **Step 1: Write failing tests for report health summaries**

Add `tests/test_report_health_ui.py`:

```python
from __future__ import annotations

from app.ui.report_health import latest_report_health_summary


def test_latest_report_health_summary_uses_quality_gate_candidate_and_follow_up_state() -> None:
    result = latest_report_health_summary(
        {
            "report_id": 15,
            "topic": "記憶體產業鏈",
            "tickers": ["2408", "8150"],
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}},
            "candidate_whitelist": [
                {"ticker": "2408", "status": "evidence_supported"},
                {"ticker": "8150", "status": "evidence_supported"},
            ],
        },
        {
            "summary": {"required_count": 0, "tracking_count": 1},
            "status": "ready",
        },
    )

    assert result == {
        "state": "ready",
        "quality_label": "ready",
        "report_label": "#15｜記憶體產業鏈",
        "candidate_label": "候選 2｜正式 2",
        "follow_up_label": "可閱讀",
        "action_label": "閱讀最新版",
    }


def test_latest_report_health_summary_marks_required_gaps_as_attention() -> None:
    result = latest_report_health_summary(
        {
            "report_id": 12,
            "topic": "AI 產業鏈",
            "quality_gate": {"status": "caution", "metrics": {"promoted_count": 1}},
            "candidate_whitelist": [{"ticker": "2330"}],
        },
        {"summary": {"required_count": 2}, "status": "needs_follow_up"},
    )

    assert result["state"] == "attention"
    assert result["follow_up_label"] == "需補強 2 項"
    assert result["action_label"] == "補強資料"


def test_latest_report_health_summary_handles_empty_report() -> None:
    result = latest_report_health_summary({}, {})

    assert result == {
        "state": "attention",
        "quality_label": "-",
        "report_label": "尚未選擇報告",
        "candidate_label": "候選 0｜正式 0",
        "follow_up_label": "尚無狀態",
        "action_label": "建立分析",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_report_health_ui.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.ui.report_health'`.

- [ ] **Step 3: Implement `app/ui/report_health.py`**

Create `app/ui/report_health.py`:

```python
from __future__ import annotations

from typing import Any


def latest_report_health_summary(report_result: dict, follow_up_plan: dict | None = None) -> dict[str, str]:
    follow_up_plan = follow_up_plan or {}
    report_id = report_result.get("report_id")
    topic = str(report_result.get("topic") or "").strip()
    quality_gate = _dict_value(report_result.get("quality_gate"))
    metrics = _dict_value(quality_gate.get("metrics"))
    candidates = report_result.get("candidate_whitelist") or []
    promoted_count = int(metrics.get("promoted_count") or len(report_result.get("tickers") or []))
    candidate_count = len([item for item in candidates if isinstance(item, dict)])
    required_count = _required_follow_up_count(follow_up_plan)
    if not report_id:
        return {
            "state": "attention",
            "quality_label": "-",
            "report_label": "尚未選擇報告",
            "candidate_label": "候選 0｜正式 0",
            "follow_up_label": "尚無狀態",
            "action_label": "建立分析",
        }
    state = "attention" if required_count else "ready"
    follow_up_label = f"需補強 {required_count} 項" if required_count else "可閱讀"
    action_label = "補強資料" if required_count else "閱讀最新版"
    return {
        "state": state,
        "quality_label": str(quality_gate.get("status") or "-"),
        "report_label": f"#{report_id}｜{topic or '未命名主題'}",
        "candidate_label": f"候選 {candidate_count}｜正式 {promoted_count}",
        "follow_up_label": follow_up_label,
        "action_label": action_label,
    }


def _required_follow_up_count(follow_up_plan: dict) -> int:
    summary = _dict_value(follow_up_plan.get("summary"))
    selected = _dict_value(summary.get("selected"))
    value = selected.get("required_count", summary.get("required_count", 0))
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_report_health_ui.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add app/ui/report_health.py tests/test_report_health_ui.py
git commit -m "Add latest report health helpers"
```

---

## Task 3: Render Today Workbench on Analysis Page

**Files:**
- Modify: `app/ui/analysis_workspace.py`
- Modify: `tests/streamlit_ui_test_helpers.py`
- Modify: `tests/test_streamlit_ui_contract.py`

- [ ] **Step 1: Write failing contract assertions**

Modify `tests/streamlit_ui_test_helpers.py`:

```python
OPERATOR_STATUS_SOURCE = Path("app/ui/operator_status.py")
REPORT_HEALTH_SOURCE = Path("app/ui/report_health.py")
```

Add `OPERATOR_STATUS_SOURCE` and `REPORT_HEALTH_SOURCE` to `UI_SOURCE_FILES`.

Modify `tests/test_streamlit_ui_contract.py` inside `test_streamlit_shell_uses_operational_workspace_header`:

```python
    assert "from app.ui.operator_status import (" in source
    assert "operator_status_cards(" in source
    assert '"今日狀態"' in source
    assert '"/tasks/summary?days=7&limit=10"' in source
    assert '"/llm/quota"' in source
    assert '"/reports?limit=5"' in source
    assert "operator-status-grid" in combined
    assert "operator-status-card" in combined
```

- [ ] **Step 2: Run contract test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_streamlit_ui_contract.py::test_streamlit_shell_uses_operational_workspace_header -q
```

Expected: FAIL because `analysis_workspace.py` does not import `operator_status_cards` and CSS classes are missing.

- [ ] **Step 3: Render the status grid in `analysis_workspace.py`**

Add imports:

```python
from html import escape

from app.ui.operator_status import operator_status_cards, operator_status_overall
```

Add helper functions near the bottom of the file:

```python
def _render_operator_workbench() -> None:
    service_snapshot = load_api_json_or_default(
        "/services/status",
        {},
        error_message="讀取系統狀態失敗",
        notify="warning",
    )
    task_summary = load_api_json_or_default(
        "/tasks/summary?days=7&limit=10",
        {},
        error_message="讀取任務摘要失敗",
        notify="warning",
    )
    quota = load_api_json_or_default(
        "/llm/quota",
        {},
        error_message="讀取模型額度失敗",
        notify="warning",
    )
    reports = load_api_json_or_default(
        "/reports?limit=5",
        [],
        error_message="讀取最新版報告失敗",
        notify="warning",
    )
    if not isinstance(reports, list):
        reports = []
    overall = operator_status_overall(service_snapshot, task_summary, reports)
    cards = operator_status_cards(service_snapshot, task_summary, quota, reports)
    card_html = "\n".join(_operator_card_html(card) for card in cards)
    st.markdown(
        f"""
        <section class="operator-workbench" aria-label="今日狀態">
            <div class="operator-workbench-head">
                <div>
                    <div class="workspace-kicker">今日狀態</div>
                    <h2>{escape(overall["label"])}</h2>
                    <p>{escape(overall["detail"])}</p>
                </div>
                <span class="operator-state is-{escape(overall["state"])}">{escape(overall["state"])}</span>
            </div>
            <div class="operator-status-grid">
                {card_html}
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _operator_card_html(card: dict[str, str]) -> str:
    return f"""
    <article class="operator-status-card is-{escape(card.get("state", "attention"))}">
        <div class="operator-card-title">{escape(card.get("title", "-"))}</div>
        <div class="operator-card-value">{escape(card.get("value", "-"))}</div>
        <div class="operator-card-caption">{escape(card.get("caption", ""))}</div>
        <div class="operator-card-action">{escape(card.get("action_label", ""))}</div>
    </article>
    """
```

Call `_render_operator_workbench()` in `render_analysis_workspace()` immediately after the top hero markdown and before `render_section_header("建立一次分析", ...)`.

- [ ] **Step 4: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_operator_status_ui.py tests/test_streamlit_ui_contract.py::test_streamlit_shell_uses_operational_workspace_header -q
```

Expected: PASS after CSS is added in Task 5. If this step fails only because CSS classes are missing, keep the failure and proceed to Task 5 before committing Task 3.

- [ ] **Step 5: Commit Task 3 after Task 5 CSS exists**

Run after Task 5 passes:

```bash
git add app/ui/analysis_workspace.py tests/streamlit_ui_test_helpers.py tests/test_streamlit_ui_contract.py app/ui/styles/stock_dashboard.css
git commit -m "Render operator workbench summary"
```

---

## Task 4: Render Latest Report Health Strip

**Files:**
- Modify: `app/ui/report_center.py`
- Modify: `tests/test_streamlit_ui_contract.py`

- [ ] **Step 1: Write failing contract assertions**

Modify `tests/test_streamlit_ui_contract.py` inside `test_streamlit_shell_uses_operational_workspace_header`:

```python
    assert "from app.ui.report_health import latest_report_health_summary" in source
    assert "latest_report_health_summary(" in source
    assert "report-health-strip" in combined
    assert "report-health-card" in combined
```

- [ ] **Step 2: Run contract test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_streamlit_ui_contract.py::test_streamlit_shell_uses_operational_workspace_header -q
```

Expected: FAIL because the report center does not import or render report health.

- [ ] **Step 3: Render report health strip in `report_center.py`**

Add import:

```python
from html import escape

from app.ui.report_health import latest_report_health_summary
```

After `history_result` is built and before `history_html = report_html(...)`, load the follow-up plan and render:

```python
        follow_up_plan = load_api_json_or_default(
            f"/reports/{int(selected_id)}/follow-up/plan",
            {},
            error_message="讀取補強計畫失敗",
            notify="warning",
        )
        _render_report_health_strip(
            latest_report_health_summary(history_result or {}, follow_up_plan)
        )
```

Add helper:

```python
def _render_report_health_strip(summary: dict[str, str]) -> None:
    st.markdown(
        f"""
        <section class="report-health-strip is-{escape(summary.get("state", "attention"))}">
            <article class="report-health-card">
                <span>最新版</span>
                <strong>{escape(summary.get("report_label", "-"))}</strong>
            </article>
            <article class="report-health-card">
                <span>品質門檻</span>
                <strong>{escape(summary.get("quality_label", "-"))}</strong>
            </article>
            <article class="report-health-card">
                <span>股票範圍</span>
                <strong>{escape(summary.get("candidate_label", "-"))}</strong>
            </article>
            <article class="report-health-card">
                <span>補強狀態</span>
                <strong>{escape(summary.get("follow_up_label", "-"))}</strong>
            </article>
        </section>
        """,
        unsafe_allow_html=True,
    )
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_report_health_ui.py tests/test_streamlit_ui_contract.py::test_streamlit_shell_uses_operational_workspace_header -q
```

Expected: PASS after CSS exists in Task 5.

- [ ] **Step 5: Commit Task 4 after Task 5 CSS exists**

Run after Task 5 passes:

```bash
git add app/ui/report_center.py app/ui/report_health.py tests/test_report_health_ui.py tests/test_streamlit_ui_contract.py app/ui/styles/stock_dashboard.css
git commit -m "Show latest report health strip"
```

---

## Task 5: Data Enrichment Captions and Workbench CSS

**Files:**
- Modify: `app/ui/data_enrichment_market.py`
- Modify: `app/ui/styles/stock_dashboard.css`
- Modify: `tests/test_streamlit_ui_contract.py`

- [ ] **Step 1: Write failing contract assertions**

Modify `tests/test_streamlit_ui_contract.py`:

```python
    assert "會更新最新版報告的股價與成交量判讀" in source
    assert "會補齊五年財務與品質門檻需要的財報資料" in source
    assert "會更新本益比、股價淨值比與殖利率判讀" in source
    assert "會補齊公司文件、法說會或公開資訊缺口" in source
    assert "action-impact-grid" in combined
    assert "operator-workbench" in combined
```

- [ ] **Step 2: Run contract test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_streamlit_ui_contract.py::test_streamlit_shell_uses_operational_workspace_header -q
```

Expected: FAIL because captions and CSS classes are not present.

- [ ] **Step 3: Add report-impact captions in `data_enrichment_market.py`**

After the four refresh buttons, add:

```python
    st.markdown(
        """
        <div class="action-impact-grid" aria-label="資料補強影響">
            <div><strong>刷新股價</strong><span>會更新最新版報告的股價與成交量判讀</span></div>
            <div><strong>刷新 5 年財報</strong><span>會補齊五年財務與品質門檻需要的財報資料</span></div>
            <div><strong>刷新估值</strong><span>會更新本益比、股價淨值比與殖利率判讀</span></div>
            <div><strong>補抓公司文件</strong><span>會補齊公司文件、法說會或公開資訊缺口</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
```

- [ ] **Step 4: Add CSS classes to `stock_dashboard.css`**

Append near existing workspace styles:

```css
.operator-workbench,
.report-health-strip,
.action-impact-grid {
    margin: 18px 0;
}
.operator-workbench {
    background: var(--stock-surface);
    border: 1px solid var(--stock-border);
    border-radius: 8px;
    padding: 20px;
    box-shadow: var(--stock-shadow);
}
.operator-workbench-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 16px;
}
.operator-workbench-head h2 {
    margin: 0;
    font-size: 1.45rem;
}
.operator-workbench-head p {
    margin: 6px 0 0;
    color: var(--stock-muted);
}
.operator-state,
.operator-card-action {
    display: inline-flex;
    align-items: center;
    min-height: 28px;
    border-radius: 999px;
    padding: 3px 10px;
    font-weight: 700;
    border: 1px solid var(--stock-border);
}
.operator-state.is-ready,
.operator-status-card.is-ready .operator-card-action {
    color: var(--stock-accent);
    background: var(--stock-accent-soft);
    border-color: rgba(15, 118, 110, 0.25);
}
.operator-state.is-attention,
.operator-status-card.is-attention .operator-card-action {
    color: var(--stock-warning);
    background: var(--stock-warning-soft);
    border-color: rgba(146, 64, 14, 0.24);
}
.operator-state.is-blocked,
.operator-status-card.is-blocked .operator-card-action {
    color: var(--stock-danger);
    background: var(--stock-danger-soft);
    border-color: rgba(180, 35, 24, 0.24);
}
.operator-status-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
}
.operator-status-card,
.report-health-card,
.action-impact-grid > div {
    background: var(--stock-surface-alt);
    border: 1px solid var(--stock-border-soft);
    border-radius: 8px;
    padding: 14px;
}
.operator-card-title,
.report-health-card span,
.action-impact-grid span {
    color: var(--stock-muted);
    font-size: 0.9rem;
}
.operator-card-value,
.report-health-card strong,
.action-impact-grid strong {
    display: block;
    margin-top: 4px;
    color: var(--stock-text);
    font-weight: 800;
}
.operator-card-caption {
    margin: 8px 0 12px;
    color: var(--stock-muted);
    min-height: 42px;
}
.report-health-strip {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
}
.action-impact-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
}
.action-impact-grid span {
    display: block;
    margin-top: 4px;
}
@media (max-width: 900px) {
    .operator-workbench-head {
        flex-direction: column;
    }
    .operator-status-grid,
    .report-health-strip,
    .action-impact-grid {
        grid-template-columns: 1fr;
    }
}
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_streamlit_ui_contract.py tests/test_operator_status_ui.py tests/test_report_health_ui.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3, Task 4, and Task 5 UI rendering together if not already committed**

If Tasks 3 and 4 waited for CSS, commit all rendering files together:

```bash
git add app/ui/analysis_workspace.py app/ui/report_center.py app/ui/data_enrichment_market.py app/ui/styles/stock_dashboard.css tests/streamlit_ui_test_helpers.py tests/test_streamlit_ui_contract.py
git commit -m "Render operator workbench UI"
```

---

## Task 6: Verification and Browser QA

**Files:**
- No source files expected unless verification finds a defect.

- [ ] **Step 1: Run focused frontend tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_operator_status_ui.py tests/test_report_health_ui.py tests/test_streamlit_ui_contract.py tests/test_frontend_smoke.py tests/test_status_frontend.py -q
```

Expected: PASS.

- [ ] **Step 2: Run lint and compile checks**

Run:

```bash
.venv/bin/python -m ruff check app/ui tests/test_operator_status_ui.py tests/test_report_health_ui.py tests/test_streamlit_ui_contract.py
.venv/bin/python -m compileall app streamlit_app.py
```

Expected: both commands pass.

- [ ] **Step 3: Run full test suite**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS for the full suite.

- [ ] **Step 4: Run task submission smoke without consuming external data or model quota**

Run:

```bash
.venv/bin/python scripts/task_submission_smoke.py --submit --wait --json --strict
```

Expected: `"status": "passed"` and a successful no-op `market_refresh` task.

- [ ] **Step 5: Run frontend smoke**

Run:

```bash
.venv/bin/python scripts/frontend_smoke.py --streamlit-url http://127.0.0.1:8501 --api-url http://127.0.0.1:8000 --skip-browser --json
```

Expected: `"status": "passed"` with zero failed checks.

- [ ] **Step 6: Browser QA with the in-app browser**

Open:

```text
http://127.0.0.1:8501
```

Verify:

- First viewport contains `今日狀態`.
- First viewport contains four operator cards: `系統狀態`, `最新版報告`, `AI 額度`, `待處理事項`.
- The analysis form still appears below the workbench.
- Report center contains the report health strip above report content.
- Data enrichment contains the four report-impact captions.
- Desktop viewport has no incoherent overlap.
- Mobile-ish viewport stacks status cards in a single column.

- [ ] **Step 7: Commit verification fixes if needed**

If QA finds a defect, fix it with the smallest change and commit:

```bash
git add app/ui tests
git commit -m "Fix operator workbench QA findings"
```

If no defect is found, do not create an empty commit.

- [ ] **Step 8: Prepare release summary**

Collect:

```bash
git status --short --branch
git log --oneline -6
```

Expected:

- Working tree clean.
- Branch contains the spec commit, plan commit, and implementation commits.

---

## Self-Review

- Spec coverage:
  - Today workbench: Task 1 and Task 3.
  - Latest report health strip: Task 2 and Task 4.
  - Action-oriented failures: Task 1.
  - Quota summary: Task 1 and Task 3.
  - Data enrichment impact captions: Task 5.
  - CSS and responsive behavior: Task 5 and Task 6.
  - Background-task boundary and no quota-consuming UI calls: Task 3 and Task 6.

- Placeholder scan:
  - The plan contains concrete file paths, function names, code snippets, commands, and expected results.
  - No undefined helper is used in a later task without being created in an earlier task.

- Type consistency:
  - Operator cards consistently use `title`, `value`, `caption`, `state`, `action_label`, and `route_hint`.
  - Report health consistently uses `state`, `quality_label`, `report_label`, `candidate_label`, `follow_up_label`, and `action_label`.
