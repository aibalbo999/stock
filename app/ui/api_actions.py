from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

import requests
import streamlit as st

from app.ui.api_client import request_error_message

T = TypeVar("T")
ErrorNotifier = Callable[[str], None]


def run_api_action_or_none(
    action: Callable[[], T],
    *,
    error_message: str,
    error_notifier: ErrorNotifier | None = None,
) -> T | None:
    notify_error = error_notifier or st.error
    try:
        return action()
    except ValueError as exc:
        notify_error(f"{error_message}：{exc}")
    except requests.RequestException as exc:
        notify_error(f"{error_message}：{request_error_message(exc)}")
    return None
