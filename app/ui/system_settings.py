from __future__ import annotations

# ruff: noqa: F403,F405
from app.ui.dashboard_core import *


def render_system_settings() -> None:
    settings_whitelist = SupplyChainWhitelist()
    settings_tickers = sorted(settings_whitelist.allowed_tickers())
    settings_tabs = st.tabs(["股票範圍", "自動排程", "維護"])

    with settings_tabs[0]:
        render_section_header("股票範圍", "這裡是系統可辨識的台股公司範圍；正式報告仍會再用資料證據篩選。")
        segments = settings_whitelist.segments
        scope_cols = st.columns(3)
        scope_cols[0].metric("產業分類", len(segments))
        scope_cols[1].metric("股票數", len(settings_whitelist.companies()))
        scope_cols[2].metric("風險詞組", len(settings_whitelist.risk_keywords))
        segment_filter = st.selectbox(
            "產業分類篩選",
            options=["全部"] + [segment.name for segment in segments],
        )
        segment_rows = []
        for segment in segments:
            if segment_filter != "全部" and segment.name != segment_filter:
                continue
            for company in segment.companies:
                segment_rows.append(
                    {
                        "股票": company.ticker,
                        "公司": company.name,
                        "產業分類": segment.name,
                        "證據關鍵字": "、".join(company.evidence_keywords[:5]) or "-",
                    }
                )
        if segment_rows:
            st.dataframe(segment_rows, width="stretch", hide_index=True)
        else:
            st.info("目前沒有符合篩選的公司。")
        with st.expander("進階：原始白名單 JSON"):
            st.json(settings_whitelist.raw)

    with settings_tabs[1]:
        render_section_header("自動排程", "設定收盤後資料刷新與報告更新。")
        try:
            schedule_config = api_get("/schedule")
        except requests.RequestException as exc:
            schedule_config = {
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
            }
            st.error(f"讀取排程設定失敗：{request_error_message(exc)}")
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
            schedule_hour = st.number_input("小時", min_value=0, max_value=23, value=int(schedule_config.get("hour") or 0))
        with col_minute:
            schedule_minute = st.number_input("分鐘", min_value=0, max_value=59, value=int(schedule_config.get("minute") or 0))
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
        schedule_force_refresh = st.toggle("強制刷新市場資料", value=bool(schedule_config.get("force_refresh")))
        schedule_refresh_filings = st.toggle("補齊公司公開文件", value=bool(schedule_config.get("refresh_company_filings", True)))
        schedule_rerun_report = st.toggle("刷新後重新產生報告", value=bool(schedule_config.get("rerun_report", True)))
        schedule_ready = (
            (not schedule_enabled)
            or schedule_task == "latest_report_update"
            or (bool(schedule_topic.strip()) and bool(schedule_tickers))
        )
        if not schedule_ready:
            st.caption("固定主題每日產報需填入主題並至少選擇一檔白名單股票。")
        if st.button("儲存排程設定", type="primary", disabled=not schedule_ready):
            try:
                saved = api_put(
                    "/schedule",
                    {
                        "enabled": schedule_enabled,
                        "task": schedule_task,
                        "hour": int(schedule_hour),
                        "minute": int(schedule_minute),
                        "topic": schedule_topic.strip(),
                        "tickers": schedule_tickers,
                        "lookback_days": int(schedule_lookback),
                        "timezone": "Asia/Taipei",
                        "force_refresh": schedule_force_refresh,
                        "rerun_report": schedule_rerun_report,
                        "refresh_company_filings": schedule_refresh_filings,
                    },
                )
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
        with st.expander("進階：背景服務啟動指令"):
            st.info("使用一鍵啟動時會自動帶起背景排程服務；單獨啟動時可用以下指令。")
            st.code(
                ".venv/bin/python -m celery \\\n"
                "  -A app.tasks.celery_app.celery_app worker -B \\\n"
                "  --loglevel=INFO --pool=solo",
                language="bash",
            )

    with settings_tabs[2]:
        render_section_header("維護", "一般使用不需要查看；只有資料異常或服務連線問題時使用。")
        try:
            status = api_get("/db/status")
        except requests.RequestException as exc:
            status = {"settings": {}, "integrity": {}, "tables": {}}
            st.error(f"讀取 DB 狀態失敗：{request_error_message(exc)}")
        try:
            service_snapshot = api_get("/services/status")
        except requests.RequestException as exc:
            service_snapshot = {}
            st.error(f"讀取服務狀態失敗：{request_error_message(exc)}")
        try:
            llm_quota = api_get("/llm/quota")
        except requests.RequestException as exc:
            llm_quota = {"models": [], "totals": {}, "window": {}, "recommended_model": None}
            st.error(f"讀取 AI 額度狀態失敗：{request_error_message(exc)}")
        try:
            llm_usage_summary = api_get("/llm/usage/summary?days=7")
        except requests.RequestException as exc:
            llm_usage_summary = {"totals": {}, "by_model": [], "by_operation": [], "daily": []}
            st.error(f"讀取 AI 用量趨勢失敗：{request_error_message(exc)}")
        try:
            task_summary = api_get("/tasks/summary?days=7")
        except requests.RequestException as exc:
            task_summary = {"totals": {}, "by_status": [], "by_operation": [], "recent_failures": []}
            st.error(f"讀取背景任務觀測失敗：{request_error_message(exc)}")
        try:
            report_quality_summary = api_get("/reports/quality/summary?limit=20")
        except requests.RequestException as exc:
            report_quality_summary = {"status": "unknown", "totals": {}, "reports": [], "alerts": []}
            st.error(f"讀取報告品質總覽失敗：{request_error_message(exc)}")
        strict_upgrade_audit = st.toggle(
            "正式部署檢查",
            value=False,
            help="啟用後會把外部 Neo4j live import 也視為必備項目。",
        )
        try:
            strict_query = "true" if strict_upgrade_audit else "false"
            upgrade_audit = api_get(f"/services/upgrade-audit?strict_external={strict_query}")
        except requests.RequestException as exc:
            upgrade_audit = {"overall_status": "unknown", "warnings": [], "failures": []}
            st.error(f"讀取升級稽核失敗：{request_error_message(exc)}")
        st.markdown(upgrade_audit_html(upgrade_audit), unsafe_allow_html=True)
        with st.expander("升級稽核明細"):
            st.dataframe(upgrade_audit_rows(upgrade_audit), width="stretch", hide_index=True)
        service_metrics = maintenance_service_metrics(status, service_snapshot)
        service_cols = st.columns(len(service_metrics))
        for column, (label, value) in zip(service_cols, service_metrics.items()):
            column.metric(label, value)
        external_warnings = [
            item
            for item in upgrade_audit.get("warnings", []) or []
            if isinstance(item, dict) and item.get("external_integration")
        ]
        with st.expander("外部部署選配狀態", expanded=bool(external_warnings)):
            deploy = upgrade_audit.get("deployment") if isinstance(upgrade_audit.get("deployment"), dict) else {}
            deploy_cols = st.columns(4)
            deploy_cols[0].metric("部署狀態", deploy.get("status") or upgrade_audit.get("deployment_status") or "-")
            deploy_cols[1].metric("Ready", int(deploy.get("ready") or 0))
            deploy_cols[2].metric("Warnings", int(deploy.get("warnings") or 0))
            deploy_cols[3].metric("Failures", int(deploy.get("failures") or 0))
            if external_warnings:
                st.dataframe(
                    [
                        {
                            "area": row.get("area"),
                            "capability": row.get("capability"),
                            "status": row.get("status"),
                            "remediation": row.get("remediation"),
                        }
                        for row in external_warnings
                    ],
                    width="stretch",
                    hide_index=True,
                )
                st.code(".venv/bin/python scripts/external_integrations_smoke.py --strict --json", language="bash")
            else:
                st.success("外部部署選配目前沒有警示。")
        with st.expander("AI 額度與模型路由", expanded=True):
            quota_window = llm_quota.get("window") if isinstance(llm_quota.get("window"), dict) else {}
            quota_totals = llm_quota.get("totals") if isinstance(llm_quota.get("totals"), dict) else {}
            quota_cols = st.columns(4)
            quota_cols[0].metric("推薦模型", llm_quota.get("recommended_model") or "-")
            quota_cols[1].metric("今日請求", int(quota_totals.get("request_count") or 0))
            quota_cols[2].metric("今日 Token", int(quota_totals.get("total_token_estimate") or 0))
            quota_cols[3].metric("額度時區", quota_window.get("timezone") or "-")
            quota_rows = []
            for model in llm_quota.get("models") or []:
                quota_rows.append(
                    {
                        "rank": model.get("rank"),
                        "model": model.get("model"),
                        "status": model.get("status"),
                        "requests_used": model.get("requests_used"),
                        "request_budget": model.get("request_budget"),
                        "requests_remaining": model.get("requests_remaining"),
                        "tokens_used": model.get("tokens_used"),
                        "token_budget": model.get("token_budget"),
                    }
                )
            if quota_rows:
                st.dataframe(quota_rows, width="stretch", hide_index=True)
            else:
                st.info("尚未有 AI 用量紀錄。")
            budget_source = llm_quota.get("budget_source") if isinstance(llm_quota.get("budget_source"), dict) else {}
            if budget_source.get("note"):
                st.caption(str(budget_source["note"]))
        with st.expander("AI 用量趨勢與成本", expanded=True):
            usage_totals = (
                llm_usage_summary.get("totals")
                if isinstance(llm_usage_summary.get("totals"), dict)
                else {}
            )
            usage_cols = st.columns(5)
            usage_cols[0].metric("7 日請求", int(usage_totals.get("request_count") or 0))
            usage_cols[1].metric("7 日 Token", int(usage_totals.get("total_token_estimate") or 0))
            usage_cols[2].metric(
                "估算成本 USD",
                f"{float(usage_totals.get('estimated_cost_usd') or 0.0):.4f}",
            )
            usage_cols[3].metric("Fallback 次數", int(usage_totals.get("fallback_path_count") or 0))
            usage_cols[4].metric("可重試失敗", int(usage_totals.get("retryable_failure_count") or 0))
            daily_usage_rows = llm_usage_summary.get("daily") or []
            model_usage_rows = llm_usage_summary.get("by_model") or []
            operation_usage_rows = llm_usage_summary.get("by_operation") or []
            if daily_usage_rows:
                st.caption("每日 token / request 趨勢")
                st.dataframe(daily_usage_rows, width="stretch", hide_index=True)
            if model_usage_rows:
                st.caption("模型用量")
                st.dataframe(model_usage_rows, width="stretch", hide_index=True)
            if operation_usage_rows:
                st.caption("任務用量")
                st.dataframe(operation_usage_rows, width="stretch", hide_index=True)
            if not (daily_usage_rows or model_usage_rows or operation_usage_rows):
                st.info("尚未有可彙總的 AI 用量紀錄。")
            usage_alerts = llm_usage_summary.get("alerts") or []
            for alert in usage_alerts:
                message = str(alert.get("message") or alert.get("code") or "")
                if alert.get("severity") == "error":
                    st.error(message)
                elif alert.get("severity") == "warning":
                    st.warning(message)
                else:
                    st.caption(message)
            cost_budget = llm_usage_summary.get("cost_budget")
            if isinstance(cost_budget, dict):
                st.caption(
                    "成本預算："
                    f"{cost_budget.get('status')}｜"
                    f"window ${float(cost_budget.get('window_cost_budget_usd') or 0.0):.4f}"
                )
        with st.expander("背景任務觀測", expanded=False):
            task_totals = task_summary.get("totals") if isinstance(task_summary.get("totals"), dict) else {}
            task_cols = st.columns(5)
            task_cols[0].metric("7 日任務", int(task_totals.get("run_count") or 0))
            task_cols[1].metric("成功率", "-" if task_totals.get("success_rate") is None else f"{float(task_totals['success_rate']) * 100:.1f}%")
            task_cols[2].metric("失敗", int(task_totals.get("failed_count") or 0))
            task_cols[3].metric("執行中", int(task_totals.get("running_count") or 0))
            task_cols[4].metric("疑似卡住", int(task_totals.get("stale_running_count") or 0))
            if task_summary.get("by_operation"):
                st.caption("任務類型")
                st.dataframe(task_summary["by_operation"], width="stretch", hide_index=True)
            if task_summary.get("recent_failures"):
                st.caption("近期失敗 / 取消")
                st.dataframe(task_summary["recent_failures"], width="stretch", hide_index=True)
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
        with st.expander("進階：服務細節"):
            st.json(status["settings"])
            st.json(status["integrity"])
            st.json(service_snapshot)
            st.dataframe(
                [
                    {"table": table, **details}
                    for table, details in status["tables"].items()
                ],
                width="stretch",
                hide_index=True,
            )
        with st.expander("進階：資料清理"):
            st.warning("清理操作會刪除歷史紀錄；不確定時請不要使用。")
            cleanup_confirmed = st.checkbox(
                "我了解這裡會改動或刪除歷史資料",
                value=False,
                key="confirm_maintenance_cleanup",
            )
            if not cleanup_confirmed:
                st.caption("勾選確認後才會啟用下方維護按鈕，避免手機或滑鼠誤觸。")
            if st.button("清除失敗紀錄", disabled=not cleanup_confirmed):
                try:
                    result = api_post("/maintenance/cleanup", {"failed_runs": True})
                    st.success(f"已清除 {result.get('failed_runs_deleted', 0)} 筆失敗紀錄。")
                except requests.RequestException as exc:
                    st.error(f"清理失敗：{request_error_message(exc)}")
            stale_minutes = st.number_input("執行逾時分鐘", min_value=5, max_value=1440, value=60)
            if st.button("標記逾時任務", disabled=not cleanup_confirmed):
                stale_before = datetime.utcnow() - timedelta(minutes=int(stale_minutes))
                try:
                    result = api_post(
                        "/maintenance/cleanup",
                        {"stale_running_before": stale_before.isoformat()},
                    )
                    st.success(f"已標記 {result.get('stale_running_marked_failed', 0)} 筆逾時任務。")
                except requests.RequestException as exc:
                    st.error(f"標記失敗：{request_error_message(exc)}")
            if st.button("修復失效報告連結", disabled=not cleanup_confirmed):
                try:
                    result = api_post("/maintenance/cleanup", {"orphan_report_refs": True})
                    st.success(f"已修復 {result.get('orphan_report_refs_cleared', 0)} 筆報告連結。")
                except requests.RequestException as exc:
                    st.error(f"修復失敗：{request_error_message(exc)}")
            cleanup_days = st.number_input("保留天數", min_value=1, max_value=3650, value=90)
            cleanup_before = datetime.combine(today_taipei() - timedelta(days=int(cleanup_days)), time.min)
            col_runs, col_reports = st.columns(2)
            with col_runs:
                if st.button("清除舊分析紀錄", disabled=not cleanup_confirmed):
                    try:
                        result = api_post(
                            "/maintenance/cleanup",
                            {"runs_before": cleanup_before.isoformat()},
                        )
                        st.success(
                            f"已清除 {result.get('old_runs_deleted', 0)} 筆 "
                            f"{cleanup_before.date().isoformat()} 前的分析紀錄。"
                        )
                    except requests.RequestException as exc:
                        st.error(f"清理失敗：{request_error_message(exc)}")
            with col_reports:
                if st.button("清除舊報告", disabled=not cleanup_confirmed):
                    try:
                        result = api_post(
                            "/maintenance/cleanup",
                            {"reports_before": cleanup_before.isoformat()},
                        )
                        st.success(
                            f"已清除 {result.get('old_reports_deleted', 0)} 筆 "
                            f"{cleanup_before.date().isoformat()} 前的報告。"
                        )
                    except requests.RequestException as exc:
                        st.error(f"清理失敗：{request_error_message(exc)}")
