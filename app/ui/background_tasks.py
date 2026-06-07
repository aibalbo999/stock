from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import requests
import streamlit as st

from app.ui.api_client import api_task_post, queue_data_operation, request_error_message


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
) -> dict | None:
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
) -> dict | None:
    return submit_background_task(
        lambda: api_task_post(path, payload),
        task_state_key=task_state_key,
        status_state_keys=status_state_keys,
        success_message=success_message,
        error_message=error_message,
        task_type_state_key=task_type_state_key,
        task_type=task_type,
    )


def submit_data_operation_task(
    operation: str,
    payload: dict,
    *,
    task_state_key: str = "last_data_task_id",
    status_state_keys: Sequence[str] = (),
    success_message: str,
    error_message: str,
) -> dict | None:
    return submit_background_task(
        lambda: queue_data_operation(operation, payload),
        task_state_key=task_state_key,
        status_state_keys=status_state_keys,
        success_message=success_message,
        error_message=error_message,
    )


def _task_id(task_response: Any) -> str:
    if not isinstance(task_response, dict):
        return ""
    return str(task_response.get("task_id") or "").strip()
