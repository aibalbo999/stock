# Operator Decision Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an operator decision layer that turns queue, task, quota, report, and follow-up state into a clear next action, report lifecycle, incident inbox, and data-gap action map.

**Architecture:** Add pure UI-presenter helper modules under `app/ui/` first, with no Streamlit imports and no network calls. Then connect those helpers to the existing Streamlit pages through lightweight render functions that reuse current FastAPI read endpoints and existing background-task submission controls.

**Tech Stack:** Python 3.12, Streamlit, pytest, ruff, existing FastAPI JSON endpoints, existing `app/ui/styles/stock_dashboard.css`.

---

## File Structure

- Create `app/ui/report_lifecycle.py`: pure helper that converts a selected report and follow-up plan into lifecycle stage cards and trust summary.
- Create `tests/test_report_lifecycle_ui.py`: focused lifecycle helper tests.
- Create `app/ui/incident_inbox.py`: pure helper that normalizes queue, stale task, task failure, quota, and report-quality signals into incidents.
- Create `tests/test_incident_inbox_ui.py`: focused incident inbox tests.
- Create `app/ui/operator_decisions.py`: pure helper that ranks state into one Next Best Action and a short secondary action list.
- Create `tests/test_operator_decisions_ui.py`: focused decision-ranking tests.
- Create `app/ui/data_gap_actions.py`: pure helper that maps follow-up next actions into operator-facing data enrichment actions.
- Create `tests/test_data_gap_actions_ui.py`: focused data-gap action map tests.
- Modify `app/ui/analysis_workspace.py`: load the latest report detail and follow-up plan for the homepage workbench, then render the primary recommendation and secondary actions.
- Modify `app/ui/report_center.py`: render the lifecycle strip above the existing latest-report health strip.
- Modify `app/ui/data_enrichment_market.py`: render latest report data-gap actions above the existing refresh buttons.
- Modify `app/ui/system_settings_maintenance.py`: render the incident inbox above background task observability.
- Modify `app/ui/styles/stock_dashboard.css`: add compact styles for the new operator decision surfaces.
- Modify `tests/streamlit_ui_test_helpers.py`: include the four new helper files in UI source contract reads.
- Modify `tests/test_streamlit_ui_contract.py`: lock imports, labels, CSS classes, and endpoint usage for the new surfaces.

## Implementation Tasks

### Task 1: Report Lifecycle Helper

**Files:**
- Create: `app/ui/report_lifecycle.py`
- Create: `tests/test_report_lifecycle_ui.py`

- [ ] **Step 1: Write the failing report lifecycle tests**

Create `tests/test_report_lifecycle_ui.py` with this content:

```python
from __future__ import annotations

from app.ui.report_lifecycle import latest_report_lifecycle, stage_by_key


def test_latest_report_lifecycle_marks_ready_report_readable() -> None:
    lifecycle = latest_report_lifecycle(
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
        {"summary": {"required_count": 0, "tracking_count": 1}, "status": "ready"},
    )

    assert lifecycle["overall_state"] == "ready"
    assert lifecycle["trust_label"] == "可閱讀"
    assert lifecycle["primary_action"] == "閱讀最新版"
    assert lifecycle["route_hint"] == "report:15"
    assert stage_by_key(lifecycle, "data")["state"] == "done"
    assert stage_by_key(lifecycle, "quality")["state"] == "done"
    assert stage_by_key(lifecycle, "readable")["label"] == "可閱讀"


def test_latest_report_lifecycle_blocks_zero_formal_tickers() -> None:
    lifecycle = latest_report_lifecycle(
        {
            "report_id": 18,
            "topic": "散熱產業鏈",
            "tickers": ["3017", "3324"],
            "quality_gate": {"status": "caution", "metrics": {"promoted_count": 0}},
            "candidate_whitelist": [{"ticker": "3017"}, {"ticker": "3324"}],
        },
        {"summary": {"required_count": 0}},
    )

    assert lifecycle["overall_state"] == "blocked"
    assert lifecycle["trust_label"] == "不可直接採信"
    assert lifecycle["primary_action"] == "補強資料"
    assert lifecycle["route_hint"] == "data_enrichment"
    assert stage_by_key(lifecycle, "quality")["state"] == "blocked"
    assert stage_by_key(lifecycle, "readable")["state"] == "blocked"


def test_latest_report_lifecycle_marks_required_gaps_as_attention() -> None:
    lifecycle = latest_report_lifecycle(
        {
            "report_id": 12,
            "topic": "AI 產業鏈",
            "quality_gate": {"status": "caution", "metrics": {"promoted_count": 1}},
            "candidate_whitelist": [{"ticker": "2330"}],
        },
        {"summary": {"required_count": 2}, "status": "needs_follow_up"},
    )

    assert lifecycle["overall_state"] == "attention"
    assert lifecycle["trust_label"] == "可閱讀但需註記"
    assert lifecycle["primary_action"] == "補強資料"
    assert stage_by_key(lifecycle, "data")["label"] == "缺口 2 項"
    assert stage_by_key(lifecycle, "follow_up")["state"] == "attention"
    assert stage_by_key(lifecycle, "rerun")["label"] == "補強後重跑"


def test_latest_report_lifecycle_marks_follow_up_running() -> None:
    lifecycle = latest_report_lifecycle(
        {
            "report_id": 21,
            "topic": "AI 伺服器供應鏈",
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 3}},
            "auto_follow_up": {"status": "queued"},
            "candidate_whitelist": [{"ticker": "2330"}, {"ticker": "2382"}, {"ticker": "6669"}],
        },
        {"summary": {"required_count": 1}, "status": "queued"},
    )

    assert lifecycle["overall_state"] == "running"
    assert lifecycle["trust_label"] == "補強中"
    assert lifecycle["primary_action"] == "查看補強任務"
    assert lifecycle["route_hint"] == "settings:maintenance"
    assert stage_by_key(lifecycle, "follow_up")["state"] == "running"
    assert stage_by_key(lifecycle, "rerun")["state"] == "running"


def test_latest_report_lifecycle_handles_empty_report() -> None:
    lifecycle = latest_report_lifecycle({}, {})

    assert lifecycle["overall_state"] == "attention"
    assert lifecycle["trust_label"] == "尚未有最新版報告"
    assert lifecycle["primary_action"] == "建立分析"
    assert lifecycle["route_hint"] == "analysis"
    assert stage_by_key(lifecycle, "data")["state"] == "unknown"
```

- [ ] **Step 2: Run the lifecycle tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_report_lifecycle_ui.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'app.ui.report_lifecycle'
```

- [ ] **Step 3: Implement `app/ui/report_lifecycle.py`**

Create `app/ui/report_lifecycle.py` with this content:

```python
from __future__ import annotations

from typing import Any


RUNNING_STATUSES = {"queued", "started", "running", "pending", "processing"}
BLOCKED_QUALITY_STATUSES = {"failed", "blocked", "error"}
ATTENTION_QUALITY_STATUSES = {"caution", "warning", "attention", "needs_follow_up"}


def latest_report_lifecycle(
    report_result: dict | None,
    follow_up_plan: dict | None = None,
) -> dict[str, Any]:
    report = _dict_value(report_result)
    plan = _dict_value(follow_up_plan)
    if not report:
        return {
            "overall_state": "attention",
            "trust_label": "尚未有最新版報告",
            "trust_explanation": "先建立分析報告，系統才有可閱讀版本。",
            "primary_action": "建立分析",
            "route_hint": "analysis",
            "report_id": None,
            "stage_cards": [
                _stage("data", "資料", "unknown", "尚無報告", "目前沒有可判讀的最新版報告。"),
                _stage("quality", "品質", "unknown", "尚無 Gate", "建立報告後才會有品質門檻結果。"),
                _stage("follow_up", "補強", "unknown", "尚無狀態", "目前沒有補強計畫。"),
                _stage("rerun", "重跑", "unknown", "尚無狀態", "目前沒有重跑建議。"),
                _stage("readable", "可讀", "unknown", "待建立", "建立報告後才會出現可讀版本。"),
            ],
        }

    report_id = report.get("report_id") or report.get("id")
    topic = _text(report.get("topic"), default="未命名報告")
    quality_gate = _dict_value(report.get("quality_gate"))
    quality_status = _text(quality_gate.get("status"), default="-").casefold()
    metrics = _dict_value(quality_gate.get("metrics"))
    promoted_count = _promoted_count(report, metrics)
    candidate_count = _candidate_count(report)
    required_count = _required_count(plan)
    follow_up_status = _follow_up_status(report, plan)
    running = follow_up_status in RUNNING_STATUSES
    has_rerun_report = _has_rerun_report(report)

    data_state = "attention" if required_count > 0 else "done"
    data_label = f"缺口 {required_count} 項" if required_count > 0 else "資料可用"
    data_detail = (
        "最新版報告仍有必補資料缺口，先補資料再重跑。"
        if required_count > 0
        else "未發現必補資料缺口。"
    )

    if promoted_count <= 0:
        quality_state = "blocked"
        quality_label = "正式分析 0 檔"
        quality_detail = "品質門檻沒有產生正式分析股票，報告不可直接採信。"
    elif quality_status in BLOCKED_QUALITY_STATUSES:
        quality_state = "blocked"
        quality_label = quality_status
        quality_detail = "品質門檻失敗，先處理阻塞原因。"
    elif quality_status in ATTENTION_QUALITY_STATUSES:
        quality_state = "attention"
        quality_label = "需留意"
        quality_detail = f"品質門檻為 {quality_status}，閱讀時需要保留警示。"
    else:
        quality_state = "done"
        quality_label = "品質可讀"
        quality_detail = "品質門檻可支援閱讀最新版報告。"

    if running:
        follow_up_state = "running"
        follow_up_label = "補強執行中"
        follow_up_detail = "補強任務已送出或正在執行，先到維護頁追蹤任務。"
    elif required_count > 0:
        follow_up_state = "attention"
        follow_up_label = "需補強"
        follow_up_detail = "有必補缺口，建議先完成資料補強。"
    else:
        follow_up_state = "done"
        follow_up_label = "無必補缺口"
        follow_up_detail = "目前沒有必要補強項目。"

    if running:
        rerun_state = "running"
        rerun_label = "等待補強完成"
        rerun_detail = "補強完成後再確認是否已有重跑報告。"
    elif required_count > 0:
        rerun_state = "attention"
        rerun_label = "補強後重跑"
        rerun_detail = "資料補完後建議重跑，讓最新版只保留最新結論。"
    elif has_rerun_report:
        rerun_state = "done"
        rerun_label = "已有重跑"
        rerun_detail = "補強後的重跑報告已記錄在最新版流程中。"
    else:
        rerun_state = "done"
        rerun_label = "不需重跑"
        rerun_detail = "目前沒有因必補缺口而需要重跑。"

    if quality_state == "blocked":
        readable_state = "blocked"
        readable_label = "不可採信"
        readable_detail = "先處理品質或資料問題，再閱讀投資結論。"
    elif required_count > 0 or quality_state == "attention":
        readable_state = "attention"
        readable_label = "可讀但需註記"
        readable_detail = "可先閱讀脈絡，但投資判讀需標示資料限制。"
    else:
        readable_state = "done"
        readable_label = "可閱讀"
        readable_detail = "這份報告可作為目前最新版閱讀。"

    stage_cards = [
        _stage("data", "資料", data_state, data_label, data_detail),
        _stage("quality", "品質", quality_state, quality_label, quality_detail),
        _stage("follow_up", "補強", follow_up_state, follow_up_label, follow_up_detail),
        _stage("rerun", "重跑", rerun_state, rerun_label, rerun_detail),
        _stage("readable", "可讀", readable_state, readable_label, readable_detail),
    ]
    overall_state = _overall_state(stage_cards)
    trust_label = _trust_label(overall_state)
    primary_action, route_hint = _primary_action(
        overall_state=overall_state,
        report_id=report_id,
        required_count=required_count,
        running=running,
    )
    return {
        "overall_state": overall_state,
        "trust_label": trust_label,
        "trust_explanation": _trust_explanation(
            overall_state,
            topic=topic,
            candidate_count=candidate_count,
            promoted_count=promoted_count,
            required_count=required_count,
        ),
        "primary_action": primary_action,
        "route_hint": route_hint,
        "report_id": report_id,
        "stage_cards": stage_cards,
    }


def stage_by_key(lifecycle: dict, key: str) -> dict:
    for stage in lifecycle.get("stage_cards") or []:
        if isinstance(stage, dict) and stage.get("key") == key:
            return stage
    return {}


def _stage(key: str, title: str, state: str, label: str, detail: str) -> dict[str, str]:
    return {
        "key": key,
        "title": title,
        "state": state,
        "label": label,
        "detail": detail,
    }


def _overall_state(stage_cards: list[dict[str, str]]) -> str:
    states = [stage["state"] for stage in stage_cards]
    if "blocked" in states:
        return "blocked"
    if "running" in states:
        return "running"
    if "attention" in states:
        return "attention"
    return "ready"


def _trust_label(overall_state: str) -> str:
    return {
        "ready": "可閱讀",
        "running": "補強中",
        "attention": "可閱讀但需註記",
        "blocked": "不可直接採信",
    }.get(overall_state, "需人工確認")


def _trust_explanation(
    overall_state: str,
    *,
    topic: str,
    candidate_count: int,
    promoted_count: int,
    required_count: int,
) -> str:
    if overall_state == "blocked":
        return f"{topic} 報告目前正式分析 {promoted_count} 檔，需先補強資料或品質門檻。"
    if overall_state == "running":
        return f"{topic} 報告正在補強，等待背景任務完成後再閱讀最新版。"
    if overall_state == "attention":
        return (
            f"{topic} 報告候選 {candidate_count} 檔、正式分析 {promoted_count} 檔，"
            f"仍有 {required_count} 項必補缺口。"
        )
    return f"{topic} 報告候選 {candidate_count} 檔、正式分析 {promoted_count} 檔，可作為最新版閱讀。"


def _primary_action(
    *,
    overall_state: str,
    report_id: Any,
    required_count: int,
    running: bool,
) -> tuple[str, str]:
    if running or overall_state == "running":
        return "查看補強任務", "settings:maintenance"
    if overall_state == "blocked" or required_count > 0:
        return "補強資料", "data_enrichment"
    if report_id is not None:
        return "閱讀最新版", f"report:{report_id}"
    return "建立分析", "analysis"


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value: Any, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _promoted_count(report: dict, metrics: dict) -> int:
    if "promoted_count" in metrics:
        return _int_value(metrics.get("promoted_count"))
    promoted = report.get("promoted_tickers")
    if isinstance(promoted, list):
        return len(promoted)
    return 0


def _candidate_count(report: dict) -> int:
    candidates = report.get("candidate_whitelist")
    if isinstance(candidates, list):
        return len(candidates)
    tickers = report.get("tickers")
    if isinstance(tickers, list):
        return len(tickers)
    return 0


def _required_count(plan: dict) -> int:
    summary = _dict_value(plan.get("summary"))
    return _int_value(summary.get("required_count"))


def _follow_up_status(report: dict, plan: dict) -> str:
    plan_status = _text(plan.get("status")).casefold()
    if plan_status:
        return plan_status
    auto_follow_up = _dict_value(report.get("auto_follow_up"))
    return _text(auto_follow_up.get("status")).casefold()


def _has_rerun_report(report: dict) -> bool:
    auto_follow_up = _dict_value(report.get("auto_follow_up"))
    return isinstance(auto_follow_up.get("rerun_report"), dict)
```

- [ ] **Step 4: Run the lifecycle tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_report_lifecycle_ui.py -q
```

Expected:

```text
5 passed
```

- [ ] **Step 5: Commit the lifecycle helper**

Run:

```bash
git add app/ui/report_lifecycle.py tests/test_report_lifecycle_ui.py
git commit -m "Add report lifecycle UI helper"
```

Expected:

```text
[main <hash>] Add report lifecycle UI helper
```

### Task 2: Incident Inbox Helper

**Files:**
- Create: `app/ui/incident_inbox.py`
- Create: `tests/test_incident_inbox_ui.py`

- [ ] **Step 1: Write the failing incident inbox tests**

Create `tests/test_incident_inbox_ui.py` with this content:

```python
from __future__ import annotations

from app.ui.incident_inbox import incident_counts, incident_inbox_items, top_incidents


def test_incident_inbox_reports_queue_unavailable() -> None:
    incidents = incident_inbox_items(
        {
            "task_queue": {
                "ready": False,
                "processing_ready": False,
                "worker_online": False,
            }
        },
        {"totals": {"stale_running_count": 0}},
        {"models": [], "recommended_model": None},
    )

    assert incidents[0]["severity"] == "critical"
    assert incidents[0]["category"] == "task_queue"
    assert incidents[0]["title"] == "背景任務未就緒"
    assert incidents[0]["route_hint"] == "settings:maintenance"


def test_incident_inbox_reports_stale_running_task() -> None:
    incidents = incident_inbox_items(
        {
            "task_queue": {
                "ready": True,
                "processing_ready": True,
                "worker_online": True,
            }
        },
        {"totals": {"stale_running_count": 2}},
        {"models": [], "recommended_model": None},
    )

    assert incidents[0]["severity"] == "critical"
    assert incidents[0]["title"] == "有 2 個任務疑似卡住"
    assert incidents[0]["dedupe_key"] == "task_queue:stale_running"


def test_incident_inbox_deduplicates_recent_failures() -> None:
    failure = {
        "task_id": "abc",
        "operation": "market_refresh",
        "status": "failed",
        "error_category": "payload_validation",
        "retryable": True,
        "finished_at": "2026-06-10T09:30:00",
    }
    incidents = incident_inbox_items(
        {
            "task_queue": {
                "ready": True,
                "processing_ready": True,
                "worker_online": True,
            }
        },
        {"recent_failures": [failure], "recent": [failure]},
        {"models": [], "recommended_model": None},
    )

    whitelist_incidents = [item for item in incidents if item["category"] == "whitelist"]
    assert len(whitelist_incidents) == 1
    assert whitelist_incidents[0]["title"] == "白名單或輸入擋下任務"
    assert whitelist_incidents[0]["retryable"] is True
    assert whitelist_incidents[0]["route_hint"] == "task:abc"


def test_incident_inbox_reports_quota_pressure() -> None:
    incidents = incident_inbox_items(
        {
            "task_queue": {
                "ready": True,
                "processing_ready": True,
                "worker_online": True,
            }
        },
        {},
        {
            "recommended_model": "gemini-3.5-flash",
            "models": [
                {
                    "model": "gemini-3.5-flash",
                    "state": "blocked",
                    "remaining": 0,
                    "limit": 1500,
                }
            ],
        },
    )

    assert incidents[0]["category"] == "quota"
    assert incidents[0]["severity"] == "warning"
    assert incidents[0]["title"] == "AI 額度需注意"
    assert incidents[0]["source"] == "gemini-3.5-flash"


def test_incident_inbox_reports_report_lifecycle_blocker() -> None:
    incidents = incident_inbox_items(
        {
            "task_queue": {
                "ready": True,
                "processing_ready": True,
                "worker_online": True,
            }
        },
        {},
        {},
        {
            "overall_state": "blocked",
            "trust_label": "不可直接採信",
            "trust_explanation": "正式分析 0 檔。",
            "primary_action": "補強資料",
            "route_hint": "data_enrichment",
            "report_id": 18,
        },
    )

    assert incidents[0]["category"] == "report_quality"
    assert incidents[0]["severity"] == "critical"
    assert incidents[0]["source"] == "report:18"
    assert incident_counts(incidents) == {"critical": 1, "warning": 0, "info": 0}


def test_top_incidents_limits_sorted_results() -> None:
    incidents = [
        {"id": "info", "severity": "info", "category": "quota", "retryable": False},
        {"id": "warning", "severity": "warning", "category": "whitelist", "retryable": True},
        {"id": "critical", "severity": "critical", "category": "task_queue", "retryable": False},
    ]

    assert [item["id"] for item in top_incidents(incidents, limit=2)] == [
        "critical",
        "warning",
    ]
```

- [ ] **Step 2: Run the incident tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_incident_inbox_ui.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'app.ui.incident_inbox'
```

- [ ] **Step 3: Implement `app/ui/incident_inbox.py`**

Create `app/ui/incident_inbox.py` with this content:

```python
from __future__ import annotations

from typing import Any

from app.ui.operator_status import quota_operator_summary


SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
CATEGORY_ORDER = {
    "task_queue": 0,
    "report_quality": 1,
    "whitelist": 2,
    "data_source": 3,
    "vector_store": 4,
    "runtime_storage": 5,
    "quota": 6,
    "unknown": 7,
}
FAILURE_CATEGORY_MAP = {
    "payload_validation": "whitelist",
    "data_source": "data_source",
    "vector_store": "vector_store",
    "runtime_storage": "runtime_storage",
}


def incident_inbox_items(
    service_snapshot: dict | None,
    task_summary: dict | None,
    quota: dict | None = None,
    report_lifecycle: dict | None = None,
) -> list[dict[str, Any]]:
    incidents: list[dict[str, Any]] = []
    service = _dict_value(service_snapshot)
    summary = _dict_value(task_summary)
    task_queue = _dict_value(service.get("task_queue"))
    totals = _dict_value(summary.get("totals"))

    if not _queue_ready(task_queue):
        incidents.append(
            {
                "id": "task_queue_unavailable",
                "severity": "critical",
                "category": "task_queue",
                "title": "背景任務未就緒",
                "impact": "分析、補強與資料刷新可能無法完成。",
                "next_action": "到維護頁檢查 Redis/Celery worker。",
                "route_hint": "settings:maintenance",
                "retryable": False,
                "source": "task_queue",
                "created_at": "",
                "dedupe_key": "task_queue:unavailable",
            }
        )

    stale_count = _int_value(totals.get("stale_running_count"))
    if stale_count > 0:
        incidents.append(
            {
                "id": "task_queue_stale_running",
                "severity": "critical",
                "category": "task_queue",
                "title": f"有 {stale_count} 個任務疑似卡住",
                "impact": "新的補強或報告任務可能排隊等待過久。",
                "next_action": "到維護頁查看任務狀態並重試可重試任務。",
                "route_hint": "settings:maintenance",
                "retryable": False,
                "source": "task_queue",
                "created_at": "",
                "dedupe_key": "task_queue:stale_running",
            }
        )

    incidents.extend(_task_alert_incidents(summary))
    incidents.extend(_failure_incidents(summary))
    quota_incident = _quota_incident(_dict_value(quota))
    if quota_incident:
        incidents.append(quota_incident)
    lifecycle_incident = _report_lifecycle_incident(_dict_value(report_lifecycle))
    if lifecycle_incident:
        incidents.append(lifecycle_incident)

    return top_incidents(_dedupe_incidents(incidents), limit=50)


def top_incidents(incidents: list[dict], limit: int = 3) -> list[dict]:
    return sorted(incidents, key=_incident_sort_key)[:limit]


def incident_counts(incidents: list[dict]) -> dict[str, int]:
    return {
        "critical": sum(1 for incident in incidents if incident.get("severity") == "critical"),
        "warning": sum(1 for incident in incidents if incident.get("severity") == "warning"),
        "info": sum(1 for incident in incidents if incident.get("severity") == "info"),
    }


def _task_alert_incidents(task_summary: dict) -> list[dict[str, Any]]:
    incidents: list[dict[str, Any]] = []
    for index, alert in enumerate(_list_value(task_summary.get("alerts"))):
        severity = "critical" if alert.get("severity") == "error" else "warning"
        code = _text(alert.get("code"), default=f"alert_{index}")
        message = _text(alert.get("message"), default=code)
        next_steps = [str(step) for step in _list_value(alert.get("next_steps")) if str(step).strip()]
        incidents.append(
            {
                "id": f"task_alert_{code}",
                "severity": severity,
                "category": "task_queue",
                "title": message,
                "impact": "背景任務觀測已回報異常。",
                "next_action": "；".join(next_steps) if next_steps else "到維護頁查看背景任務觀測。",
                "route_hint": "settings:maintenance",
                "retryable": False,
                "source": code,
                "created_at": "",
                "dedupe_key": f"task_alert:{code}",
            }
        )
    return incidents


def _failure_incidents(task_summary: dict) -> list[dict[str, Any]]:
    incidents = []
    for failure in _recent_failures(task_summary):
        category = _failure_category(failure)
        task_id = _text(failure.get("task_id"))
        operation = _text(failure.get("operation"), default="task")
        retryable = bool(failure.get("retryable"))
        incidents.append(
            {
                "id": f"failure_{task_id or operation}_{category}",
                "severity": "critical" if category == "runtime_storage" else "warning",
                "category": category,
                "title": _failure_title(category),
                "impact": _failure_impact(category),
                "next_action": _failure_next_action(category, retryable),
                "route_hint": f"task:{task_id}" if task_id else "settings:maintenance",
                "retryable": retryable,
                "source": task_id or operation,
                "created_at": _text(failure.get("finished_at") or failure.get("created_at")),
                "dedupe_key": f"failure:{category}:{task_id or operation}",
            }
        )
    return incidents


def _quota_incident(quota: dict) -> dict[str, Any] | None:
    if not quota:
        return None
    summary = quota_operator_summary(quota)
    if summary.get("state") == "ready":
        return None
    model = summary.get("recommended_model") or "-"
    return {
        "id": f"quota_{model}",
        "severity": "warning",
        "category": "quota",
        "title": "AI 額度需注意",
        "impact": f"目前建議模型 {model} 額度狀態為 {summary.get('remaining') or '-'}。",
        "next_action": "查看額度頁，等待重置或確認 fallback 模型。",
        "route_hint": "settings:ai_quota",
        "retryable": False,
        "source": model,
        "created_at": "",
        "dedupe_key": f"quota:{model}",
    }


def _report_lifecycle_incident(lifecycle: dict) -> dict[str, Any] | None:
    state = _text(lifecycle.get("overall_state"))
    if state not in {"blocked", "attention"}:
        return None
    report_id = lifecycle.get("report_id")
    source = f"report:{report_id}" if report_id is not None else "report"
    return {
        "id": f"report_quality_{report_id or 'latest'}",
        "severity": "critical" if state == "blocked" else "warning",
        "category": "report_quality",
        "title": lifecycle.get("trust_label") or "報告品質需確認",
        "impact": lifecycle.get("trust_explanation") or "最新版報告需要人工確認。",
        "next_action": lifecycle.get("primary_action") or "查看報告中心",
        "route_hint": lifecycle.get("route_hint") or "report_center",
        "retryable": False,
        "source": source,
        "created_at": "",
        "dedupe_key": f"report_quality:{source}:{state}",
    }


def _recent_failures(task_summary: dict) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for collection_key in ("recent_failures", "recent"):
        for row in _list_value(task_summary.get(collection_key)):
            if not _is_failed_task(row):
                continue
            identity = _failure_identity(row)
            if identity in seen:
                continue
            seen.add(identity)
            rows.append(row)
    return rows


def _is_failed_task(row: dict) -> bool:
    status = _text(row.get("status")).casefold()
    celery_status = _text(row.get("celery_status")).casefold()
    return status in {"failed", "failure", "cancelled", "error"} or celery_status == "failure"


def _failure_identity(row: dict) -> str:
    return _text(row.get("task_id")) or ":".join(
        [
            _text(row.get("operation"), default="task"),
            _text(row.get("error_category"), default="unknown"),
            _text(row.get("finished_at") or row.get("created_at")),
        ]
    )


def _failure_category(failure: dict) -> str:
    raw_category = _text(failure.get("error_category"), default="unknown")
    return FAILURE_CATEGORY_MAP.get(raw_category, raw_category if raw_category else "unknown")


def _failure_title(category: str) -> str:
    return {
        "whitelist": "白名單或輸入擋下任務",
        "data_source": "資料來源抓取失敗",
        "vector_store": "RAG 向量檢索曾降級",
        "runtime_storage": "本機儲存失敗",
    }.get(category, "有失敗任務")


def _failure_impact(category: str) -> str:
    return {
        "whitelist": "補強或重跑沒有進入有效資料流程。",
        "data_source": "最新版報告可能缺少最新市場或公司資料。",
        "vector_store": "報告可降級完成，但檢索覆蓋率較低。",
        "runtime_storage": "報告檔案、SQLite 或備份可能沒有寫入成功。",
    }.get(category, "近期任務失敗，需查看維護頁。")


def _failure_next_action(category: str, retryable: bool) -> str:
    if category == "whitelist":
        return "修正輸入後重試" if retryable else "檢查輸入與白名單"
    if retryable:
        return "到維護頁重試此任務"
    return "到維護頁查看失敗診斷"


def _dedupe_incidents(incidents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for incident in incidents:
        key = _text(incident.get("dedupe_key"), default=_text(incident.get("id")))
        current = selected.get(key)
        if current is None or _incident_sort_key(incident) < _incident_sort_key(current):
            selected[key] = incident
    return list(selected.values())


def _incident_sort_key(incident: dict) -> tuple[int, int, int, str]:
    severity = SEVERITY_ORDER.get(_text(incident.get("severity")), 9)
    category = CATEGORY_ORDER.get(_text(incident.get("category")), 9)
    retry_rank = 0 if incident.get("retryable") else 1
    created_at = _text(incident.get("created_at"))
    return (severity, category, retry_rank, created_at)


def _queue_ready(task_queue: dict) -> bool:
    return bool(
        task_queue.get("ready")
        and task_queue.get("processing_ready")
        and task_queue.get("worker_online")
    )


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _text(value: Any, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
```

- [ ] **Step 4: Run the incident tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_incident_inbox_ui.py -q
```

Expected:

```text
6 passed
```

- [ ] **Step 5: Commit the incident inbox helper**

Run:

```bash
git add app/ui/incident_inbox.py tests/test_incident_inbox_ui.py
git commit -m "Add operator incident inbox helper"
```

Expected:

```text
[main <hash>] Add operator incident inbox helper
```

### Task 3: Operator Decision Helper

**Files:**
- Create: `app/ui/operator_decisions.py`
- Create: `tests/test_operator_decisions_ui.py`

- [ ] **Step 1: Write the failing operator decision tests**

Create `tests/test_operator_decisions_ui.py` with this content:

```python
from __future__ import annotations

from app.ui.operator_decisions import operator_next_best_action, operator_secondary_actions


READY_QUEUE = {"task_queue": {"ready": True, "processing_ready": True, "worker_online": True}}


def test_operator_next_action_prioritizes_queue_blocker() -> None:
    action = operator_next_best_action(
        {"task_queue": {"ready": False, "processing_ready": False, "worker_online": False}},
        {},
        {},
        [{"id": 15, "title": "AI 產業鏈"}],
        {"report_id": 15, "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}}},
        {"summary": {"required_count": 0}},
    )

    assert action["state"] == "blocked"
    assert action["title"] == "先修復背景任務"
    assert action["action_label"] == "查看維護"
    assert action["route_hint"] == "settings:maintenance"


def test_operator_next_action_prompts_report_creation_when_missing() -> None:
    action = operator_next_best_action(READY_QUEUE, {}, {}, [], {}, {})

    assert action["state"] == "attention"
    assert action["title"] == "先建立最新版報告"
    assert action["action_label"] == "建立分析"
    assert action["route_hint"] == "analysis"


def test_operator_next_action_prioritizes_zero_formal_tickers() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {},
        {},
        [{"id": 18, "title": "散熱產業鏈"}],
        {
            "report_id": 18,
            "topic": "散熱產業鏈",
            "quality_gate": {"status": "caution", "metrics": {"promoted_count": 0}},
            "candidate_whitelist": [{"ticker": "3017"}],
        },
        {"summary": {"required_count": 0}},
    )

    assert action["state"] == "blocked"
    assert action["title"] == "先確認報告可信度"
    assert action["reason"] == "最新版報告目前不可直接採信。"
    assert action["action_label"] == "查看報告生命週期"
    assert action["route_hint"] == "report:18"


def test_operator_next_action_prioritizes_required_data_gaps() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {},
        {},
        [{"id": 12, "title": "AI 產業鏈"}],
        {
            "report_id": 12,
            "topic": "AI 產業鏈",
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}},
            "candidate_whitelist": [{"ticker": "2330"}, {"ticker": "2382"}],
        },
        {"summary": {"required_count": 2}, "status": "needs_follow_up"},
    )

    assert action["state"] == "attention"
    assert action["title"] == "先補強最新版報告資料"
    assert action["action_label"] == "補強資料"
    assert action["route_hint"] == "data_enrichment"


def test_operator_next_action_surfaces_quota_pressure_after_report_gates() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {},
        {
            "recommended_model": "gemini-3.5-flash",
            "models": [{"model": "gemini-3.5-flash", "state": "blocked", "remaining": 0}],
        },
        [{"id": 15, "title": "AI 產業鏈"}],
        {
            "report_id": 15,
            "topic": "AI 產業鏈",
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}},
            "candidate_whitelist": [{"ticker": "2330"}, {"ticker": "2382"}],
        },
        {"summary": {"required_count": 0}},
    )

    assert action["state"] == "attention"
    assert action["title"] == "等待額度或查看 fallback"
    assert action["action_label"] == "查看額度"
    assert action["route_hint"] == "settings:ai_quota"


def test_operator_next_action_reads_latest_when_healthy() -> None:
    action = operator_next_best_action(
        READY_QUEUE,
        {},
        {},
        [{"id": 15, "title": "AI 產業鏈"}],
        {
            "report_id": 15,
            "topic": "AI 產業鏈",
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}},
            "candidate_whitelist": [{"ticker": "2330"}, {"ticker": "2382"}],
        },
        {"summary": {"required_count": 0}},
    )

    assert action["state"] == "ready"
    assert action["title"] == "閱讀最新版報告"
    assert action["action_label"] == "讀報告"
    assert action["route_hint"] == "report:15"


def test_operator_secondary_actions_show_ranked_incidents() -> None:
    actions = operator_secondary_actions(
        READY_QUEUE,
        {
            "recent_failures": [
                {
                    "task_id": "abc",
                    "operation": "market_refresh",
                    "status": "failed",
                    "error_category": "payload_validation",
                    "retryable": True,
                }
            ]
        },
        {},
        [{"id": 15, "title": "AI 產業鏈"}],
        {
            "report_id": 15,
            "topic": "AI 產業鏈",
            "quality_gate": {"status": "ready", "metrics": {"promoted_count": 2}},
            "candidate_whitelist": [{"ticker": "2330"}, {"ticker": "2382"}],
        },
        {"summary": {"required_count": 0}},
    )

    assert actions[0]["title"] == "白名單或輸入擋下任務"
    assert actions[0]["route_hint"] == "task:abc"
```

- [ ] **Step 2: Run the operator decision tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_operator_decisions_ui.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'app.ui.operator_decisions'
```

- [ ] **Step 3: Implement `app/ui/operator_decisions.py`**

Create `app/ui/operator_decisions.py` with this content:

```python
from __future__ import annotations

from typing import Any

from app.ui.incident_inbox import incident_inbox_items, top_incidents
from app.ui.operator_status import quota_operator_summary
from app.ui.report_lifecycle import latest_report_lifecycle, stage_by_key


def operator_next_best_action(
    service_snapshot: dict | None,
    task_summary: dict | None,
    quota: dict | None,
    reports: list[dict] | None,
    report_result: dict | None = None,
    follow_up_plan: dict | None = None,
) -> dict[str, Any]:
    latest_report = _latest_report(reports)
    report_payload = _dict_value(report_result) or latest_report
    lifecycle = latest_report_lifecycle(report_payload, follow_up_plan)
    incidents = incident_inbox_items(service_snapshot, task_summary, quota, lifecycle)
    queue_incident = _first_incident(incidents, "task_queue", severity="critical")
    if queue_incident:
        return _action(
            state="blocked",
            priority=1,
            title="先修復背景任務",
            reason=queue_incident["impact"],
            risk="未修復前，分析、補強與資料刷新可能卡住。",
            impact="恢復所有背景任務提交與處理能力。",
            action_label="查看維護",
            route_hint="settings:maintenance",
            source_ids=[queue_incident["source"]],
        )

    if not latest_report and not report_payload:
        return _action(
            state="attention",
            priority=3,
            title="先建立最新版報告",
            reason="目前沒有可閱讀的最新版報告。",
            risk="沒有報告時，資料補強與維護訊號缺少投資脈絡。",
            impact="建立第一份可追蹤的分析基準。",
            action_label="建立分析",
            route_hint="analysis",
            source_ids=[],
        )

    report_id = lifecycle.get("report_id") or latest_report.get("id")
    quality_stage = stage_by_key(lifecycle, "quality")
    if lifecycle.get("overall_state") == "blocked" and quality_stage.get("state") == "blocked":
        return _action(
            state="blocked",
            priority=5,
            title="先確認報告可信度",
            reason="最新版報告目前不可直接採信。",
            risk="直接閱讀可能把候選不足或正式分析 0 檔誤判為投資結論。",
            impact="確認品質阻塞點，再決定補資料或重新分析。",
            action_label="查看報告生命週期",
            route_hint=f"report:{report_id}" if report_id is not None else "report_center",
            source_ids=[f"report:{report_id}"] if report_id is not None else [],
        )

    data_stage = stage_by_key(lifecycle, "data")
    if data_stage.get("state") == "attention":
        return _action(
            state="attention",
            priority=4,
            title="先補強最新版報告資料",
            reason=data_stage.get("detail") or "最新版報告仍有必要資料缺口。",
            risk="未補強前，報告結論需要保留資料限制。",
            impact="補齊股價、財務、估值或公司文件後重跑最新版報告。",
            action_label="補強資料",
            route_hint="data_enrichment",
            source_ids=[f"report:{report_id}"] if report_id is not None else [],
        )

    if lifecycle.get("overall_state") == "running":
        return _action(
            state="attention",
            priority=6,
            title="等待補強完成",
            reason="補強或重跑任務正在背景執行。",
            risk="任務完成前閱讀可能不是最新結論。",
            impact="確認任務完成後，只保留最新報告版本。",
            action_label="查看補強任務",
            route_hint="settings:maintenance",
            source_ids=[f"report:{report_id}"] if report_id is not None else [],
        )

    quota_summary = quota_operator_summary(_dict_value(quota))
    if quota_summary.get("state") != "ready":
        return _action(
            state="attention",
            priority=8,
            title="等待額度或查看 fallback",
            reason=f"目前建議模型 {quota_summary.get('recommended_model') or '-'} 額度不足或不可用。",
            risk="立即送出深度分析可能降級、排隊或失敗。",
            impact="確認模型 fallback 後再送出高成本任務。",
            action_label="查看額度",
            route_hint="settings:ai_quota",
            source_ids=[quota_summary.get("recommended_model") or "-"],
        )

    return _action(
        state="ready",
        priority=10,
        title="閱讀最新版報告",
        reason="背景任務、品質門檻與必補資料缺口都沒有阻塞。",
        risk="仍需把報告視為研究輔助，不是買賣指令。",
        impact="直接閱讀目前系統保留的最新版結論。",
        action_label="讀報告",
        route_hint=f"report:{report_id}" if report_id is not None else "report_center",
        source_ids=[f"report:{report_id}"] if report_id is not None else [],
    )


def operator_secondary_actions(
    service_snapshot: dict | None,
    task_summary: dict | None,
    quota: dict | None,
    reports: list[dict] | None,
    report_result: dict | None = None,
    follow_up_plan: dict | None = None,
) -> list[dict[str, Any]]:
    latest_report = _latest_report(reports)
    report_payload = _dict_value(report_result) or latest_report
    lifecycle = latest_report_lifecycle(report_payload, follow_up_plan)
    incidents = top_incidents(
        incident_inbox_items(service_snapshot, task_summary, quota, lifecycle),
        limit=3,
    )
    secondary = [
        {
            "title": incident["title"],
            "detail": incident["next_action"],
            "state": _incident_state(incident),
            "route_hint": incident["route_hint"],
        }
        for incident in incidents
    ]
    report_id = lifecycle.get("report_id") or latest_report.get("id")
    if report_id is not None:
        secondary.append(
            {
                "title": "查看報告生命週期",
                "detail": lifecycle.get("trust_label") or "確認最新版報告狀態",
                "state": lifecycle.get("overall_state") or "attention",
                "route_hint": f"report:{report_id}",
            }
        )
    secondary.append(
        {
            "title": "資料缺口行動地圖",
            "detail": "查看目前補資料動作能改善哪些報告缺口。",
            "state": "attention",
            "route_hint": "data_enrichment",
        }
    )
    return _dedupe_secondary_actions(secondary)[:3]


def _action(
    *,
    state: str,
    priority: int,
    title: str,
    reason: str,
    risk: str,
    impact: str,
    action_label: str,
    route_hint: str,
    source_ids: list[Any],
) -> dict[str, Any]:
    return {
        "state": state,
        "priority": priority,
        "title": title,
        "reason": reason,
        "risk": risk,
        "impact": impact,
        "action_label": action_label,
        "route_hint": route_hint,
        "source_ids": [str(source_id) for source_id in source_ids if str(source_id).strip()],
    }


def _first_incident(
    incidents: list[dict],
    category: str,
    *,
    severity: str | None = None,
) -> dict:
    for incident in incidents:
        if incident.get("category") != category:
            continue
        if severity is not None and incident.get("severity") != severity:
            continue
        return incident
    return {}


def _incident_state(incident: dict) -> str:
    if incident.get("severity") == "critical":
        return "blocked"
    if incident.get("severity") == "warning":
        return "attention"
    return "ready"


def _dedupe_secondary_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = []
    seen = set()
    for action in actions:
        key = (action.get("title"), action.get("route_hint"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped


def _latest_report(reports: list[dict] | None) -> dict:
    if not isinstance(reports, list):
        return {}
    for report in reports:
        if isinstance(report, dict):
            return report
    return {}


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}
```

- [ ] **Step 4: Run the operator decision tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_operator_decisions_ui.py -q
```

Expected:

```text
7 passed
```

- [ ] **Step 5: Commit the operator decision helper**

Run:

```bash
git add app/ui/operator_decisions.py tests/test_operator_decisions_ui.py
git commit -m "Add operator next action helper"
```

Expected:

```text
[main <hash>] Add operator next action helper
```

### Task 4: Data Gap Action Map Helper

**Files:**
- Create: `app/ui/data_gap_actions.py`
- Create: `tests/test_data_gap_actions_ui.py`

- [ ] **Step 1: Write the failing data gap action tests**

Create `tests/test_data_gap_actions_ui.py` with this content:

```python
from __future__ import annotations

from app.ui.data_gap_actions import data_gap_action_items, data_gap_action_summary


def test_data_gap_action_items_map_follow_up_next_actions() -> None:
    items = data_gap_action_items(
        {"report_id": 12, "topic": "AI 產業鏈"},
        {
            "request": {"topic": "AI 產業鏈", "tickers": ["2330", "2382"]},
            "next_actions": [
                {
                    "action": "refresh_market",
                    "tickers": ["2330"],
                    "target": "股價與量能",
                    "priority": "required",
                    "purpose": "required",
                    "reason": "缺少最新股價",
                    "next_step": "刷新股價",
                },
                {
                    "action": "ingest_company_filings",
                    "tickers": ["2382"],
                    "target": "公司公開文件",
                    "priority": "required",
                    "purpose": "required",
                    "reason": "缺少法說會簡報",
                    "next_step": "補抓公司文件",
                },
                {
                    "action": "rerun_analysis",
                    "tickers": ["2330", "2382"],
                    "target": "完整投資報告",
                    "priority": "required",
                    "purpose": "required",
                    "reason": "補強後重跑",
                    "next_step": "重跑報告",
                },
            ],
        },
    )

    assert [item["operation"] for item in items] == [
        "market_refresh",
        "company_filings_fetch",
        "report_follow_up",
    ]
    assert items[0]["gap_type"] == "price"
    assert items[0]["route_hint"] == "data_enrichment:market"
    assert items[1]["action_label"] == "補抓公司文件"
    assert items[2]["post_action_hint"] == "補強完成後重跑報告"


def test_data_gap_action_items_return_empty_without_gaps() -> None:
    assert data_gap_action_items({"report_id": 15}, {"next_actions": []}) == []
    assert data_gap_action_summary([]) == {
        "state": "ready",
        "label": "目前沒有必要資料缺口",
        "detail": "最新版報告沒有必補資料行動。",
    }


def test_data_gap_action_summary_counts_required_actions() -> None:
    items = data_gap_action_items(
        {"report_id": 12, "topic": "AI 產業鏈"},
        {
            "next_actions": [
                {"action": "refresh_financial_metrics", "tickers": ["2330"], "purpose": "required"},
                {"action": "refresh_valuations", "tickers": ["2330"], "purpose": "tracking"},
            ]
        },
    )

    assert data_gap_action_summary(items) == {
        "state": "attention",
        "label": "必補 1 項｜追蹤 1 項",
        "detail": "先處理必補資料，再重跑最新版報告。",
    }
```

- [ ] **Step 2: Run the data gap tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_data_gap_actions_ui.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'app.ui.data_gap_actions'
```

- [ ] **Step 3: Implement `app/ui/data_gap_actions.py`**

Create `app/ui/data_gap_actions.py` with this content:

```python
from __future__ import annotations

from typing import Any


ACTION_OPERATION_MAP = {
    "refresh_market": {
        "gap_type": "price",
        "action_label": "刷新股價",
        "operation": "market_refresh",
        "route_hint": "data_enrichment:market",
    },
    "refresh_financial_metrics": {
        "gap_type": "financials",
        "action_label": "刷新 5 年財報",
        "operation": "fundamentals_refresh",
        "route_hint": "data_enrichment:market",
    },
    "refresh_monthly_revenue": {
        "gap_type": "financials",
        "action_label": "刷新月營收",
        "operation": "fundamentals_refresh",
        "route_hint": "data_enrichment:market",
    },
    "refresh_valuations": {
        "gap_type": "valuation",
        "action_label": "刷新估值",
        "operation": "valuation_refresh",
        "route_hint": "data_enrichment:market",
    },
    "ingest_company_filings": {
        "gap_type": "filing",
        "action_label": "補抓公司文件",
        "operation": "company_filings_fetch",
        "route_hint": "data_enrichment:market",
    },
    "ingest_news": {
        "gap_type": "news",
        "action_label": "匯入新聞/研究摘要",
        "operation": "manual_ingest",
        "route_hint": "data_enrichment:manual",
    },
    "rerun_analysis": {
        "gap_type": "rag",
        "action_label": "補強後重跑報告",
        "operation": "report_follow_up",
        "route_hint": "report_center",
    },
}


def data_gap_action_items(
    report_result: dict | None,
    follow_up_plan: dict | None,
) -> list[dict[str, Any]]:
    report = _dict_value(report_result)
    plan = _dict_value(follow_up_plan)
    request = _dict_value(plan.get("request"))
    report_id = report.get("report_id") or report.get("id") or plan.get("report_id")
    topic = report.get("topic") or request.get("topic") or "最新版報告"
    items = []
    for row in _list_value(plan.get("next_actions")):
        action = _text(row.get("action"))
        metadata = ACTION_OPERATION_MAP.get(action)
        if not metadata:
            continue
        tickers = _tickers(row, request)
        route_hint = metadata["route_hint"]
        if action == "rerun_analysis" and report_id is not None:
            route_hint = f"report:{report_id}"
        items.append(
            {
                "report_id": report_id,
                "topic": topic,
                "ticker": "、".join(tickers) if tickers else "全部",
                "tickers": tickers,
                "gap_type": metadata["gap_type"],
                "action_label": metadata["action_label"],
                "operation": metadata["operation"],
                "impact": _impact(row, metadata["action_label"]),
                "post_action_hint": _post_action_hint(action),
                "route_hint": route_hint,
                "purpose": _text(row.get("purpose") or row.get("priority"), default="tracking"),
                "priority": _text(row.get("priority") or row.get("purpose"), default="tracking"),
            }
        )
    return _dedupe_items(items)


def data_gap_action_summary(items: list[dict]) -> dict[str, str]:
    if not items:
        return {
            "state": "ready",
            "label": "目前沒有必要資料缺口",
            "detail": "最新版報告沒有必補資料行動。",
        }
    required_count = sum(1 for item in items if item.get("purpose") == "required")
    tracking_count = len(items) - required_count
    return {
        "state": "attention" if required_count else "ready",
        "label": f"必補 {required_count} 項｜追蹤 {tracking_count} 項",
        "detail": "先處理必補資料，再重跑最新版報告。"
        if required_count
        else "目前只有追蹤型資料更新，可排在主要閱讀流程之後。",
    }


def _impact(row: dict, action_label: str) -> str:
    target = _text(row.get("target"))
    reason = _text(row.get("reason"))
    if target and reason:
        return f"{action_label}可改善「{target}」：{reason}"
    if target:
        return f"{action_label}可改善「{target}」。"
    return _text(row.get("next_step"), default=f"{action_label}可改善最新版報告資料缺口。")


def _post_action_hint(action: str) -> str:
    if action == "rerun_analysis":
        return "補強完成後重跑報告"
    return "補完後建議重跑報告"


def _tickers(row: dict, request: dict) -> list[str]:
    tickers = row.get("tickers")
    if not isinstance(tickers, list):
        tickers = request.get("tickers")
    if not isinstance(tickers, list):
        return []
    return [str(ticker).strip() for ticker in tickers if str(ticker).strip()]


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = []
    seen = set()
    for item in items:
        key = (item.get("operation"), tuple(item.get("tickers") or []), item.get("purpose"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _text(value: Any, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default
```

- [ ] **Step 4: Run the data gap tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_data_gap_actions_ui.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit the data gap helper**

Run:

```bash
git add app/ui/data_gap_actions.py tests/test_data_gap_actions_ui.py
git commit -m "Add data gap action map helper"
```

Expected:

```text
[main <hash>] Add data gap action map helper
```

### Task 5: Streamlit Page Integration and UI Contract

**Files:**
- Modify: `app/ui/analysis_workspace.py`
- Modify: `app/ui/report_center.py`
- Modify: `app/ui/data_enrichment_market.py`
- Modify: `app/ui/system_settings_maintenance.py`
- Modify: `app/ui/styles/stock_dashboard.css`
- Modify: `tests/streamlit_ui_test_helpers.py`
- Modify: `tests/test_streamlit_ui_contract.py`

- [ ] **Step 1: Write the failing UI contract additions**

Modify `tests/streamlit_ui_test_helpers.py` by adding these constants after `REPORT_HEALTH_SOURCE`:

```python
REPORT_LIFECYCLE_SOURCE = Path("app/ui/report_lifecycle.py")
INCIDENT_INBOX_SOURCE = Path("app/ui/incident_inbox.py")
OPERATOR_DECISIONS_SOURCE = Path("app/ui/operator_decisions.py")
DATA_GAP_ACTIONS_SOURCE = Path("app/ui/data_gap_actions.py")
```

Add the same four constants to `UI_SOURCE_FILES` immediately after `REPORT_HEALTH_SOURCE`:

```python
    REPORT_LIFECYCLE_SOURCE,
    INCIDENT_INBOX_SOURCE,
    OPERATOR_DECISIONS_SOURCE,
    DATA_GAP_ACTIONS_SOURCE,
```

Modify `tests/test_streamlit_ui_contract.py::test_streamlit_shell_uses_operational_workspace_header` by adding these assertions after the existing `report-health-card` assertion:

```python
    assert "from app.ui.report_lifecycle import latest_report_lifecycle" in source
    assert "latest_report_lifecycle(" in source
    assert "report-lifecycle-strip" in combined
    assert "report-lifecycle-step" in combined
    assert "報告生命週期" in source
```

Add these assertions after the existing `operator-status-card` assertion:

```python
    assert "from app.ui.operator_decisions import (" in source
    assert "operator_next_best_action(" in source
    assert "operator_secondary_actions(" in source
    assert "operator-decision-card" in combined
    assert "operator-secondary-actions" in combined
    assert "下一步建議" in source
    assert '"/reports/{int(latest_report_id)}"' in source
    assert '"/reports/{int(latest_report_id)}/follow-up/plan"' in source
```

Add these assertions after the existing `背景任務觀測` assertion:

```python
    assert "from app.ui.incident_inbox import (" in source
    assert "incident_inbox_items(" in source
    assert "incident_counts(" in source
    assert "incident-inbox" in combined
    assert "incident-card" in combined
    assert "待處理事件" in source
```

Add these assertions after the existing `action-impact-grid` assertion:

```python
    assert "from app.ui.data_gap_actions import (" in source
    assert "data_gap_action_items(" in source
    assert "data_gap_action_summary(" in source
    assert "data-gap-action-map" in combined
    assert "data-gap-action-card" in combined
    assert "資料缺口行動地圖" in source
```

- [ ] **Step 2: Run the UI contract and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_streamlit_ui_contract.py::test_streamlit_shell_uses_operational_workspace_header -q
```

Expected:

```text
AssertionError
```

- [ ] **Step 3: Integrate the decision layer into `app/ui/analysis_workspace.py`**

Add this import after the existing `dashboard_core` import:

```python
from app.ui.operator_decisions import (
    operator_next_best_action,
    operator_secondary_actions,
)
```

Inside `_render_operator_workbench`, after the `reports` type guard, insert this block:

```python
    latest_report_id = _latest_report_id(reports)
    latest_report_payload = {}
    latest_follow_up_plan = {}
    if latest_report_id is not None:
        latest_report_payload = load_api_json_or_default(
            f"/reports/{int(latest_report_id)}",
            {},
            error_message="讀取首頁報告狀態失敗",
            notify="warning",
        )
        latest_follow_up_plan = load_api_json_or_default(
            f"/reports/{int(latest_report_id)}/follow-up/plan",
            {},
            error_message="讀取首頁補強計畫失敗",
            notify="warning",
        )
    primary_action = operator_next_best_action(
        service_snapshot,
        task_summary,
        quota,
        reports,
        latest_report_payload,
        latest_follow_up_plan,
    )
    secondary_actions = operator_secondary_actions(
        service_snapshot,
        task_summary,
        quota,
        reports,
        latest_report_payload,
        latest_follow_up_plan,
    )
```

Inside the `st.markdown` HTML for `_render_operator_workbench`, add this line between the closing `</div>` of `.operator-workbench-head` and the opening `<div class="operator-status-grid">`:

```python
{_operator_decision_html(primary_action, secondary_actions)}
```

Add these helper functions below `_render_operator_workbench` and above `_operator_card_html`:

```python
def _latest_report_id(reports: list[dict]) -> int | None:
    for report in reports:
        if not isinstance(report, dict) or report.get("id") is None:
            continue
        try:
            return int(report["id"])
        except (TypeError, ValueError):
            return None
    return None


def _operator_decision_html(primary_action: dict, secondary_actions: list[dict]) -> str:
    secondary_html = "\n".join(_secondary_action_html(action) for action in secondary_actions)
    source_ids = primary_action.get("source_ids") or []
    source_text = "、".join(str(source_id) for source_id in source_ids) if source_ids else "系統狀態"
    return f"""<section class="operator-decision-card is-{escape(primary_action.get("state", "attention"))}">
<div class="operator-decision-copy">
<div class="workspace-kicker">下一步建議</div>
<h3>{escape(primary_action.get("title", "-"))}</h3>
<p>{escape(primary_action.get("reason", ""))}</p>
<div class="operator-decision-meta">
<span>風險：{escape(primary_action.get("risk", ""))}</span>
<span>影響：{escape(primary_action.get("impact", ""))}</span>
<span>來源：{escape(source_text)}</span>
</div>
</div>
<div class="operator-decision-action">
<strong>{escape(primary_action.get("action_label", "-"))}</strong>
<span>{escape(primary_action.get("route_hint", ""))}</span>
</div>
<div class="operator-secondary-actions" aria-label="次要建議">
{secondary_html}
</div>
</section>"""


def _secondary_action_html(action: dict) -> str:
    return f"""<article class="operator-secondary-action is-{escape(action.get("state", "attention"))}">
<strong>{escape(action.get("title", "-"))}</strong>
<span>{escape(action.get("detail", ""))}</span>
<em>{escape(action.get("route_hint", ""))}</em>
</article>"""
```

- [ ] **Step 4: Integrate the lifecycle strip into `app/ui/report_center.py`**

Add this import after the existing `report_health` import:

```python
from app.ui.report_lifecycle import latest_report_lifecycle
```

Inside `if selected_id and report_markdown:`, after `follow_up_plan = load_api_json_or_default(...)` and before `_render_report_health_strip(...)`, insert:

```python
        _render_report_lifecycle_strip(latest_report_lifecycle(history_result or {}, follow_up_plan))
```

Add this helper function immediately above `_render_report_health_strip`:

```python
def _render_report_lifecycle_strip(lifecycle: dict) -> None:
    stage_html = "\n".join(_report_lifecycle_stage_html(stage) for stage in lifecycle.get("stage_cards") or [])
    st.markdown(
        f"""<section class="report-lifecycle-strip is-{escape(lifecycle.get("overall_state", "attention"))}" aria-label="報告生命週期">
<div class="report-lifecycle-summary">
<span>報告生命週期</span>
<strong>{escape(lifecycle.get("trust_label", "-"))}</strong>
<p>{escape(lifecycle.get("trust_explanation", ""))}</p>
<em>{escape(lifecycle.get("primary_action", ""))}</em>
</div>
<div class="report-lifecycle-steps">
{stage_html}
</div>
</section>""",
        unsafe_allow_html=True,
    )


def _report_lifecycle_stage_html(stage: dict) -> str:
    return f"""<article class="report-lifecycle-step is-{escape(stage.get("state", "unknown"))}">
<span>{escape(stage.get("title", "-"))}</span>
<strong>{escape(stage.get("label", "-"))}</strong>
<p>{escape(stage.get("detail", ""))}</p>
</article>"""
```

- [ ] **Step 5: Integrate the incident inbox into `app/ui/system_settings_maintenance.py`**

Add this import after the existing `dashboard_core` import:

```python
from app.ui.incident_inbox import incident_counts, incident_inbox_items
```

After the `upgrade_audit = load_api_json_or_default(...)` block and before `render_upgrade_audit_panel(upgrade_audit)`, insert:

```python
    _render_incident_inbox(incident_inbox_items(service_snapshot, task_summary, llm_quota))
```

Add these helper functions at the bottom of the file:

```python
def _render_incident_inbox(incidents: list[dict]) -> None:
    counts = incident_counts(incidents)
    incident_html = "\n".join(_incident_card_html(incident) for incident in incidents[:8])
    if not incident_html:
        incident_html = """<article class="incident-card is-ready">
<strong>目前沒有待處理事件</strong>
<span>背景任務、近期失敗與 AI 額度沒有主要阻塞。</span>
</article>"""
    st.markdown(
        f"""<section class="incident-inbox" aria-label="待處理事件">
<div class="incident-inbox-head">
<div>
<div class="workspace-kicker">待處理事件</div>
<h3>事件收件匣</h3>
</div>
<div class="incident-counts">
<span>Critical {counts["critical"]}</span>
<span>Warning {counts["warning"]}</span>
<span>Info {counts["info"]}</span>
</div>
</div>
<div class="incident-list">
{incident_html}
</div>
</section>""",
        unsafe_allow_html=True,
    )


def _incident_card_html(incident: dict) -> str:
    return f"""<article class="incident-card is-{escape(incident.get("severity", "info"))}">
<strong>{escape(incident.get("title", "-"))}</strong>
<span>{escape(incident.get("impact", ""))}</span>
<em>{escape(incident.get("next_action", ""))}</em>
<small>{escape(incident.get("route_hint", ""))}</small>
</article>"""
```

Also add this import at the top of `app/ui/system_settings_maintenance.py`:

```python
from html import escape
```

- [ ] **Step 6: Integrate the data gap action map into `app/ui/data_enrichment_market.py`**

Add this import after the existing `dashboard_core` import:

```python
from app.ui.data_gap_actions import data_gap_action_items, data_gap_action_summary
```

After the `visual_rag_chain_rows` block and before `default_market_tickers = ...`, insert:

```python
    latest_report_payload, latest_follow_up_plan = _latest_report_follow_up_context()
    _render_data_gap_action_map(data_gap_action_items(latest_report_payload, latest_follow_up_plan))
```

Add these helper functions below `render_market_data_tab` and above `_render_cache_summary`:

```python
def _latest_report_follow_up_context() -> tuple[dict, dict]:
    reports = load_api_json_or_default(
        "/reports?limit=1",
        [],
        error_message="讀取最新版報告失敗",
        notify="warning",
    )
    if not isinstance(reports, list) or not reports:
        return {}, {}
    latest_report_id = reports[0].get("id") if isinstance(reports[0], dict) else None
    if latest_report_id is None:
        return {}, {}
    report_payload = load_api_json_or_default(
        f"/reports/{int(latest_report_id)}",
        {},
        error_message="讀取最新版報告內容失敗",
        notify="warning",
    )
    follow_up_plan = load_api_json_or_default(
        f"/reports/{int(latest_report_id)}/follow-up/plan",
        {},
        error_message="讀取最新版補強計畫失敗",
        notify="warning",
    )
    return report_payload if isinstance(report_payload, dict) else {}, follow_up_plan if isinstance(follow_up_plan, dict) else {}


def _render_data_gap_action_map(items: list[dict]) -> None:
    summary = data_gap_action_summary(items)
    cards_html = "\n".join(_data_gap_action_card_html(item) for item in items[:6])
    if not cards_html:
        cards_html = """<article class="data-gap-action-card is-ready">
<strong>目前沒有必要資料缺口</strong>
<span>最新版報告沒有必補資料行動。</span>
<em>可依例行需求刷新市場資料。</em>
</article>"""
    st.markdown(
        f"""<section class="data-gap-action-map is-{escape(summary.get("state", "ready"))}" aria-label="資料缺口行動地圖">
<div class="data-gap-action-head">
<div class="workspace-kicker">資料缺口行動地圖</div>
<h3>{escape(summary.get("label", "-"))}</h3>
<p>{escape(summary.get("detail", ""))}</p>
</div>
<div class="data-gap-action-list">
{cards_html}
</div>
</section>""",
        unsafe_allow_html=True,
    )


def _data_gap_action_card_html(item: dict) -> str:
    return f"""<article class="data-gap-action-card is-{escape(item.get("purpose", "tracking"))}">
<strong>{escape(item.get("action_label", "-"))}</strong>
<span>{escape(item.get("ticker", "全部"))}｜{escape(item.get("impact", ""))}</span>
<em>{escape(item.get("post_action_hint", ""))}</em>
</article>"""
```

Also add this import at the top of `app/ui/data_enrichment_market.py`:

```python
from html import escape
```

- [ ] **Step 7: Add compact CSS for the new surfaces**

Modify `app/ui/styles/stock_dashboard.css`.

Extend the existing margin selector:

```css
.operator-workbench,
.operator-decision-card,
.report-health-strip,
.report-lifecycle-strip,
.incident-inbox,
.data-gap-action-map,
.action-impact-grid {
    margin: 18px 0;
}
```

Add this block after the existing `.operator-workbench-head p` rule:

```css
.operator-decision-card {
    display: grid;
    grid-template-columns: minmax(0, 1.3fr) minmax(180px, 0.4fr);
    gap: 14px;
    background: #ffffff;
    border: 1px solid var(--stock-border);
    border-radius: 8px;
    padding: 16px;
}
.operator-decision-card h3,
.report-lifecycle-summary strong,
.incident-inbox h3,
.data-gap-action-head h3 {
    margin: 4px 0 6px;
    color: var(--stock-text);
}
.operator-decision-copy p,
.operator-decision-meta,
.report-lifecycle-summary p,
.report-lifecycle-step p,
.data-gap-action-head p {
    color: var(--stock-muted);
    line-height: 1.5;
}
.operator-decision-meta {
    display: grid;
    gap: 4px;
    font-size: 0.88rem;
}
.operator-decision-action {
    align-self: start;
    background: var(--stock-surface-alt);
    border: 1px solid var(--stock-border-soft);
    border-radius: 8px;
    padding: 12px;
}
.operator-decision-action strong,
.operator-decision-action span {
    display: block;
}
.operator-decision-action span {
    margin-top: 4px;
    color: var(--stock-muted);
    font-size: 0.85rem;
}
.operator-secondary-actions {
    grid-column: 1 / -1;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
}
.operator-secondary-action,
.report-lifecycle-step,
.incident-card,
.data-gap-action-card {
    background: var(--stock-surface-alt);
    border: 1px solid var(--stock-border-soft);
    border-radius: 8px;
    padding: 12px;
}
.operator-secondary-action strong,
.operator-secondary-action span,
.operator-secondary-action em,
.incident-card strong,
.incident-card span,
.incident-card em,
.incident-card small,
.data-gap-action-card strong,
.data-gap-action-card span,
.data-gap-action-card em {
    display: block;
}
.operator-secondary-action span,
.incident-card span,
.data-gap-action-card span {
    margin-top: 5px;
    color: var(--stock-muted);
}
.operator-secondary-action em,
.incident-card em,
.incident-card small,
.data-gap-action-card em {
    margin-top: 7px;
    color: #334155;
    font-style: normal;
    font-size: 0.84rem;
}
```

Add this block after the existing `.report-health-strip` rule:

```css
.report-lifecycle-strip {
    display: grid;
    grid-template-columns: minmax(220px, 0.42fr) minmax(0, 1fr);
    gap: 12px;
    background: var(--stock-surface);
    border: 1px solid var(--stock-border);
    border-radius: 8px;
    padding: 16px;
}
.report-lifecycle-summary span,
.report-lifecycle-summary em,
.report-lifecycle-step span {
    color: var(--stock-muted);
    font-style: normal;
    font-size: 0.88rem;
}
.report-lifecycle-steps {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 8px;
}
.report-lifecycle-step strong {
    display: block;
    margin-top: 4px;
    color: var(--stock-text);
}
.incident-inbox,
.data-gap-action-map {
    background: var(--stock-surface);
    border: 1px solid var(--stock-border);
    border-radius: 8px;
    padding: 16px;
}
.incident-inbox-head,
.data-gap-action-head {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    align-items: flex-start;
    margin-bottom: 12px;
}
.incident-counts {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}
.incident-counts span {
    border: 1px solid var(--stock-border);
    border-radius: 999px;
    padding: 4px 9px;
    color: #334155;
    background: #ffffff;
    font-size: 0.84rem;
    font-weight: 700;
}
.incident-list,
.data-gap-action-list {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
}
.is-critical,
.is-blocked {
    border-color: rgba(180, 35, 24, 0.32);
}
.is-warning,
.is-attention,
.is-required {
    border-color: rgba(146, 64, 14, 0.28);
}
.is-ready,
.is-done {
    border-color: rgba(15, 118, 110, 0.25);
}
```

Extend the existing `@media (max-width: 900px)` grid rule:

```css
    .operator-status-grid,
    .operator-secondary-actions,
    .report-health-strip,
    .report-lifecycle-strip,
    .report-lifecycle-steps,
    .incident-list,
    .data-gap-action-list,
    .action-impact-grid {
        grid-template-columns: 1fr;
    }
    .operator-decision-card {
        grid-template-columns: 1fr;
    }
```

- [ ] **Step 8: Run the focused UI contract and helper tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_report_lifecycle_ui.py tests/test_incident_inbox_ui.py tests/test_operator_decisions_ui.py tests/test_data_gap_actions_ui.py tests/test_streamlit_ui_contract.py -q
```

Expected:

```text
passed
```

- [ ] **Step 9: Run ruff for modified UI and tests**

Run:

```bash
.venv/bin/python -m ruff check app/ui tests/test_report_lifecycle_ui.py tests/test_incident_inbox_ui.py tests/test_operator_decisions_ui.py tests/test_data_gap_actions_ui.py tests/test_streamlit_ui_contract.py
```

Expected:

```text
All checks passed!
```

- [ ] **Step 10: Commit the Streamlit integration**

Run:

```bash
git add app/ui/analysis_workspace.py app/ui/report_center.py app/ui/data_enrichment_market.py app/ui/system_settings_maintenance.py app/ui/styles/stock_dashboard.css tests/streamlit_ui_test_helpers.py tests/test_streamlit_ui_contract.py
git commit -m "Render operator decision layer UI"
```

Expected:

```text
[main <hash>] Render operator decision layer UI
```

### Task 6: Full Verification and Browser QA

**Files:**
- Verify: all files changed in Tasks 1 through 5.

- [ ] **Step 1: Run focused tests one more time**

Run:

```bash
.venv/bin/python -m pytest tests/test_report_lifecycle_ui.py tests/test_incident_inbox_ui.py tests/test_operator_decisions_ui.py tests/test_data_gap_actions_ui.py tests/test_streamlit_ui_contract.py -q
```

Expected:

```text
passed
```

- [ ] **Step 2: Run full test suite**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected:

```text
passed
```

- [ ] **Step 3: Run ruff on the repository**

Run:

```bash
.venv/bin/python -m ruff check .
```

Expected:

```text
All checks passed!
```

- [ ] **Step 4: Compile Python files**

Run:

```bash
.venv/bin/python -m compileall app tests scripts
```

Expected:

```text
Listing 'app'...
Listing 'tests'...
Listing 'scripts'...
```

The command must exit with status `0`.

- [ ] **Step 5: Run the existing task submission smoke test without external data refresh**

Run:

```bash
.venv/bin/python scripts/task_submission_smoke.py --base-url http://127.0.0.1:8000 --no-external-refresh
```

Expected:

```text
task_submission_smoke passed
```

- [ ] **Step 6: Run the existing frontend smoke test**

Run:

```bash
.venv/bin/python scripts/frontend_smoke.py --base-url http://127.0.0.1:8501
```

Expected:

```text
frontend_smoke passed
```

- [ ] **Step 7: Use Browser QA on the Streamlit app**

Use the Browser plugin or the local browser QA tool against `http://127.0.0.1:8501`. Verify these operator-facing surfaces render without overlap on desktop and mobile widths:

- `分析工作區`: `下一步建議`, `今日狀態`, decision card, secondary actions.
- `報告中心`: `報告生命週期`, lifecycle steps, existing report health strip.
- `資料補強`: `資料缺口行動地圖`, existing refresh buttons.
- `系統設定` then `維護`: `待處理事件`, existing background task observability.

Expected:

```text
No blank page, no uncaught Streamlit exception, no overlapping text, and the new cards fit inside the viewport at 390px and 1440px widths.
```

- [ ] **Step 8: Commit QA fixes after verification**

If verification changes are made during Task 6, commit only those changes:

```bash
git add app/ui tests
git commit -m "Fix operator decision layer QA findings"
```

Expected:

```text
[main <hash>] Fix operator decision layer QA findings
```

When Task 6 produces no code changes, record the verification commands and results in the final execution summary without creating an empty commit.

## Self-Review Checklist

- Spec coverage:
  - Next Best Action is implemented in Task 3 and rendered in Task 5.
  - Report lifecycle is implemented in Task 1 and rendered in Task 5.
  - Incident inbox is implemented in Task 2 and rendered in Task 5.
  - Data gap action map is implemented in Task 4 and rendered in Task 5.
  - Existing diagnostics, task submission, report retention, and manual controls remain in place.
  - UI rendering uses existing read endpoints only; it does not call LLM test endpoints, scraping endpoints, or data refresh endpoints.
- Type consistency:
  - Lifecycle uses `overall_state`, `trust_label`, `trust_explanation`, `primary_action`, `route_hint`, `report_id`, and `stage_cards`.
  - Incidents use `severity`, `category`, `title`, `impact`, `next_action`, `route_hint`, `retryable`, `source`, `created_at`, and `dedupe_key`.
  - Operator actions use `state`, `priority`, `title`, `reason`, `risk`, `impact`, `action_label`, `route_hint`, and `source_ids`.
  - Data-gap actions use `report_id`, `topic`, `ticker`, `tickers`, `gap_type`, `action_label`, `operation`, `impact`, `post_action_hint`, `route_hint`, `purpose`, and `priority`.
- Verification:
  - Helper tests cover ready, attention, blocked, running, dedupe, quota, and empty states.
  - UI contract locks the new imports, labels, CSS classes, and latest-report detail endpoints.
  - Browser QA checks desktop and mobile layout for the four operator surfaces.
