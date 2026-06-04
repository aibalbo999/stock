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
        schedule_store = ScheduleConfigStore()
        schedule_config = schedule_store.load()
        schedule_enabled = st.toggle("啟用每日排程", value=schedule_config.enabled)
        schedule_task = st.selectbox(
            "排程任務",
            options=["latest_report_update", "configured_report"],
            index=0 if schedule_config.task == "latest_report_update" else 1,
            format_func=lambda value: {
                "latest_report_update": "收盤後更新最新報告",
                "configured_report": "固定主題每日產報",
            }.get(value, value),
        )
        col_hour, col_minute = st.columns(2)
        with col_hour:
            schedule_hour = st.number_input("小時", min_value=0, max_value=23, value=schedule_config.hour)
        with col_minute:
            schedule_minute = st.number_input("分鐘", min_value=0, max_value=59, value=schedule_config.minute)
        schedule_topic = st.text_input(
            "排程主題",
            value=schedule_config.topic,
            disabled=schedule_task == "latest_report_update",
        )
        schedule_default_tickers = [
            ticker for ticker in schedule_config.tickers if ticker in settings_tickers
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
            value=schedule_config.lookback_days,
        )
        schedule_force_refresh = st.toggle("強制刷新市場資料", value=schedule_config.force_refresh)
        schedule_refresh_filings = st.toggle("補齊公司公開文件", value=schedule_config.refresh_company_filings)
        schedule_rerun_report = st.toggle("刷新後重新產生報告", value=schedule_config.rerun_report)
        schedule_ready = (
            (not schedule_enabled)
            or schedule_task == "latest_report_update"
            or (bool(schedule_topic.strip()) and bool(schedule_tickers))
        )
        if not schedule_ready:
            st.caption("固定主題每日產報需填入主題並至少選擇一檔白名單股票。")
        if st.button("儲存排程設定", type="primary", disabled=not schedule_ready):
            try:
                saved = schedule_store.save(
                    ScheduleConfig(
                        enabled=schedule_enabled,
                        task=schedule_task,
                        hour=int(schedule_hour),
                        minute=int(schedule_minute),
                        topic=schedule_topic.strip(),
                        tickers=schedule_tickers,
                        lookback_days=int(schedule_lookback),
                        timezone="Asia/Taipei",
                        force_refresh=schedule_force_refresh,
                        rerun_report=schedule_rerun_report,
                        refresh_company_filings=schedule_refresh_filings,
                    )
                )
            except ValueError as exc:
                st.error(f"儲存失敗：{exc}")
            else:
                st.success(f"已儲存：每日 {saved.timezone} {saved.hour:02d}:{saved.minute:02d} {saved.task}")
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
        status = db_status()
        service_snapshot = service_status()
        strict_upgrade_audit = st.toggle(
            "正式部署檢查",
            value=False,
            help="啟用後會把外部 Neo4j live import 也視為必備項目。",
        )
        upgrade_audit = audit_upgrade_capabilities(
            service_snapshot,
            strict_external=bool(strict_upgrade_audit),
        )
        st.markdown(upgrade_audit_html(upgrade_audit), unsafe_allow_html=True)
        with st.expander("升級稽核明細"):
            st.dataframe(upgrade_audit_rows(upgrade_audit), width="stretch", hide_index=True)
        service_metrics = maintenance_service_metrics(status, service_snapshot)
        service_cols = st.columns(len(service_metrics))
        for column, (label, value) in zip(service_cols, service_metrics.items()):
            column.metric(label, value)
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
                with session_scope() as session:
                    deleted = AnalysisRunRepository(session).delete_failed()
                st.success(f"已清除 {deleted} 筆失敗紀錄。")
            stale_minutes = st.number_input("執行逾時分鐘", min_value=5, max_value=1440, value=60)
            if st.button("標記逾時任務", disabled=not cleanup_confirmed):
                stale_before = datetime.utcnow() - timedelta(minutes=int(stale_minutes))
                with session_scope() as session:
                    marked = AnalysisRunRepository(session).mark_stale_running_failed(
                        stale_before,
                        "marked failed from Streamlit maintenance",
                    )
                st.success(f"已標記 {marked} 筆逾時任務。")
            if st.button("修復失效報告連結", disabled=not cleanup_confirmed):
                with session_scope() as session:
                    cleared = AnalysisRunRepository(session).clear_orphan_report_refs()
                st.success(f"已修復 {cleared} 筆報告連結。")
            cleanup_days = st.number_input("保留天數", min_value=1, max_value=3650, value=90)
            cleanup_before = datetime.combine(today_taipei() - timedelta(days=int(cleanup_days)), time.min)
            col_runs, col_reports = st.columns(2)
            with col_runs:
                if st.button("清除舊分析紀錄", disabled=not cleanup_confirmed):
                    with session_scope() as session:
                        deleted = AnalysisRunRepository(session).delete_before(cleanup_before)
                    st.success(f"已清除 {deleted} 筆 {cleanup_before.date().isoformat()} 前的分析紀錄。")
            with col_reports:
                if st.button("清除舊報告", disabled=not cleanup_confirmed):
                    with session_scope() as session:
                        deleted = ReportRepository(session).delete_before(cleanup_before)
                    st.success(f"已清除 {deleted} 筆 {cleanup_before.date().isoformat()} 前的報告。")
