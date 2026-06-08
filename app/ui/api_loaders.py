from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

import requests
import streamlit as st

from app.ui.api_client import api_get, request_error_message

ApiLoadNotify = Literal["error", "warning", "info", "none"]


def load_api_json_or_default(
    path: str,
    fallback: Any,
    *,
    error_message: str,
    timeout: float | None = None,
    notify: ApiLoadNotify = "error",
    not_found_message: str | None = None,
) -> Any:
    try:
        if timeout is None:
            return api_get(path)
        return api_get(path, timeout=timeout)
    except requests.RequestException as exc:
        if _request_status_code(exc) == 404 and not_found_message:
            _notify_api_load_error(not_found_message, notify="info")
            return deepcopy(fallback)
        _notify_api_load_error(
            f"{error_message}：{request_error_message(exc)}",
            notify=notify,
        )
        return deepcopy(fallback)


def _notify_api_load_error(
    message: str,
    *,
    notify: ApiLoadNotify,
) -> None:
    if notify == "error":
        st.error(message)
    elif notify == "warning":
        st.warning(message)
    elif notify == "info":
        st.info(message)


def _request_status_code(exc: requests.RequestException) -> int | None:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    return int(status_code) if isinstance(status_code, int) else None
