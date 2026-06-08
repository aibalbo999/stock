from __future__ import annotations

import requests
import streamlit as st

from app.ui.api_client import api_put, request_error_message
from app.ui.api_loaders import load_api_json_or_default
from app.ui.dashboard_core import render_section_header


def render_schedule_tab(settings_tickers: list[str]) -> None:
    render_section_header("自動排程", "設定收盤後資料刷新與報告更新。")
    schedule_config = _load_schedule_config()
    schedule_enabled = st.toggle("啟用每日排程", value=bool(schedule_config.get("enabled")))
    schedule_task = st.selectbox(
        "排程任務",
        options=["latest_report_update", "configured_report"],
        index=0 if schedule_config.get("task") == "latest_report_update" else 1,
        format_func=lambda value: {
            "latest_report_update": "收盤後更新最新報告",
            "configured_report": "固定主題每日產報",
        }.get(value, value),
    )
    col_hour, col_minute = st.columns(2)
    with col_hour:
        schedule_hour = st.number_input(
            "小時",
            min_value=0,
            max_value=23,
            value=int(schedule_config.get("hour") or 0),
        )
    with col_minute:
        schedule_minute = st.number_input(
            "分鐘",
            min_value=0,
            max_value=59,
            value=int(schedule_config.get("minute") or 0),
        )
    schedule_topic = st.text_input(
        "排程主題",
        value=str(schedule_config.get("topic") or ""),
        disabled=schedule_task == "latest_report_update",
    )
    schedule_default_tickers = [
        ticker for ticker in schedule_config.get("tickers", []) if ticker in settings_tickers
    ]
    schedule_tickers = st.multiselect(
        "排程個股",
        options=settings_tickers,
        default=schedule_default_tickers,
        help="收盤後更新模式留空時，系統會自動使用最新報告與候選名單股票。",
    )
    schedule_lookback = st.number_input(
        "排程回看天數",
        min_value=1,
        max_value=365,
        value=int(schedule_config.get("lookback_days") or 120),
    )
    schedule_force_refresh = st.toggle(
        "強制刷新市場資料",
        value=bool(schedule_config.get("force_refresh")),
    )
    schedule_refresh_filings = st.toggle(
        "補齊公司公開文件",
        value=bool(schedule_config.get("refresh_company_filings", True)),
    )
    schedule_rerun_report = st.toggle(
        "刷新後重新產生報告",
        value=bool(schedule_config.get("rerun_report", True)),
    )
    schedule_ready = (
        (not schedule_enabled)
        or schedule_task == "latest_report_update"
        or (bool(schedule_topic.strip()) and bool(schedule_tickers))
    )
    if not schedule_ready:
        st.caption("固定主題每日產報需填入主題並至少選擇一檔白名單股票。")
    if st.button("儲存排程設定", type="primary", disabled=not schedule_ready):
        _save_schedule_config(
            enabled=schedule_enabled,
            task=schedule_task,
            hour=int(schedule_hour),
            minute=int(schedule_minute),
            topic=schedule_topic.strip(),
            tickers=schedule_tickers,
            lookback_days=int(schedule_lookback),
            force_refresh=schedule_force_refresh,
            rerun_report=schedule_rerun_report,
            refresh_company_filings=schedule_refresh_filings,
        )
    with st.expander("進階：背景服務啟動指令"):
        st.info("使用一鍵啟動時會自動帶起背景排程服務；單獨啟動時可用以下指令。")
        st.code(
            ".venv/bin/python -m celery \\\n"
            "  -A app.tasks.celery_app.celery_app worker -B \\\n"
            "  --loglevel=INFO --pool=solo",
            language="bash",
        )


def _load_schedule_config() -> dict:
    return load_api_json_or_default(
        "/schedule",
        {
            "enabled": False,
            "task": "latest_report_update",
            "hour": 15,
            "minute": 30,
            "topic": "",
            "tickers": [],
            "lookback_days": 120,
            "force_refresh": False,
            "refresh_company_filings": True,
            "rerun_report": True,
            "timezone": "Asia/Taipei",
        },
        error_message="讀取排程設定失敗",
    )


def _save_schedule_config(
    *,
    enabled: bool,
    task: str,
    hour: int,
    minute: int,
    topic: str,
    tickers: list[str],
    lookback_days: int,
    force_refresh: bool,
    rerun_report: bool,
    refresh_company_filings: bool,
) -> None:
    payload = {
        "enabled": enabled,
        "task": task,
        "hour": hour,
        "minute": minute,
        "topic": topic,
        "tickers": tickers,
        "lookback_days": lookback_days,
        "timezone": "Asia/Taipei",
        "force_refresh": force_refresh,
        "rerun_report": rerun_report,
        "refresh_company_filings": refresh_company_filings,
    }
    try:
        saved = api_put("/schedule", payload)
    except ValueError as exc:
        st.error(f"儲存失敗：{exc}")
    except requests.RequestException as exc:
        st.error(f"儲存失敗：{request_error_message(exc)}")
    else:
        st.success(
            f"已儲存：每日 {saved.get('timezone')} "
            f"{int(saved.get('hour') or 0):02d}:{int(saved.get('minute') or 0):02d} "
            f"{saved.get('task')}"
        )
