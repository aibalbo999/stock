from __future__ import annotations

from typing import Any


READY_OVERALL = {"state": "ready", "label": "可執行", "detail": "背景任務與最新版報告都可用。"}

PAYLOAD_VALIDATION_DETAIL = "補強或重跑任務曾被 payload 驗證擋下；修正後可重試。"
RUNNING_TASK_DETAIL = "背景任務正在處理；完成前先等待結果，不要重複送出同類任務。"


def operator_status_overall(
    service_snapshot: dict, task_summary: dict, reports: list[dict]
) -> dict[str, str]:
    if service_status_unavailable(service_snapshot):
        return {
            "state": "attention",
            "label": "系統狀態暫不可讀",
            "detail": "目前無法讀取 /services/status；請到維護頁確認 API 與背景任務狀態。",
        }

    task_queue = _task_queue_from_snapshot(service_snapshot)
    totals = _dict_value(task_summary.get("totals") if isinstance(task_summary, dict) else None)
    if not _queue_ready(task_queue):
        return {
            "state": "blocked",
            "label": "背景任務未就緒",
            "detail": "請先到系統設定檢查 Redis/Celery worker。",
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
                "無法讀取 /services/status"
                if service_status_missing
                else "Worker 線上，最新任務執行中"
                if queue_running
                else "Worker 線上"
                if task_queue.get("worker_online")
                else "Worker 離線"
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


def quota_operator_summary(quota: dict) -> dict[str, str]:
    recommended_model = _text(quota.get("recommended_model"), default="-")
    recommended_row = _recommended_quota_row(quota, recommended_model)
    remaining = _quota_remaining_text(recommended_row)
    state = _quota_state(recommended_row)
    model_order_label = _model_order_label(quota)
    limited_model_label = _limited_model_label(_first_limited_quota_model(quota))
    fallback_models = _high_quota_fallback_models(quota)
    high_quota_fallback_label = (
        "高額度保底：" + "、".join(fallback_models) if fallback_models else "無高額度保底模型"
    )
    next_model_label = _next_quota_model_label(quota, recommended_model)
    operator_caption = _quota_operator_card_caption(
        remaining=remaining,
        next_model_label=next_model_label,
        limited_model_label=limited_model_label,
        high_quota_fallback_models=fallback_models,
    )
    caption = "｜".join(
        label for label in [model_order_label, limited_model_label, high_quota_fallback_label] if label
    )
    return {
        "recommended_model": recommended_model,
        "remaining": remaining,
        "state": state,
        "model_order_label": model_order_label,
        "limited_model_label": limited_model_label,
        "high_quota_fallback_label": high_quota_fallback_label,
        "next_model_label": next_model_label,
        "operator_caption": operator_caption,
        "caption": caption,
    }


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
    return status in {"success", "successful", "succeeded", "completed", "done"} or celery_status in {
        "success",
        "successful",
        "succeeded",
    }


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


def _latest_task_successful(task_summary: dict) -> bool:
    return _task_successful(_latest_task(task_summary))


def _latest_task_running(task_summary: dict) -> bool:
    return _task_running(_latest_task(task_summary))


def _latest_task_failed(task_summary: dict) -> bool:
    return _task_failed(_latest_task(task_summary))


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
    failure_rows: list[dict] = []
    seen = set()

    explicit_failures = task_summary.get("recent_failures")
    if isinstance(explicit_failures, list):
        for failure in explicit_failures:
            if not isinstance(failure, dict):
                continue
            seen.add(_failure_identity(failure))
            failure_rows.append(failure)

    recent = task_summary.get("recent")
    if isinstance(recent, list):
        for row in recent:
            if not isinstance(row, dict) or not _task_failed(row):
                continue
            identity = _failure_identity(row)
            if identity in seen:
                continue
            seen.add(identity)
            failure_rows.append(row)
    return failure_rows


def _first_failure(task_summary: dict) -> dict:
    failures = _recent_failures(task_summary)
    return failures[0] if failures else {}


def _task_failed(task: dict) -> bool:
    status = _text(task.get("status")).casefold()
    celery_status = _text(task.get("celery_status")).casefold()
    if status in {"failed", "failure", "cancelled", "error"}:
        return True
    if celery_status in {"failed", "failure", "revoked"}:
        return True
    return bool(task.get("error") or task.get("error_category"))


def _failure_identity(failure: dict) -> tuple[str, str]:
    task_id = _text(failure.get("task_id"))
    if task_id:
        return ("task", task_id)
    run_id = _text(failure.get("id"))
    if run_id:
        return ("run", run_id)
    return ("row", repr(sorted(failure.items())))


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
            "detail": "目前無法讀取 /tasks/summary；不代表沒有失敗任務。",
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


def _recommended_quota_row(quota: dict, recommended_model: str) -> dict:
    if not isinstance(quota, dict):
        return {}
    for row in quota.get("models") or []:
        if not isinstance(row, dict):
            continue
        if _text(row.get("model")) == recommended_model:
            return row
    return {}


def _quota_remaining_text(model_row: dict) -> str:
    remaining = model_row.get("requests_remaining") if isinstance(model_row, dict) else None
    budget = model_row.get("request_budget") if isinstance(model_row, dict) else None
    if remaining in {None, ""} or budget in {None, ""}:
        return "額度未追蹤"
    return f"{remaining} / {budget}"


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
    model_rows = quota.get("models")
    if isinstance(model_rows, list):
        models = [
            _text(row.get("model"))
            for row in model_rows
            if isinstance(row, dict)
            and _text(row.get("routing_tier")) == "high_quota_fallback"
        ]
        models = [model for model in models if model]
        if models:
            return models

    routing_policy = quota.get("routing_policy")
    if not isinstance(routing_policy, dict):
        return []
    return [
        model
        for model in (_text(item) for item in routing_policy.get("high_quota_fallback_models") or [])
        if model
    ]


def _next_quota_model_label(quota: dict, recommended_model: str) -> str:
    models = _model_order(quota)
    if not recommended_model or recommended_model not in models:
        return ""
    next_index = models.index(recommended_model) + 1
    if next_index >= len(models):
        return ""
    return f"下一順位 {models[next_index]}"


def _quota_operator_card_caption(
    *,
    remaining: str,
    next_model_label: str,
    limited_model_label: str,
    high_quota_fallback_models: list[str],
) -> str:
    remaining_label = (
        f"免費額度 {remaining}" if remaining and remaining != "額度未追蹤" else "額度未追蹤"
    )
    labels = ["聰明優先", remaining_label]
    if next_model_label:
        labels.append(next_model_label)
    if limited_model_label and limited_model_label != "受限：無":
        labels.append(limited_model_label)
    if high_quota_fallback_models:
        labels.append("保底 " + "、".join(high_quota_fallback_models))
    return "｜".join(labels)


def _model_order_label(quota: dict) -> str:
    models = _model_order(quota)
    if not models:
        return "順序：尚無模型順序"
    visible_models = models[:4]
    suffix = f" +{len(models) - len(visible_models)}" if len(models) > len(visible_models) else ""
    return "順序：" + " → ".join(visible_models) + suffix


def _model_order(quota: dict) -> list[str]:
    if not isinstance(quota, dict):
        return []
    explicit_order = [_text(model) for model in quota.get("model_order") or []]
    explicit_order = [model for model in explicit_order if model]
    if explicit_order:
        return list(dict.fromkeys(explicit_order))

    rows = [
        row
        for row in quota.get("models") or []
        if isinstance(row, dict) and _text(row.get("model"))
    ]
    rows.sort(key=lambda row: (_rank_value(row.get("rank")), _text(row.get("model"))))
    return list(dict.fromkeys(_text(row.get("model")) for row in rows))


def _first_limited_quota_model(quota: dict) -> dict:
    if not isinstance(quota, dict):
        return {}
    ordered_models = _model_order(quota)
    rows_by_model = {
        _text(row.get("model")): row
        for row in quota.get("models") or []
        if isinstance(row, dict) and _text(row.get("model"))
    }
    for model in ordered_models:
        row = rows_by_model.get(model, {})
        if _quota_limited_status(row):
            return row

    limited_rows = [
        row
        for row in quota.get("models") or []
        if isinstance(row, dict) and _quota_limited_status(row)
    ]
    limited_rows.sort(key=lambda row: (_rank_value(row.get("rank")), _text(row.get("model"))))
    return limited_rows[0] if limited_rows else {}


def _quota_limited_status(row: dict) -> str:
    if not isinstance(row, dict):
        return ""
    status = _text(row.get("status")).casefold()
    if status in {"exhausted", "cooldown"}:
        return status
    risk_level = _text(row.get("risk_level")).casefold()
    if risk_level in {"exhausted", "cooldown"}:
        return risk_level
    return ""


def _limited_model_label(row: dict) -> str:
    status = _quota_limited_status(row)
    if not status:
        return "受限：無"
    model = _text(row.get("model"), default="-")
    if status == "cooldown":
        seconds = _int_value(row.get("active_cooldown_seconds"))
        return f"受限：{model}（冷卻 {seconds} 秒）"
    return f"受限：{model}（耗盡）"


def _rank_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 999


def _text(value: Any, *, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
