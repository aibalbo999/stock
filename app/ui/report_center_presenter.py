from __future__ import annotations

import json
from typing import Any


RUN_SOURCE_LABELS = {
    "follow_up_api": "自動補強",
    "pipeline_api": "分析流程",
    "report_api": "報告生成",
    "topic_discovery": "主題探索",
    "manual": "手動操作",
}

RUN_STATUS_LABELS = {
    "completed": "完成",
    "success": "完成",
    "successful": "完成",
    "succeeded": "完成",
    "done": "完成",
    "failed": "失敗",
    "failure": "失敗",
    "error": "錯誤",
    "cancelled": "已取消",
    "running": "執行中",
    "started": "執行中",
    "in_progress": "執行中",
    "processing": "執行中",
    "queued": "排隊中",
    "pending": "排隊中",
    "submitted": "已送出",
}

RUN_ERROR_LABELS = {
    "task_queue_error": "背景任務佇列異常",
    "payload_validation": "輸入或白名單已擋下任務",
    "runtime_storage": "執行紀錄儲存異常",
    "timeout": "逾時",
}


def latest_report_picker_state(
    reports: list[dict] | None,
    *,
    pending_report_id: Any = None,
    current_report_id: Any = None,
    task_summary: dict | None = None,
) -> dict[str, Any]:
    options = _latest_report_options(reports)
    if not options:
        latest_running_task = _latest_task_running(task_summary)
        if latest_running_task:
            return {
                "mode": "running",
                "options": [],
                "selected_id": None,
                "selector_label": "",
                "summary_title": "最新版報告生成中",
                "summary_detail": "最新任務正在背景執行；完成前不需要重複建立分析。",
                "scope_note": "完成後報告中心會只顯示可閱讀的最新版結果。",
                "action_label": "查看任務",
                "route_hint": _task_route_hint(latest_running_task),
            }
        return {
            "mode": "empty",
            "options": [],
            "selected_id": None,
            "selector_label": "",
            "summary_title": "尚無最新版報告",
            "summary_detail": "建立分析後，這裡會顯示目前保留的最新版報告。",
            "scope_note": "報告中心不需要手動整理歷史版本；系統會保留最新可讀結果。",
            "action_label": "建立分析",
            "route_hint": "analysis",
        }

    selected_id = (
        _matching_report_id(options, pending_report_id)
        or _matching_report_id(options, current_report_id)
        or options[0]["id"]
    )
    if len(options) == 1:
        return {
            "mode": "single_latest",
            "options": options,
            "selected_id": selected_id,
            "selector_label": "",
            "summary_title": "目前最新版報告",
            "summary_detail": options[0]["summary_detail"],
            "scope_note": "此頁只顯示目前保留的最新版；舊版請到疑難排解的執行紀錄追蹤。",
        }

    return {
        "mode": "multi_topic_latest",
        "options": options,
        "selected_id": selected_id,
        "selector_label": "選擇主題最新版報告",
        "summary_title": "每個主題的最新版",
        "summary_detail": f"共 {len(options)} 份主題最新版，預設讀取最新產生的一份。",
        "scope_note": "這不是歷史版本清單；每個主題只顯示最新一份可讀報告。",
    }


def report_run_history_rows(runs: list[Any] | None) -> list[dict[str, Any]]:
    if not isinstance(runs, list):
        return []
    rows: list[dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict) or run.get("id") is None:
            continue
        payload = _parse_json_object(run.get("payload") or "{}")
        rows.append(
            {
                "紀錄": f"#{run.get('id')}",
                "來源": _run_source_label(run.get("source")),
                "狀態": _run_status_label(run.get("status")),
                "報告": f"#{run.get('report_id')}" if run.get("report_id") else "-",
                "背景任務": payload.get("celery_task_id") or "-",
                "開始": _format_optional_time(run.get("started_at")),
                "完成": _format_optional_time(run.get("finished_at")),
                "錯誤": _run_error_label(run.get("error")),
            }
        )
    return rows


def report_run_history_ids(runs: list[Any] | None) -> list[Any]:
    if not isinstance(runs, list):
        return []
    return [run["id"] for run in runs if isinstance(run, dict) and run.get("id") is not None]


def report_run_detail_error_message(error: Any) -> str:
    return f"執行紀錄錯誤：{_run_error_label(error)}"


def empty_report_action_summary(picker: dict[str, Any]) -> dict[str, str]:
    action_label = _text(picker.get("action_label"))
    route_hint = _text(picker.get("route_hint"))
    if not action_label or not route_hint:
        return {}
    if _text(picker.get("mode")) == "running":
        return {
            "state": "running",
            "eyebrow": "建議操作",
            "title": "先確認背景任務進度",
            "caption": "最新任務還在背景執行；完成前避免重複送出分析。",
            "action_label": action_label,
            "route_hint": route_hint,
        }
    return {
        "state": "empty",
        "eyebrow": "建議操作",
        "title": "建立第一份最新版報告",
        "caption": "前往分析工作區建立報告；完成後回到這裡閱讀最新版。",
        "action_label": action_label,
        "route_hint": route_hint,
    }


def report_reader_decision_summary(
    lifecycle: dict[str, Any],
    health_summary: dict[str, str],
) -> dict[str, str]:
    lifecycle_state = _text(lifecycle.get("overall_state"), default="attention")
    health_state = _text(health_summary.get("state"))
    state = _reader_decision_state(lifecycle_state, health_state)
    title = {
        "ready": "可以閱讀最新版",
        "running": "等待補強完成再閱讀",
        "attention": "可先閱讀，但投資判斷需標示限制",
        "blocked": "暫停採信，先處理阻塞",
    }.get(state, "需要人工確認後再閱讀")
    action_label = _reader_decision_action_label(lifecycle, health_summary, state)
    action_detail = _reader_decision_action_detail(lifecycle, state)
    return {
        "state": state,
        "eyebrow": "閱讀決策",
        "title": title,
        "caption": _text(
            lifecycle.get("trust_explanation"),
            default="請先確認報告生命週期與品質狀態。",
        ),
        "evidence": _text(
            health_summary.get("report_meta_label"),
            default="尚無報告時間",
        ),
        "quality": _reader_quality_label(health_summary),
        "follow_up": f"補強 {_text(health_summary.get('follow_up_label'), default='尚無狀態')}",
        "action_label": action_label,
        "action_detail": action_detail,
    }


def _latest_report_options(reports: list[dict] | None) -> list[dict[str, Any]]:
    if not isinstance(reports, list):
        return []
    options: list[dict[str, Any]] = []
    for report in reports:
        if not isinstance(report, dict) or report.get("id") is None:
            continue
        generated_at = _format_generated_at(report.get("generated_at"))
        title = _text(report.get("title") or report.get("topic"), default="未命名報告")
        topic = _text(report.get("topic") or report.get("title"), default="未命名主題")
        options.append(
            {
                "id": report["id"],
                "label": f"{generated_at}｜{title}",
                "summary_detail": f"{topic}｜{generated_at}",
            }
        )
    return options


def _matching_report_id(options: list[dict[str, Any]], report_id: Any) -> Any:
    report_id_text = _text(report_id)
    if not report_id_text:
        return None
    for option in options:
        if _text(option.get("id")) == report_id_text:
            return option["id"]
    return None


def _latest_task_running(task_summary: dict | None) -> dict:
    task = _latest_task(task_summary)
    return task if _task_running(task) else {}


def _latest_task(task_summary: dict | None) -> dict:
    if not isinstance(task_summary, dict):
        return {}
    for key in ("latest", "latest_task"):
        value = task_summary.get(key)
        if isinstance(value, dict):
            return value
    recent = task_summary.get("recent")
    if isinstance(recent, list):
        for row in recent:
            if isinstance(row, dict):
                return row
    return {}


def _task_running(task: dict) -> bool:
    if _task_successful(task) or _task_failed(task):
        return False
    if task.get("running") is True:
        return True
    status = _text(task.get("status")).casefold()
    celery_status = _text(task.get("celery_status")).casefold()
    return status in {
        "pending",
        "queued",
        "received",
        "retry",
        "running",
        "started",
        "in_progress",
        "processing",
        "submitted",
        "scheduled",
    } or celery_status in {
        "pending",
        "queued",
        "received",
        "retry",
        "running",
        "started",
    }


def _task_successful(task: dict) -> bool:
    if task.get("successful") is True:
        return True
    status = _text(task.get("status")).casefold()
    celery_status = _text(task.get("celery_status")).casefold()
    return status in {"success", "successful", "succeeded", "completed", "done"} or celery_status in {
        "success",
        "successful",
        "succeeded",
    }


def _task_failed(task: dict) -> bool:
    status = _text(task.get("status")).casefold()
    celery_status = _text(task.get("celery_status")).casefold()
    if status in {"failed", "failure", "cancelled", "error"}:
        return True
    if celery_status in {"failed", "failure", "revoked"}:
        return True
    return bool(task.get("error") or task.get("error_category"))


def _task_route_hint(task: dict) -> str:
    task_id = _text(task.get("task_id"))
    return f"task:{task_id}" if task_id else "settings:maintenance"


def _format_generated_at(value: Any) -> str:
    text = _text(value)
    if not text:
        return "未標示時間"
    return text[:16].replace("T", " ")


def _format_optional_time(value: Any) -> str:
    text = _text(value)
    return _format_generated_at(text) if text else "-"


def _run_source_label(value: Any) -> str:
    text = _text(value)
    return RUN_SOURCE_LABELS.get(text, text or "-")


def _run_status_label(value: Any) -> str:
    text = _text(value).casefold()
    return RUN_STATUS_LABELS.get(text, text or "-")


def _run_error_label(value: Any) -> str:
    text = _text(value)
    return RUN_ERROR_LABELS.get(text, text or "-")


def _reader_decision_state(lifecycle_state: str, health_state: str) -> str:
    priority = {"blocked": 4, "running": 3, "attention": 2, "ready": 1}
    candidates = [state for state in (lifecycle_state, health_state) if state]
    if not candidates:
        return "attention"
    return max(candidates, key=lambda state: priority.get(state, 0))


def _reader_decision_action_label(
    lifecycle: dict[str, Any],
    health_summary: dict[str, str],
    state: str,
) -> str:
    if state == "blocked":
        return _text(
            health_summary.get("action_label"),
            default=lifecycle.get("primary_action", "確認狀態"),
        )
    return _text(
        lifecycle.get("primary_action"),
        default=health_summary.get("action_label", "確認狀態"),
    )


def _reader_decision_action_detail(lifecycle: dict[str, Any], state: str) -> str:
    if state == "blocked":
        return "完成建議操作後再回來閱讀最新版。"
    return _text(
        lifecycle.get("primary_action_detail"),
        default="完成建議操作後再回來閱讀最新版。",
    )


def _reader_quality_label(health_summary: dict[str, str]) -> str:
    quality = _text(health_summary.get("quality_label"), default="-")
    candidates = _text(health_summary.get("candidate_label"), default="候選 0｜正式 0")
    return f"品質 {quality}｜{candidates}"


def _parse_json_object(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _text(value: Any, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default
