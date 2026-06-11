from __future__ import annotations

from typing import Any

from app.ui.operator_quota_presenter import quota_operator_summary
from app.ui.operator_task_state import (
    latest_task_row as _latest_task,
    latest_task_running as _latest_task_running,
    latest_task_successful as _latest_task_successful,
    task_row_failed as _task_failed,
    task_summary_failures as _recent_failures,
)


READY_OVERALL = {"state": "ready", "label": "可執行", "detail": "背景任務與最新版報告都可用。"}

PAYLOAD_VALIDATION_DETAIL = "補強或重跑任務曾被輸入驗證擋下；修正後可重試。"
RUNNING_TASK_DETAIL = "背景任務正在處理；完成前先等待結果，不要重複送出同類任務。"


def operator_status_overall(
    service_snapshot: dict, task_summary: dict, reports: list[dict]
) -> dict[str, str]:
    if service_status_unavailable(service_snapshot):
        return {
            "state": "attention",
            "label": "系統狀態暫不可讀",
            "detail": "目前無法讀取系統狀態；請到維護頁確認 API 與背景任務狀態。",
        }

    task_queue = _task_queue_from_snapshot(service_snapshot)
    totals = _dict_value(task_summary.get("totals") if isinstance(task_summary, dict) else None)
    if not _queue_ready(task_queue):
        return {
            "state": "blocked",
            "label": "背景任務未就緒",
            "detail": "請先到系統設定檢查背景任務佇列與背景執行器。",
        }

    if _int_value(totals.get("stale_running_count")) > 0:
        return {
            "state": "blocked",
            "label": "有卡住任務",
            "detail": "有任務疑似卡住，請先到維護頁處理。",
        }

    if _latest_task_running(task_summary):
        return {
            "state": "attention",
            "label": "最新任務執行中",
            "detail": RUNNING_TASK_DETAIL,
        }

    if not _latest_report(reports):
        return {
            "state": "attention",
            "label": "尚無最新版報告",
            "detail": "系統可執行，請先建立分析報告。",
        }

    failure_count = len(_recent_failures(task_summary))
    if failure_count:
        if _latest_task_failed(task_summary):
            return {
                "state": "attention",
                "label": "最新任務需要確認",
                "detail": "最新任務失敗或取消；請先查看任務診斷後再重試或重新送出。",
            }
        if _latest_task_successful(task_summary):
            return {
                "state": "ready",
                "label": "可執行",
                "detail": "背景任務與最新版報告都可用；歷史失敗仍可追蹤。",
            }
        return {
            "state": "attention",
            "label": "有待處理紀錄",
            "detail": "最近任務可執行，但仍有歷史失敗需要重試或確認。",
        }
    return dict(READY_OVERALL)


def operator_status_cards(
    service_snapshot: dict,
    task_summary: dict,
    quota: dict,
    reports: list[dict],
) -> list[dict[str, str]]:
    service_status_missing = service_status_unavailable(service_snapshot)
    task_queue = _task_queue_from_snapshot(service_snapshot)
    report = _latest_report(reports)
    running_task = _latest_task(task_summary) if _latest_task_running(task_summary) else {}
    quota_summary = quota_operator_summary(quota)
    failure_summary = _first_failure_summary(task_summary)
    queue_state = (
        "attention" if service_status_missing else "ready" if _queue_ready(task_queue) else "blocked"
    )
    queue_running = queue_state == "ready" and bool(running_task)

    return [
        {
            "title": "系統狀態",
            "value": "處理中" if queue_running else _queue_card_value(queue_state),
            "caption": (
                "無法讀取系統狀態"
                if service_status_missing
                else "背景執行器在線，最新任務執行中"
                if queue_running
                else "背景執行器在線"
                if task_queue.get("worker_online")
                else "背景執行器離線"
            ),
            "state": "attention" if queue_running else queue_state,
            "action_label": (
                "查看任務" if queue_running else "開始使用" if queue_state == "ready" else "查看維護"
            ),
            "route_hint": (
                _task_route_hint(running_task)
                if queue_running
                else "analysis"
                if queue_state == "ready"
                else "settings:maintenance"
            ),
        },
        {
            "title": "最新版報告",
            "value": "生成中" if running_task and not report else _report_value(report),
            "caption": (
                "最新任務執行中" if running_task and not report else _report_caption(report)
            ),
            "state": "ready" if report else "attention",
            "action_label": "讀報告" if report else "查看任務" if running_task else "建立分析",
            "route_hint": (
                _task_route_hint(running_task)
                if running_task and not report
                else _report_route_hint(report)
            ),
        },
        {
            "title": "AI 額度",
            "value": quota_summary["recommended_model"],
            "caption": quota_summary["operator_caption"],
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


def service_status_unavailable(service_snapshot: dict | None) -> bool:
    return not isinstance(service_snapshot, dict) or not isinstance(
        service_snapshot.get("task_queue"), dict
    )


def task_summary_unavailable(task_summary: dict | None) -> bool:
    if not isinstance(task_summary, dict):
        return True
    return not any(
        key in task_summary
        for key in ("totals", "recent", "recent_failures", "alerts", "latest", "latest_task")
    )


def task_failure_action_summary(failure: dict) -> dict[str, str]:
    if not isinstance(failure, dict) or not failure:
        return {
            "state": "ready",
            "label": "無阻塞",
            "detail": "最近任務沒有需要立即處理的失敗。",
            "action_label": "繼續",
            "route_hint": "analysis",
        }

    category = _text(failure.get("error_category"))
    retryable = bool(failure.get("retryable"))
    task_id = _text(failure.get("task_id"))
    if category == "payload_validation":
        return {
            "state": "attention",
            "label": "輸入或白名單已擋下任務",
            "detail": PAYLOAD_VALIDATION_DETAIL,
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
        "detail": _text(failure.get("next_action"), default="請到維護頁查看任務細節。"),
        "action_label": "查看維護",
        "route_hint": f"task:{task_id}" if task_id else "settings:maintenance",
    }


def _task_queue_from_snapshot(service_snapshot: dict) -> dict:
    if not isinstance(service_snapshot, dict):
        return {}
    task_queue = service_snapshot.get("task_queue")
    return task_queue if isinstance(task_queue, dict) else {}


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _queue_ready(task_queue: dict) -> bool:
    return bool(
        task_queue.get("ready")
        and task_queue.get("processing_ready")
        and task_queue.get("worker_online")
    )


def _queue_submission_ready(task_queue: dict) -> bool:
    return bool(task_queue.get("ready"))


def _queue_processing_ready(task_queue: dict) -> bool:
    if "processing_ready" in task_queue:
        return bool(task_queue.get("processing_ready"))
    return bool(task_queue.get("ready") and task_queue.get("worker_online"))


def _queue_value(task_queue: dict) -> str:
    if _queue_processing_ready(task_queue):
        return "可執行"
    if _queue_submission_ready(task_queue):
        return "可提交"
    return "需修復"


def _queue_card_value(queue_state: str) -> str:
    if queue_state == "ready":
        return "可送任務"
    if queue_state == "attention":
        return "狀態未知"
    return "需維護"


def _latest_task_failed(task_summary: dict) -> bool:
    return _task_failed(_latest_task(task_summary))


def _latest_report(reports: list[dict]) -> dict:
    if not isinstance(reports, list):
        return {}
    for report in reports:
        if isinstance(report, dict):
            return report
    return {}


def _first_failure(task_summary: dict) -> dict:
    failures = _recent_failures(task_summary)
    return failures[0] if failures else {}


def _report_id(report: dict) -> str:
    if not isinstance(report, dict):
        return ""
    return _text(report.get("id") or report.get("report_id"))


def _report_value(report: dict) -> str:
    report_id = _report_id(report)
    return f"#{report_id}" if report_id else "-"


def _report_detail(report: dict) -> str:
    if not isinstance(report, dict) or not report:
        return "尚未取得最新版報告。"
    topic = _text(report.get("topic") or report.get("title"))
    return topic or "最新版報告可用。"


def _report_caption(report: dict) -> str:
    if not isinstance(report, dict) or not report:
        return "尚無最新版報告"
    return _text(report.get("topic") or report.get("title"), default="未命名報告")


def _report_route_hint(report: dict) -> str:
    report_id = _report_id(report)
    return f"report:{report_id}" if report_id else "analysis"


def _task_route_hint(task: dict) -> str:
    task_id = _text(task.get("task_id"))
    return f"task:{task_id}" if task_id else "settings:maintenance"


def _first_failure_summary(task_summary: dict) -> dict[str, str]:
    if task_summary_unavailable(task_summary):
        return {
            "state": "attention",
            "label": "任務摘要暫不可讀",
            "detail": "目前無法讀取任務摘要；不代表沒有失敗任務。",
            "action_label": "查看維護",
            "route_hint": "settings:maintenance",
        }
    first_failure = _first_failure(task_summary)
    if not first_failure and _latest_task_running(task_summary):
        return _running_task_summary(_latest_task(task_summary))
    if first_failure and _latest_task_successful(task_summary):
        return _historical_failure_summary(first_failure)
    return task_failure_action_summary(first_failure)


def _running_task_summary(task: dict) -> dict[str, str]:
    return {
        "state": "attention",
        "label": "等待任務完成",
        "detail": "最新任務正在背景執行；完成前不需要重複送出。",
        "action_label": "查看任務",
        "route_hint": _task_route_hint(task),
    }


def _historical_failure_summary(failure: dict) -> dict[str, str]:
    task_id = _text(failure.get("task_id"))
    return {
        "state": "ready",
        "label": "歷史失敗可追蹤",
        "detail": "最新任務已成功；舊失敗保留於維護頁，不影響閱讀最新版報告。",
        "action_label": "查看紀錄",
        "route_hint": f"task:{task_id}" if task_id else "settings:maintenance",
    }


def _text(value: Any, *, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
