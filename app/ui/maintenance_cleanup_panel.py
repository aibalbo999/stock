from __future__ import annotations

from datetime import datetime, time, timedelta

import streamlit as st

from app.core.time import today_taipei, utc_now_naive
from app.ui.api_actions import run_api_action_or_none
from app.ui.api_client import api_post
from app.ui.api_loaders import load_api_json_or_default


def render_maintenance_cleanup_panel() -> None:
    with st.expander("進階：資料清理"):
        st.warning("清理操作會刪除歷史紀錄；不確定時請不要使用。")
        cleanup_confirmed = st.checkbox(
            "我了解這裡會改動或刪除歷史資料",
            value=False,
            key="confirm_maintenance_cleanup",
        )
        if not cleanup_confirmed:
            st.caption("勾選確認後才會啟用下方維護按鈕，避免手機或滑鼠誤觸。")
        preview = load_api_json_or_default(
            "/reports/retention/preview",
            {"deletable_artifact_count": 0, "stale_topic_count": 0, "topics": []},
            error_message="讀取報告保留預覽失敗",
            notify="warning",
        )
        preview_cols = st.columns(3)
        preview_cols[0].metric("可清舊報告檔", int(preview.get("deletable_artifact_count") or 0))
        preview_cols[1].metric("有舊版主題", int(preview.get("stale_topic_count") or 0))
        preview_cols[2].metric("目前主題數", int(preview.get("topic_count") or 0))
        preview_rows = [
            {
                "主題": row.get("topic"),
                "版本數": int(row.get("version_count") or 0),
                "將清檔案": int(row.get("deletable_artifact_count") or 0),
                "保留版本": row.get("retained_stem"),
            }
            for row in preview.get("topics") or []
            if int(row.get("deletable_artifact_count") or 0)
        ]
        if preview_rows:
            st.dataframe(preview_rows, width="stretch", hide_index=True)
        if st.button("清除失敗紀錄", disabled=not cleanup_confirmed):
            result = run_api_action_or_none(
                lambda: api_post("/maintenance/cleanup", {"failed_runs": True}),
                error_message="清理失敗",
            )
            if isinstance(result, dict):
                st.success(f"已清除 {result.get('failed_runs_deleted', 0)} 筆失敗紀錄。")
        stale_minutes = st.number_input("執行逾時分鐘", min_value=5, max_value=1440, value=60)
        if st.button("標記逾時任務", disabled=not cleanup_confirmed):
            stale_before = utc_now_naive() - timedelta(minutes=int(stale_minutes))
            result = run_api_action_or_none(
                lambda: api_post(
                    "/maintenance/cleanup",
                    {"stale_running_before": stale_before.isoformat()},
                ),
                error_message="標記失敗",
            )
            if isinstance(result, dict):
                st.success(f"已標記 {result.get('stale_running_marked_failed', 0)} 筆逾時任務。")
        if st.button("修復失效報告連結", disabled=not cleanup_confirmed):
            result = run_api_action_or_none(
                lambda: api_post("/maintenance/cleanup", {"orphan_report_refs": True}),
                error_message="修復失敗",
            )
            if isinstance(result, dict):
                st.success(f"已修復 {result.get('orphan_report_refs_cleared', 0)} 筆報告連結。")
        if st.button("套用最新版報告保留策略", disabled=not cleanup_confirmed):
            result = run_api_action_or_none(
                lambda: api_post(
                    "/maintenance/cleanup",
                    {"latest_reports_only": True, "orphan_report_refs": True},
                ),
                error_message="清理失敗",
            )
            if isinstance(result, dict):
                st.success(
                    f"已刪除 {result.get('old_report_versions_deleted', 0)} 筆舊版報告，"
                    f"{result.get('old_report_files_deleted', 0)} 個舊報告檔，"
                    "每個主題只保留最新版。"
                )
        cleanup_days = st.number_input("保留天數", min_value=1, max_value=3650, value=90)
        cleanup_before = datetime.combine(
            today_taipei() - timedelta(days=int(cleanup_days)), time.min
        )
        col_runs, col_reports = st.columns(2)
        with col_runs:
            if st.button("清除舊分析紀錄", disabled=not cleanup_confirmed):
                result = run_api_action_or_none(
                    lambda: api_post(
                        "/maintenance/cleanup",
                        {"runs_before": cleanup_before.isoformat()},
                    ),
                    error_message="清理失敗",
                )
                if isinstance(result, dict):
                    st.success(
                        f"已清除 {result.get('old_runs_deleted', 0)} 筆 "
                        f"{cleanup_before.date().isoformat()} 前的分析紀錄。"
                    )
        with col_reports:
            if st.button("清除舊報告", disabled=not cleanup_confirmed):
                result = run_api_action_or_none(
                    lambda: api_post(
                        "/maintenance/cleanup",
                        {"reports_before": cleanup_before.isoformat()},
                    ),
                    error_message="清理失敗",
                )
                if isinstance(result, dict):
                    st.success(
                        f"已清除 {result.get('old_reports_deleted', 0)} 筆 "
                        f"{cleanup_before.date().isoformat()} 前的報告。"
                    )
