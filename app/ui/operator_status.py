from __future__ import annotations

from typing import Any


READY_OVERALL = {"state": "ready", "label": "可執行", "detail": "背景任務與最新版報告都可用。"}

PAYLOAD_VALIDATION_DETAIL = "補強或重跑任務曾被 payload 驗證擋下；修正後可重試。"


def operator_status_overall(
    service_snapshot: dict, task_summary: dict, reports: list[dict]
) -> dict[str, str]:
    task_queue = _task_queue_from_snapshot(service_snapshot)
    if not _queue_submission_ready(task_queue):
        return {
            "state": "blocked",
            "label": "Queue 需修復",
            "detail": "背景任務 queue 尚不可提交，請先修復 Redis/Celery 狀態。",
        }
    if not _queue_processing_ready(task_queue):
        return {
            "state": "attention",
            "label": "等待 Worker",
            "detail": "Queue 可提交，但 worker 尚未確認可接手執行。",
        }

    latest_task = _latest_task(task_summary)
    if latest_task and not _task_successful(latest_task):
        return {
            "state": "attention",
            "label": "最近任務需確認",
            "detail": "Queue 可執行，但最近任務尚未成功完成。",
        }
    if not _latest_report(reports):
        return {
            "state": "attention",
            "label": "缺最新版報告",
            "detail": "最近任務可執行，但尚未取得最新版報告。",
        }

    failure_count = len(_recent_failures(task_summary))
    if failure_count:
        return {
            "state": "attention",
            "label": "有待處理紀錄",
            "detail": f"最近任務可執行，仍有 {failure_count} 筆歷史失敗紀錄待處理。",
        }
    return dict(READY_OVERALL)


def operator_status_cards(
    service_snapshot: dict,
    task_summary: dict,
    quota: dict,
    reports: list[dict],
) -> list[dict[str, str]]:
    overall = operator_status_overall(service_snapshot, task_summary, reports)
    task_queue = _task_queue_from_snapshot(service_snapshot)
    report = _latest_report(reports)
    quota_summary = quota_operator_summary(quota)
    failure_summary = task_failure_action_summary(_first_failure(task_summary))

    return [
        {
            "title": "系統狀態",
            "state": overall["state"],
            "label": overall["label"],
            "value": _queue_value(task_queue),
            "detail": overall["detail"],
            "queue_state": "ready" if _queue_processing_ready(task_queue) else "attention",
            "action_label": "",
            "route_hint": "",
        },
        {
            "title": "最新版報告",
            "state": "ready" if report else "attention",
            "label": "可查看" if report else "尚未產生",
            "value": _report_value(report),
            "detail": _report_detail(report),
            "report_id": _report_id(report),
            "action_label": "查看報告" if report else "產生報告",
            "route_hint": _report_route_hint(report),
        },
        {
            "title": "AI 額度",
            "state": quota_summary["state"],
            "label": "可用" if quota_summary["state"] == "ready" else "需確認",
            "value": quota_summary["recommended_model"],
            "detail": quota_summary["caption"],
            "recommended_model": quota_summary["recommended_model"],
            "remaining": quota_summary["remaining"],
            "action_label": "查看額度",
            "route_hint": "quota",
        },
        {
            "title": "待處理事項",
            "state": failure_summary["state"],
            "label": failure_summary["label"],
            "value": failure_summary["action_label"],
            "detail": failure_summary["detail"],
            "failure_action": failure_summary["action_label"],
            "action_label": failure_summary["action_label"],
            "route_hint": failure_summary["route_hint"],
        },
    ]


def quota_operator_summary(quota: dict) -> dict[str, str]:
    recommended_model = _text(quota.get("recommended_model"), default="-")
    recommended_row = _recommended_quota_row(quota, recommended_model)
    remaining = _quota_remaining_text(recommended_row)
    state = _quota_state(recommended_row)
    fallback_models = _high_quota_fallback_models(quota)
    caption = "高額度保底：" + "、".join(fallback_models) if fallback_models else "高額度保底：-"
    return {
        "recommended_model": recommended_model,
        "remaining": remaining,
        "state": state,
        "caption": caption,
    }


def task_failure_action_summary(failure: dict) -> dict[str, str]:
    if not isinstance(failure, dict) or not failure:
        return {
            "state": "ready",
            "label": "無待處理",
            "detail": "沒有待處理的失敗任務。",
            "action_label": "",
            "route_hint": "",
        }

    category = _text(failure.get("error_category"))
    retryable = bool(failure.get("retryable"))
    task_id = _text(failure.get("task_id"))
    if category == "payload_validation":
        return {
            "state": "attention",
            "label": _text(failure.get("error_summary"), default="輸入或白名單已擋下任務"),
            "detail": PAYLOAD_VALIDATION_DETAIL,
            "action_label": "可重試" if retryable else "需修正",
            "route_hint": f"task:{task_id}" if task_id else "",
        }

    return {
        "state": "attention",
        "label": _failure_label(category, failure),
        "detail": _failure_detail(category, retryable),
        "action_label": "可重試" if retryable else "需人工處理",
        "route_hint": f"task:{task_id}" if task_id else "",
    }


def _task_queue_from_snapshot(service_snapshot: dict) -> dict:
    if not isinstance(service_snapshot, dict):
        return {}
    task_queue = service_snapshot.get("task_queue")
    return task_queue if isinstance(task_queue, dict) else {}


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


def _latest_task(task_summary: dict) -> dict:
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


def _task_successful(task: dict) -> bool:
    if task.get("successful") is True:
        return True
    status = _text(task.get("status")).casefold()
    celery_status = _text(task.get("celery_status")).casefold()
    return status in {"success", "successful", "completed"} or celery_status == "success"


def _latest_report(reports: list[dict]) -> dict:
    if not isinstance(reports, list):
        return {}
    for report in reports:
        if isinstance(report, dict):
            return report
    return {}


def _recent_failures(task_summary: dict) -> list[dict]:
    if not isinstance(task_summary, dict):
        return []
    failures = task_summary.get("recent_failures")
    if not isinstance(failures, list):
        return []
    return [failure for failure in failures if isinstance(failure, dict)]


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


def _report_route_hint(report: dict) -> str:
    report_id = _report_id(report)
    return f"report:{report_id}" if report_id else "report:new"


def _recommended_quota_row(quota: dict, recommended_model: str) -> dict:
    if not isinstance(quota, dict):
        return {}
    fallback = {}
    for row in quota.get("models") or []:
        if not isinstance(row, dict):
            continue
        if not fallback:
            fallback = row
        if _text(row.get("model")) == recommended_model:
            return row
    return fallback


def _quota_remaining_text(model_row: dict) -> str:
    remaining = model_row.get("requests_remaining") if isinstance(model_row, dict) else None
    budget = model_row.get("request_budget") if isinstance(model_row, dict) else None
    if remaining in {None, ""} and budget in {None, ""}:
        return "- / -"
    return f"{_text(remaining, default='-')} / {_text(budget, default='-')}"


def _quota_state(model_row: dict) -> str:
    if not isinstance(model_row, dict) or not model_row:
        return "attention"
    status = _text(model_row.get("status")).casefold()
    if status in {"ready", "available", "ok"}:
        return "ready"
    remaining = model_row.get("requests_remaining")
    try:
        return "ready" if int(remaining) > 0 else "attention"
    except (TypeError, ValueError):
        return "attention"


def _high_quota_fallback_models(quota: dict) -> list[str]:
    if not isinstance(quota, dict):
        return []
    routing_policy = quota.get("routing_policy")
    if not isinstance(routing_policy, dict):
        return []
    return [
        model
        for model in (_text(item) for item in routing_policy.get("high_quota_fallback_models") or [])
        if model
    ]


def _failure_label(category: str, failure: dict) -> str:
    summary = _text(failure.get("error_summary"))
    if summary:
        return summary
    labels = {
        "quota": "AI 額度限制",
        "task_queue": "Queue 或 Worker 異常",
        "external_config": "外部配置缺失",
        "data_source": "資料源異常",
        "runtime_storage": "本機儲存異常",
        "vector_store": "向量庫異常",
    }
    return labels.get(category, "任務失敗待確認")


def _failure_detail(category: str, retryable: bool) -> str:
    details = {
        "quota": "AI 額度或速率限制曾擋下任務；等額度恢復或切換 fallback 後可重試。",
        "task_queue": "Redis/Celery queue 或 worker 異常曾擋下任務；修復後再重送。",
        "external_config": "外部服務或文件後援設定缺失；補齊設定後再重送。",
        "data_source": "市場資料、公司文件或新聞來源異常；可縮小範圍或重刷快取後重試。",
        "runtime_storage": "本機檔案或資料庫儲存異常；確認權限與路徑後再重送。",
        "vector_store": "RAG/Chroma 向量庫或 embedding 相容性需檢查。",
    }
    if category in details:
        return details[category]
    if retryable:
        return "任務曾失敗但可重試；請檢查錯誤內容後重新送出。"
    return "任務曾失敗且需要人工確認；請檢查錯誤內容後處理。"


def _text(value: Any, *, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default
