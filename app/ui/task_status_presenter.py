from __future__ import annotations

import json

from app.ui.task_failure_diagnostics import (
    task_failure_next_action_text,
    task_failure_operation_label,
    task_failure_retry_kind_label,
)


TASK_STATUS_QUEUED_POLL_SECONDS = 8
TASK_STATUS_RETRY_POLL_SECONDS = 15

TASK_STATUS_LABELS = {
    "PENDING": "等待中",
    "QUEUED": "排隊中",
    "RECEIVED": "已接收",
    "STARTED": "執行中",
    "RETRY": "等待重試",
    "SUCCESS": "成功",
    "FAILURE": "失敗",
    "REVOKED": "已取消",
}

RUN_STATUS_LABELS = {
    "pending": "等待中",
    "queued": "排隊中",
    "running": "執行中",
    "started": "執行中",
    "retry": "等待重試",
    "completed": "完成",
    "success": "成功",
    "successful": "成功",
    "failed": "失敗",
    "failure": "失敗",
    "cancelled": "已取消",
    "canceled": "已取消",
    "revoked": "已取消",
}

RUN_SOURCE_LABELS = {
    "celery_data_operation": "資料補強背景任務",
    "celery_report_generation": "報告生成背景任務",
    "celery_maintenance_cleanup": "維護清理背景任務",
    "celery_maintenance_operation": "維護操作背景任務",
    "celery_maintenance_diagnostic": "維護診斷背景任務",
}

TASK_PROGRESS_STEP_LABELS = {
    "waiting_for_worker": "等待背景執行器",
    "worker_started": "背景執行器已接手",
    "task_retrying": "任務重試中",
    "task_completed": "任務完成",
    "task_failed": "任務失敗",
    "task_cancelled": "任務已取消",
    "fetch_market_data": "抓取市場資料",
    "market_data_refresh": "刷新市場資料",
}


def task_action_preflight_summary(
    task_status: dict,
    *,
    action: str,
    confirmed: bool,
) -> dict[str, str]:
    action_key = str(action or "").strip().casefold()
    task_id = str(task_status.get("task_id") or "-")
    status = task_status_state_label(task_status.get("status") or "UNKNOWN")
    operation = task_status_operation_label(task_status)
    detail_parts = [
        f"任務編號 {task_id}",
        f"狀態 {status}",
        f"操作 {operation}",
    ]

    if action_key == "retry":
        retry_kind = task_failure_retry_kind_label(task_status.get("retry_kind"))
        detail = "｜".join([*detail_parts, f"重試類型 {retry_kind}"])
        if task_status.get("retryable") is False:
            next_step = task_failure_next_action_text(task_status)
            return {
                "state": "blocked",
                "label": "任務操作摘要",
                "title": "此任務不支援一鍵重試",
                "detail": detail,
                "next_step": next_step
                or "請依失敗診斷修正輸入或外部設定後，從原本入口重新送出。",
                "impact": "尚未送出重試；先修正輸入、白名單或外部設定，避免重複失敗與額度浪費。",
            }
        if _task_status_successful(task_status):
            return {
                "state": "blocked",
                "label": "任務操作摘要",
                "title": "此任務已成功，不需要一鍵重試",
                "detail": detail,
                "next_step": "若需要重新執行，請回原本功能入口建立新任務。",
                "impact": "不會送出重試；避免對已成功任務重複消耗模型、外部資料源或 API 額度。",
            }
        if not _task_status_ready(task_status):
            return {
                "state": "blocked",
                "label": "任務操作摘要",
                "title": "此任務仍在執行，不能重試",
                "detail": detail,
                "next_step": "等待任務結束後，再依結果決定是否需要重試。",
                "impact": "不會送出重試；避免同一任務尚未完成時重複排隊。",
            }
        if not confirmed:
            return {
                "state": "attention",
                "label": "任務操作摘要",
                "title": "準備重試背景任務",
                "detail": detail,
                "next_step": "勾選確認後，再按「重試任務」重新送出背景任務。",
                "impact": "會重新排隊並可能再次消耗模型、外部資料源或 API 額度；若錯誤類型是 quota，建議先確認額度是否恢復。",
            }
        return {
            "state": "ready",
            "label": "任務操作摘要",
            "title": "可以重試背景任務",
            "detail": detail,
            "next_step": "按「重試任務」重新送出；送出後請查看新的任務編號與輪詢狀態。",
            "impact": "會重新排隊並可能再次消耗模型、外部資料源或 API 額度；完成前避免重複按重試。",
        }

    detail = "｜".join(detail_parts)
    if _task_status_ready(task_status):
        return {
            "state": "blocked",
            "label": "任務操作摘要",
            "title": "此任務已結束，不能取消",
            "detail": detail,
            "next_step": "不需取消；若結果失敗且支援重試，請使用重試或回原入口重新送出。",
            "impact": "不會送出取消要求；避免改動已完成任務紀錄。",
        }
    if not confirmed:
        return {
            "state": "attention",
            "label": "任務操作摘要",
            "title": "準備取消背景任務",
            "detail": detail,
            "next_step": "勾選確認後，再按「取消任務」送出取消要求。",
            "impact": "取消要求會寫入任務紀錄；若背景執行器已完成，可能只會留下取消請求紀錄。",
        }
    return {
        "state": "ready",
        "label": "任務操作摘要",
        "title": "可以送出取消要求",
        "detail": detail,
        "next_step": "按「取消任務」通知背景任務停止；取消後請刷新狀態確認是否已停止。",
        "impact": "取消要求會寫入任務紀錄；若背景執行器已完成，可能只會留下取消請求紀錄。",
    }


def task_status_operation_label(task_status: dict | None) -> str:
    if not isinstance(task_status, dict):
        return "-"

    for value in (
        task_status.get("operation"),
        _nested_text(task_status.get("execution_context"), "operation"),
    ):
        label = _task_operation_display_label(value)
        if label:
            return label

    run = task_status.get("run")
    if isinstance(run, dict):
        payload = _task_run_payload(run)
        for key in ("operation", "task", "workflow_name"):
            label = _task_operation_display_label(payload.get(key))
            if label:
                return label

        workflow = run.get("workflow")
        label = _task_operation_display_label(_nested_text(workflow, "name"))
        if label:
            return label

    for value in (
        _nested_text(task_status.get("execution_context"), "run_source"),
        _nested_text(run, "source") if isinstance(run, dict) else None,
    ):
        raw_source = _clean_task_operation_text(value)
        if raw_source:
            return task_failure_operation_label(_operator_operation_from_source(raw_source))

    return "-"


def task_status_state_label(value: object) -> str:
    text = str(value or "").strip()
    if not text or text == "-":
        return "-"
    return TASK_STATUS_LABELS.get(text.upper(), text)


def task_run_status_label(value: object) -> str:
    text = str(value or "").strip()
    if not text or text == "-":
        return "-"
    return RUN_STATUS_LABELS.get(text.casefold(), task_status_state_label(text))


def task_run_source_label(value: object) -> str:
    text = str(value or "").strip()
    if not text or text == "-":
        return "-"
    label = RUN_SOURCE_LABELS.get(text)
    if label:
        return label
    if text.startswith("celery_"):
        return f"{task_failure_operation_label(text.removeprefix('celery_'))}背景任務"
    return text


def task_status_progress_step_label(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "等待中"
    return TASK_PROGRESS_STEP_LABELS.get(text, text)


def task_status_poll_interval_seconds(
    task_status: dict | None,
    *,
    default_seconds: int,
) -> int:
    interval = max(1, int(default_seconds or 5))
    if _task_status_ready(task_status):
        return interval
    status = str((task_status or {}).get("status") or "").upper()
    progress = (task_status or {}).get("progress")
    progress_pct = progress.get("progress_pct") if isinstance(progress, dict) else None
    if isinstance(progress_pct, (int, float)) and progress_pct > 0:
        return interval
    if status in {"PENDING", "QUEUED", "RECEIVED"}:
        return max(interval, TASK_STATUS_QUEUED_POLL_SECONDS)
    if status == "RETRY":
        return max(interval, TASK_STATUS_RETRY_POLL_SECONDS)
    return interval


def task_status_poll_caption(
    task_status: dict | None,
    *,
    auto_refresh: bool,
    fragment_supported: bool,
    default_seconds: int,
) -> str:
    if _task_status_ready(task_status):
        return "狀態輪詢：任務已結束，自動刷新停止。"
    if not auto_refresh:
        return "狀態輪詢：已暫停。"
    if not fragment_supported:
        return "狀態輪詢：目前環境不支援自動刷新。"

    interval = task_status_poll_interval_seconds(
        task_status,
        default_seconds=default_seconds,
    )
    status = str((task_status or {}).get("status") or "").upper()
    progress = (task_status or {}).get("progress")
    progress_pct = progress.get("progress_pct") if isinstance(progress, dict) else None
    if status in {"PENDING", "QUEUED", "RECEIVED"}:
        reason = "排隊中"
    elif status == "RETRY":
        reason = "等待重試"
    elif isinstance(progress_pct, (int, float)) and progress_pct > 0:
        reason = "執行中"
    else:
        reason = "處理中"
    return f"狀態輪詢：約每 {interval} 秒更新，{reason}。"


def _task_status_ready(task_status: dict | None) -> bool:
    if not isinstance(task_status, dict):
        return False
    return bool(task_status.get("ready")) or str(task_status.get("status") or "").upper() in {
        "SUCCESS",
        "FAILURE",
        "REVOKED",
    }


def _task_status_successful(task_status: dict | None) -> bool:
    if not isinstance(task_status, dict):
        return False
    return bool(task_status.get("successful")) or str(task_status.get("status") or "").upper() == (
        "SUCCESS"
    )


def _nested_text(value: object, key: str) -> object:
    if isinstance(value, dict):
        return value.get(key)
    return None


def _clean_task_operation_text(value: object) -> str:
    text = str(value or "").strip()
    if not text or text in {"-", "unknown", "UNKNOWN"}:
        return ""
    return text


def _task_operation_display_label(value: object) -> str:
    text = _clean_task_operation_text(value)
    if not text:
        return ""
    return task_failure_operation_label(text)


def _task_run_payload(run: dict) -> dict:
    for key in ("payload", "payload_json"):
        raw_payload = run.get(key)
        if isinstance(raw_payload, dict):
            return raw_payload
        if not isinstance(raw_payload, str):
            continue
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _operator_operation_from_source(source: str) -> str:
    if source.startswith("celery_"):
        return source.removeprefix("celery_")
    return source
