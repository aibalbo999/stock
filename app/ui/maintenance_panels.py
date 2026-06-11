from __future__ import annotations

import streamlit as st

from app.ui.maintenance_ai_panels import (
    render_ai_quota_panel,
    render_ai_usage_panel,
)
from app.ui.maintenance_cleanup_panel import render_maintenance_cleanup_panel
from app.ui.maintenance_deployment_panel import render_external_deployment_panel
from app.ui.maintenance_status import (
    maintenance_service_metrics,
    optimization_progress_next_action_rows,
    optimization_progress_rows,
    upgrade_audit_html,
    upgrade_audit_rows,
)
from app.ui.maintenance_task_panels import render_background_task_observability_panel
from app.ui.report_observability_panel import render_report_observability_panel

__all__ = [
    "render_ai_quota_panel",
    "render_ai_usage_panel",
    "render_background_task_observability_panel",
    "render_external_deployment_panel",
    "render_maintenance_cleanup_panel",
    "render_optimization_progress_panel",
    "render_report_generation_observability_panel",
    "render_report_quality_panel",
    "render_service_details_panel",
    "render_service_metrics_panel",
    "render_submission_guard_panel",
    "render_upgrade_audit_panel",
    "submission_guard_metric_values",
    "submission_guard_rows",
]


SUBMISSION_GUARD_LABELS = {
    "analysis_submission": "送出分析任務",
    "market_data_operation": "市場資料補強",
    "manual_news_import": "手動匯入新聞",
    "manual_company_filing_import": "手動匯入公司文件",
    "company_filing_url_import": "URL 匯入公司文件",
    "rss_fetch": "RSS 抓取",
    "report_follow_up_run": "報告補強重跑",
    "report_delete": "刪除報告",
    "run_delete": "刪除分析紀錄",
    "maintenance_cleanup": "維護清理",
    "maintenance_operation": "維護操作",
    "maintenance_diagnostic": "維護診斷",
    "maintenance_post_run_diagnostic": "後續診斷",
    "maintenance_task_retry": "維護任務重試",
    "task_status_operation": "任務取消/重試",
    "schedule_settings_save": "儲存排程設定",
}

SUBMISSION_GUARD_SURFACES = {
    "analysis_workspace": "分析工作區",
    "data_enrichment_market": "資料補強：市場",
    "data_enrichment_manual": "資料補強：手動",
    "data_enrichment_rss": "資料補強：RSS",
    "report_follow_up_controls": "報告補強",
    "report_center": "報告中心",
    "maintenance_cleanup_panel": "維護清理",
    "maintenance_deployment_panel": "維護部署",
    "maintenance_task_panels": "任務觀測",
    "task_status_panel": "任務狀態",
    "system_settings_schedule": "系統設定：排程",
}

SUBMISSION_GUARD_OVERALL_STATUS_LABELS = {
    "ready": "完整",
    "missing": "需處理",
    "unknown": "未知",
}

SUBMISSION_GUARD_ROW_STATUS_LABELS = {
    True: "已保護",
    False: "缺保護",
}


def render_upgrade_audit_panel(upgrade_audit: dict) -> None:
    st.markdown(upgrade_audit_html(upgrade_audit), unsafe_allow_html=True)
    with st.expander("升級稽核明細"):
        st.dataframe(upgrade_audit_rows(upgrade_audit), width="stretch", hide_index=True)


def render_optimization_progress_panel(service_snapshot: dict) -> None:
    progress = (
        service_snapshot.get("optimization_progress")
        if isinstance(service_snapshot.get("optimization_progress"), dict)
        else {}
    )
    rows = optimization_progress_rows(progress)
    action_rows = optimization_progress_next_action_rows(progress)
    raw_status = str(progress.get("status") or "unknown")
    effective_status = str(
        progress.get("effective_status_after_available_local_defaults")
        or raw_status
    )
    expanded = effective_status != "ready"
    with st.expander("優化進度", expanded=expanded):
        cols = st.columns(5)
        cols[0].metric(
            "狀態",
            effective_status,
            delta=f"原始 {raw_status}" if effective_status != raw_status else None,
        )
        cols[1].metric(
            "完成",
            f"{int(progress.get('ready_checks') or 0)}/{int(progress.get('total_checks') or 0)}",
        )
        raw_blocking = int(progress.get("blocking_gap_count") or 0)
        raw_optional = int(progress.get("optional_gap_count") or 0)
        effective_blocking = int(
            progress.get("effective_blocking_gap_count_after_available_local_defaults")
            if progress.get("effective_blocking_gap_count_after_available_local_defaults")
            is not None
            else raw_blocking
        )
        effective_optional = int(
            progress.get("effective_optional_gap_count_after_available_local_defaults")
            if progress.get("effective_optional_gap_count_after_available_local_defaults")
            is not None
            else raw_optional
        )
        cols[2].metric(
            "Blocking",
            effective_blocking,
            delta=f"原始 {raw_blocking}" if effective_blocking != raw_blocking else None,
        )
        cols[3].metric(
            "外部/選配",
            effective_optional,
            delta=f"原始 {raw_optional}" if effective_optional != raw_optional else None,
        )
        cols[4].metric("本機可補", int(progress.get("local_resolvable_gap_count") or 0))
        if progress.get("status_note"):
            st.caption(str(progress["status_note"]))
        if progress.get("effective_gap_note"):
            st.caption(str(progress["effective_gap_note"]))
        local_projection = (
            progress.get("local_resolution_projection")
            if isinstance(progress.get("local_resolution_projection"), dict)
            else {}
        )
        if local_projection.get("next_action"):
            st.caption(str(local_projection["next_action"]))
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        if action_rows:
            st.caption("下一步")
            st.dataframe(action_rows, width="stretch", hide_index=True)


def render_service_metrics_panel(status: dict, service_snapshot: dict) -> None:
    service_metrics = maintenance_service_metrics(status, service_snapshot)
    service_cols = st.columns(len(service_metrics))
    for column, (label, value) in zip(service_cols, service_metrics.items()):
        column.metric(label, value)


def submission_guard_metric_values(service_snapshot: dict) -> dict[str, object]:
    frontend = _frontend_status(service_snapshot)
    rows = _submission_guard_raw_rows(frontend)
    total = int(frontend.get("ui_risky_submission_guard_total_count") or len(rows))
    ready = int(
        frontend.get("ui_risky_submission_guard_ready_count")
        if frontend.get("ui_risky_submission_guard_ready_count") is not None
        else sum(1 for row in rows if row.get("ready"))
    )
    missing = frontend.get("ui_risky_submission_guard_missing")
    missing_count = len(missing) if isinstance(missing, list) else max(total - ready, 0)
    if total <= 0:
        status = SUBMISSION_GUARD_OVERALL_STATUS_LABELS["unknown"]
    elif missing_count:
        status = SUBMISSION_GUARD_OVERALL_STATUS_LABELS["missing"]
    else:
        status = SUBMISSION_GUARD_OVERALL_STATUS_LABELS["ready"]
    return {
        "狀態": status,
        "完成": f"{ready}/{total}",
        "缺口": missing_count,
    }


def submission_guard_rows(service_snapshot: dict) -> list[dict[str, object]]:
    frontend = _frontend_status(service_snapshot)
    rows = []
    for row in _submission_guard_raw_rows(frontend):
        if not isinstance(row, dict):
            continue
        guard_id = str(row.get("id") or "").strip()
        surface = str(row.get("surface") or "").strip()
        rows.append(
            {
                "操作": SUBMISSION_GUARD_LABELS.get(guard_id, guard_id or "-"),
                "區域": SUBMISSION_GUARD_SURFACES.get(surface, surface or "-"),
                "狀態": SUBMISSION_GUARD_ROW_STATUS_LABELS[bool(row.get("ready"))],
                "Evidence": str(row.get("guard_key") or "-"),
            }
        )
    return rows


def render_submission_guard_panel(service_snapshot: dict) -> None:
    metrics = submission_guard_metric_values(service_snapshot)
    rows = submission_guard_rows(service_snapshot)
    expanded = metrics["狀態"] != SUBMISSION_GUARD_OVERALL_STATUS_LABELS["ready"]
    with st.expander("高風險操作保護", expanded=expanded):
        cols = st.columns(3)
        for column, (label, value) in zip(cols, metrics.items()):
            column.metric(label, value)
        st.caption("確認所有會寫入、刪除、消耗額度或重試任務的入口都有確認閘門。")
        if metrics["狀態"] == SUBMISSION_GUARD_OVERALL_STATUS_LABELS["ready"]:
            st.caption("目前所有高風險操作都已配置確認保護。")
        elif metrics["狀態"] == SUBMISSION_GUARD_OVERALL_STATUS_LABELS["unknown"]:
            st.warning("尚未取得高風險操作保護狀態；請先確認 /services/status。")
        else:
            st.warning("仍有高風險操作缺少確認保護，請先修復缺口再交給一般操作者使用。")
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)


def render_report_generation_observability_panel(report_observability_summary: dict) -> None:
    with st.expander("報告生成觀測", expanded=False):
        render_report_observability_panel(report_observability_summary)


def render_report_quality_panel(report_quality_summary: dict) -> None:
    with st.expander("報告品質 Gate 總覽", expanded=False):
        quality_totals = (
            report_quality_summary.get("totals")
            if isinstance(report_quality_summary.get("totals"), dict)
            else {}
        )
        quality_cols = st.columns(5)
        quality_cols[0].metric("狀態", report_quality_summary.get("status") or "-")
        quality_cols[1].metric("最新版報告", int(quality_totals.get("report_count") or 0))
        quality_cols[2].metric("Ready", int(quality_totals.get("ready_count") or 0))
        quality_cols[3].metric("Blockers", int(quality_totals.get("blocker_count") or 0))
        quality_cols[4].metric("Warnings", int(quality_totals.get("warning_count") or 0))
        if report_quality_summary.get("alerts"):
            st.dataframe(report_quality_summary["alerts"], width="stretch", hide_index=True)
        if report_quality_summary.get("reports"):
            st.dataframe(report_quality_summary["reports"], width="stretch", hide_index=True)


def render_service_details_panel(status: dict, service_snapshot: dict) -> None:
    with st.expander("進階：服務細節"):
        st.json(status["settings"])
        st.json(status["integrity"])
        st.json(service_snapshot)
        st.dataframe(
            [{"table": table, **details} for table, details in status["tables"].items()],
            width="stretch",
            hide_index=True,
        )


def _frontend_status(service_snapshot: dict) -> dict:
    frontend = service_snapshot.get("frontend") if isinstance(service_snapshot, dict) else {}
    return frontend if isinstance(frontend, dict) else {}


def _submission_guard_raw_rows(frontend: dict) -> list[dict]:
    rows = frontend.get("ui_risky_submission_guard_rows")
    return rows if isinstance(rows, list) else []
