from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

import requests
import streamlit as st

from app.ui.api_client import request_error_message

T = TypeVar("T")


def run_api_action_or_none(
    action: Callable[[], T],
    *,
    error_message: str,
) -> T | None:
    try:
        return action()
    except ValueError as exc:
        st.error(f"{error_message}：{exc}")
    except requests.RequestException as exc:
        st.error(f"{error_message}：{request_error_message(exc)}")
    return None
