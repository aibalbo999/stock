from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

import requests
import streamlit as st

from app.ui.api_client import api_get, request_error_message


def load_api_json_or_default(
    path: str,
    fallback: Any,
    *,
    error_message: str,
    timeout: float | None = None,
    notify: Literal["error", "warning", "none"] = "error",
) -> Any:
    try:
        if timeout is None:
            return api_get(path)
        return api_get(path, timeout=timeout)
    except requests.RequestException as exc:
        _notify_api_load_error(
            f"{error_message}：{request_error_message(exc)}",
            notify=notify,
        )
        return deepcopy(fallback)


def _notify_api_load_error(
    message: str,
    *,
    notify: Literal["error", "warning", "none"],
) -> None:
    if notify == "error":
        st.error(message)
    elif notify == "warning":
        st.warning(message)
