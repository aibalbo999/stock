from __future__ import annotations

from copy import deepcopy
from typing import Any

import requests
import streamlit as st

from app.ui.api_client import api_get, request_error_message


def load_api_json_or_default(
    path: str,
    fallback: Any,
    *,
    error_message: str,
    timeout: float | None = None,
) -> Any:
    try:
        if timeout is None:
            return api_get(path)
        return api_get(path, timeout=timeout)
    except requests.RequestException as exc:
        st.error(f"{error_message}：{request_error_message(exc)}")
        return deepcopy(fallback)
