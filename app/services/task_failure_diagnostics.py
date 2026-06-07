from __future__ import annotations

import json
from typing import Any


DATA_OPERATION_TASKS = {
    "market_refresh",
    "fundamentals_refresh",
    "valuation_refresh",
    "company_filings_fetch",
    "company_filing_from_url",
    "feed_fetch",
}


TASK_FAILURE_CATEGORIES = {
    "quota": {
        "severity": "warning",
        "summary": "模型/API 額度或速率限制",
        "keywords": (
            "resource_exhausted",
            "quota",
            "rate limit",
            "rate_limit",
            "429",
            "daily limit",
            "exhausted",
        ),
        "next_steps": [
            "查看 AI 額度與模型路由或資料源額度。",
            "等待額度重置，或改用已設定的 fallback 模型/資料源後再重試。",
        ],
    },
    "task_queue": {
        "severity": "error",
        "summary": "Redis/Celery queue 或 worker 異常",
        "keywords": (
            "redis",
            "celery",
            "broker",
            "backend",
            "kombu",
            "worker",
            "task queue",
            "connection refused",
        ),
        "next_steps": [
            "確認 /services/status 的 task_queue.ready 與 worker_online。",
            "執行 Celery inspect ping 或重新啟動 Redis/Celery worker。",
        ],
    },
    "payload_validation": {
        "severity": "error",
        "summary": "任務 payload 驗證失敗",
        "keywords": (
            "validation",
            "pydantic",
            "unsupported",
            "invalid",
            "whitelist",
            "missing required",
            "not retryable",
        ),
        "next_steps": [
            "檢查任務 payload、股票白名單與必要欄位。",
            "修正輸入後重新送出任務。",
        ],
    },
    "timeout": {
        "severity": "warning",
        "summary": "外部呼叫或任務執行逾時",
        "keywords": (
            "timeout",
            "timed out",
            "readtimeout",
            "connecttimeout",
            "deadline",
        ),
        "next_steps": [
            "降低單次批次大小或縮小股票/文件範圍。",
            "確認外部資料源與網路狀態後再重試。",
        ],
    },
    "data_source": {
        "severity": "warning",
        "summary": "市場資料、公司文件或新聞來源異常",
        "keywords": (
            "finmind",
            "fugle",
            "twse",
            "tpex",
            "mops",
            "company filing",
            "filing",
            "market data",
            "rss",
            "feed",
            "http 403",
            "http 404",
            "captcha",
        ),
        "next_steps": [
            "檢查資料源 token、日期範圍與 company filing 後援設定。",
            "可先重刷快取或降低本次資料補強範圍。",
        ],
    },
}


def parse_payload(payload_json: str | None) -> dict:
    if not payload_json:
        return {}
    try:
        payload = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def serialized_run_payload(run: dict) -> dict:
    raw_payload = run.get("payload")
    if isinstance(raw_payload, dict):
        return raw_payload
    if isinstance(raw_payload, str):
        return parse_payload(raw_payload)
    return {}


def run_source(run: dict | Any) -> str:
    if isinstance(run, dict):
        return str(run.get("source") or "")
    return str(getattr(run, "source", "") or "")


def run_operation(payload: dict, run: dict | Any) -> str:
    for key in ("operation", "task", "workflow_name"):
        value = payload.get(key)
        if value:
            return str(value)
    workflow = run.get("workflow") if isinstance(run, dict) and isinstance(run.get("workflow"), dict) else {}
    if workflow.get("name"):
        return str(workflow["name"])
    return run_source(run) or "unknown"


def run_retry_kind(payload: dict, run: dict | Any) -> str | None:
    source = run_source(run)
    task_name = str(payload.get("task") or "")
    if task_name == "after_close_report_update":
        return None
    if task_name == "data_operation" or source == "celery_data_operation":
        operation = str(payload.get("operation") or "")
        return "data_operation" if operation in DATA_OPERATION_TASKS else None
    if payload.get("source_report_id") is not None:
        return "report_follow_up"
    request_payload = payload.get("request") if isinstance(payload.get("request"), dict) else payload
    if isinstance(request_payload, dict) and request_payload.get("topic"):
        return "report_generation"
    return None


def first_next_step(diagnostic: dict | None) -> str | None:
    if not isinstance(diagnostic, dict):
        return None
    next_steps = diagnostic.get("next_steps")
    if not isinstance(next_steps, list) or not next_steps:
        return None
    first = str(next_steps[0]).strip()
    return first or None


def task_next_action(
    *,
    status: str,
    task_id: object,
    retry_kind: str | None,
    error: object,
    diagnostic: dict | None = None,
) -> str:
    first_step = first_next_step(diagnostic)
    if retry_kind and task_id:
        suffix = f"；{first_step}" if first_step else ""
        return "可從維護頁重試，或呼叫 " + f"POST /tasks/{task_id}/retry{suffix}"
    if not task_id:
        return "缺少 celery_task_id；請從 run 明細檢查原始 payload。"
    if status in {"failed", "cancelled"} or error:
        suffix = f"；{first_step}" if first_step else ""
        return f"payload 不支援自動重試；請依錯誤內容手動重新送出。{suffix}"
    return "持續觀測任務狀態。"


def task_failure_diagnostic(
    *,
    status: str,
    error: object,
    operation: str,
    retryable: bool,
) -> dict:
    normalized_status = str(status or "").casefold()
    error_text = str(error or "").strip()
    if normalized_status not in {"failed", "cancelled"} and not error_text:
        return {"category": None, "severity": None, "summary": None, "next_steps": []}
    if normalized_status == "cancelled":
        return {
            "category": "cancelled",
            "severity": "info",
            "summary": "任務已取消",
            "next_steps": ["確認是否需要重新送出；若為誤取消，可從原工作流程重新啟動。"],
        }
    text = f"{operation} {normalized_status} {error_text}".casefold()
    for category, config in TASK_FAILURE_CATEGORIES.items():
        if any(keyword in text for keyword in config["keywords"]):
            return {
                "category": category,
                "severity": config["severity"],
                "summary": config["summary"],
                "next_steps": list(config["next_steps"]),
            }
    return {
        "category": "unknown",
        "severity": "warning" if retryable else "error",
        "summary": "未分類任務失敗",
        "next_steps": [
            "查看任務狀態 drilldown 與 run payload。",
            "若錯誤可重現，補上錯誤分類規則或手動重新送出。",
        ],
    }


def task_failure_diagnostic_payload(
    *,
    run_id: int | None,
    source: str,
    payload: dict,
    status: str,
    error: object,
) -> dict:
    run_ref = {"id": run_id, "source": source}
    operation = run_operation(payload, run_ref)
    task_id = payload.get("celery_task_id")
    retry_kind = run_retry_kind(payload, run_ref)
    retryable = bool(task_id and retry_kind)
    diagnostic = task_failure_diagnostic(
        status=status,
        error=error,
        operation=operation,
        retryable=retryable,
    )
    if not diagnostic.get("category"):
        return {}
    return {
        "operation": operation,
        "error_category": diagnostic.get("category"),
        "error_severity": diagnostic.get("severity"),
        "error_summary": diagnostic.get("summary"),
        "next_steps": diagnostic.get("next_steps") or [],
        "retryable": retryable,
        "retry_kind": retry_kind,
        "retry_endpoint": f"POST /tasks/{task_id}/retry" if retryable else None,
        "status_endpoint": f"GET /tasks/{task_id}" if task_id else None,
        "run_endpoint": f"GET /runs/{run_id}" if run_id else None,
        "next_action": task_next_action(
            status=status,
            task_id=task_id,
            retry_kind=retry_kind,
            error=error,
            diagnostic=diagnostic,
        ),
    }
