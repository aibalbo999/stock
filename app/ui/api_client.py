from __future__ import annotations

from typing import Any

import requests

from app.core.config import get_settings


API_BASE_URL = get_settings().api_base_url.rstrip("/")
API_GET_TIMEOUT_SECONDS = 10
API_WRITE_TIMEOUT_SECONDS = 60
API_TASK_QUEUE_TIMEOUT_SECONDS = 20
API_TASK_PREFLIGHT_TIMEOUT_SECONDS = 3


def api_post(path: str, payload: dict, *, timeout: float = API_WRITE_TIMEOUT_SECONDS) -> dict:
    response = requests.post(f"{API_BASE_URL}{path}", json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def api_task_post(path: str, payload: dict) -> dict:
    return api_post(path, payload, timeout=API_TASK_QUEUE_TIMEOUT_SECONDS)


def api_put(path: str, payload: dict) -> dict:
    response = requests.put(f"{API_BASE_URL}{path}", json=payload, timeout=API_WRITE_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def api_delete(path: str) -> dict:
    response = requests.delete(f"{API_BASE_URL}{path}", timeout=API_WRITE_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def api_get(path: str, *, timeout: float = API_GET_TIMEOUT_SECONDS) -> Any:
    response = requests.get(f"{API_BASE_URL}{path}", timeout=timeout)
    response.raise_for_status()
    return response.json()


def request_error_message(exc: requests.RequestException) -> str:
    response = getattr(exc, "response", None)
    if response is None:
        return str(exc)
    try:
        payload = response.json()
    except ValueError:
        return str(exc)
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        message = str(detail.get("message") or detail.get("code") or exc)
        diagnostic_message = _request_diagnostic_message(detail)
        context_message = _request_context_message(detail.get("context"))
        next_steps = [str(step) for step in detail.get("next_steps") or [] if str(step).strip()]
        if diagnostic_message:
            message = f"{message} {diagnostic_message}"
        if context_message:
            message = f"{message} 診斷：{context_message}"
        if next_steps:
            return f"{message} 建議：" + "；".join(next_steps)
        return message
    if isinstance(detail, str) and detail:
        return detail
    return str(exc)


def _request_diagnostic_message(detail: dict) -> str:
    summary = str(detail.get("error_summary") or "").strip()
    category = str(detail.get("error_category") or "").strip()
    severity = str(detail.get("error_severity") or "").strip()
    if not (summary or category or severity):
        return ""
    if category or severity:
        suffix = "/".join(item for item in (category, severity) if item)
        if summary:
            return f"分類：{summary}（{suffix}）"
        return f"分類：{suffix}"
    return f"分類：{summary}"


def _request_context_message(context: object) -> str:
    if not isinstance(context, dict):
        return ""
    parts = []
    operation = str(context.get("operation") or "").strip()
    if operation:
        parts.append(f"操作：{operation}")
    tickers = [str(ticker).strip() for ticker in context.get("tickers") or [] if str(ticker).strip()]
    ticker_count = _safe_int(context.get("ticker_count"), default=len(tickers))
    if tickers:
        suffix = f"（{ticker_count} 檔）" if ticker_count else ""
        parts.append(f"股票：{', '.join(tickers)}{suffix}")
    elif ticker_count:
        parts.append(f"股票數：{ticker_count}")
    start_date = str(context.get("start_date") or "").strip()
    end_date = str(context.get("end_date") or "").strip()
    if start_date or end_date:
        parts.append(f"期間：{start_date or '?'} 至 {end_date or '?'}")
    provider_hint = str(context.get("provider_hint") or "").strip()
    if provider_hint:
        parts.append(f"資料源：{provider_hint}")
    failure_stage = str(context.get("failure_stage") or "").strip()
    if failure_stage:
        parts.append(f"階段：{failure_stage}")
    return "；".join(parts)


def _safe_int(value: object, *, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def queue_data_operation(operation: str, payload: dict) -> dict:
    return api_task_post(
        "/tasks/data-operation",
        {
            "operation": operation,
            "payload": payload,
        },
    )


def api_task_queue_status() -> dict:
    snapshot = api_get("/services/status", timeout=API_TASK_PREFLIGHT_TIMEOUT_SECONDS)
    task_queue = snapshot.get("task_queue") if isinstance(snapshot, dict) else None
    return task_queue if isinstance(task_queue, dict) else {}


def task_payload_dates(start_date: Any, end_date: Any) -> dict:
    return {
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
    }
