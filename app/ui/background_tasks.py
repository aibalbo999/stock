from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import requests
import streamlit as st

from app.ui.api_client import (
    api_task_post,
    api_task_queue_status,
    queue_data_operation,
    request_error_message,
)


TaskSubmitter = Callable[[], dict]


def submit_background_task(
    submitter: TaskSubmitter,
    *,
    task_state_key: str,
    status_state_keys: Sequence[str] = (),
    success_message: str,
    error_message: str,
    task_type_state_key: str | None = None,
    task_type: str | None = None,
    preflight: bool = False,
) -> dict | None:
    if preflight and not task_queue_preflight_ready(error_message=error_message):
        return None
    try:
        task_response = submitter()
    except requests.RequestException as exc:
        st.error(f"{error_message}：{request_error_message(exc)}")
        return None

    task_id = _task_id(task_response)
    if not task_id:
        st.error(f"{error_message}：API 回傳缺少 task_id。")
        return None

    st.session_state[task_state_key] = task_id
    if task_type_state_key and task_type:
        st.session_state[task_type_state_key] = task_type
    for status_state_key in status_state_keys:
        st.session_state.pop(status_state_key, None)
    st.success(f"{success_message}：{task_id}")
    return task_response


def submit_api_task(
    path: str,
    payload: dict,
    *,
    task_state_key: str,
    status_state_keys: Sequence[str] = (),
    success_message: str,
    error_message: str,
    task_type_state_key: str | None = None,
    task_type: str | None = None,
    preflight: bool = True,
) -> dict | None:
    return submit_background_task(
        lambda: api_task_post(path, payload),
        task_state_key=task_state_key,
        status_state_keys=status_state_keys,
        success_message=success_message,
        error_message=error_message,
        task_type_state_key=task_type_state_key,
        task_type=task_type,
        preflight=preflight,
    )


def submit_data_operation_task(
    operation: str,
    payload: dict,
    *,
    task_state_key: str = "last_data_task_id",
    status_state_keys: Sequence[str] = (),
    success_message: str,
    error_message: str,
    preflight: bool = True,
) -> dict | None:
    return submit_background_task(
        lambda: queue_data_operation(operation, payload),
        task_state_key=task_state_key,
        status_state_keys=status_state_keys,
        success_message=success_message,
        error_message=error_message,
        preflight=preflight,
    )


def task_queue_preflight_ready(*, error_message: str) -> bool:
    try:
        task_queue = api_task_queue_status()
    except requests.RequestException as exc:
        st.warning(f"無法預先確認背景任務狀態：{request_error_message(exc)}；仍會嘗試送出。")
        return True
    if task_queue.get("ready"):
        worker_warning = task_queue_worker_warning(task_queue)
        if worker_warning:
            st.warning(worker_warning)
        return True
    st.error(f"{error_message}：{task_queue_unready_message(task_queue)}")
    return False


def task_queue_unready_message(task_queue: dict) -> str:
    reasons = []
    if not task_queue.get("broker_configured"):
        reasons.append("Redis broker 尚未設定")
    if not task_queue.get("broker_ok"):
        reasons.append("Redis broker/backend 未連線")
    if task_queue.get("worker_ping_checked") and not task_queue.get("worker_online"):
        reasons.append("Celery worker 未回應")
    if not task_queue.get("celery_app_available"):
        reasons.append("Celery app 匯出不可用")
    missing_exports = task_queue.get("missing_task_exports") or []
    if missing_exports:
        reasons.append("缺少 task 匯出：" + "、".join(str(item) for item in missing_exports))
    if not task_queue.get("task_names_match_expected", True):
        reasons.append("Celery task 名稱與 API wiring 不一致")
    if not task_queue.get("submission_contract_ready", True) and not reasons:
        reasons.append("背景任務提交契約尚未就緒")
    if not reasons:
        reasons.append("背景任務 queue 尚未就緒")
    smoke_commands = task_queue.get("smoke_commands") or []
    hint = f" 可用指令：{smoke_commands[0]}" if smoke_commands else ""
    return "；".join(reasons) + "。" + hint


def task_queue_worker_warning(task_queue: dict) -> str:
    if not task_queue.get("worker_ping_checked") or task_queue.get("worker_online"):
        return ""
    if task_queue.get("worker_ping_error"):
        detail = f"；錯誤：{task_queue['worker_ping_error']}"
    else:
        detail = ""
    smoke_commands = task_queue.get("smoke_commands") or []
    hint = f" 可用指令：{smoke_commands[0]}" if smoke_commands else ""
    return f"背景任務 queue 可送出，但 Celery worker 未回應，任務可能會排隊等待{detail}。{hint}"


def _task_id(task_response: Any) -> str:
    if not isinstance(task_response, dict):
        return ""
    return str(task_response.get("task_id") or "").strip()
