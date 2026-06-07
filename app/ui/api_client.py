from __future__ import annotations

from typing import Any

import requests

from app.core.config import get_settings


API_BASE_URL = get_settings().api_base_url.rstrip("/")
API_GET_TIMEOUT_SECONDS = 10
API_WRITE_TIMEOUT_SECONDS = 60
API_TASK_QUEUE_TIMEOUT_SECONDS = 20


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


def api_get(path: str) -> Any:
    response = requests.get(f"{API_BASE_URL}{path}", timeout=API_GET_TIMEOUT_SECONDS)
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
        next_steps = [str(step) for step in detail.get("next_steps") or [] if str(step).strip()]
        if next_steps:
            return f"{message} 建議：" + "；".join(next_steps)
        return message
    if isinstance(detail, str) and detail:
        return detail
    return str(exc)


def queue_data_operation(operation: str, payload: dict) -> dict:
    return api_task_post(
        "/tasks/data-operation",
        {
            "operation": operation,
            "payload": payload,
        },
    )


def task_payload_dates(start_date: Any, end_date: Any) -> dict:
    return {
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
    }
