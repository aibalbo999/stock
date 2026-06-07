from __future__ import annotations

# ruff: noqa: F403,F405
from app.ui.dashboard_core import *


def render_analysis_workspace() -> None:
    st.markdown(
        """
        <section class="workspace-topbar">
            <div>
                <div class="workspace-kicker">AI 台股投資工作台</div>
                <h1>研究主題、補資料、看報告，集中在同一個工作台</h1>
                <div class="workspace-subtitle">
                    先確認本次配置與避開名單，再檢視候選標的與投資理由。必要資料缺口會自動排入補強流程。
                </div>
            </div>
            <div class="workspace-meta">
                <span class="workspace-chip">Asia/Taipei {today}</span>
                <span class="workspace-chip">資料不足自動降級</span>
                <span class="workspace-chip is-accent">缺口自動補強</span>
            </div>
        </section>
        <section class="workflow-strip" aria-label="分析流程">
            <div class="workflow-step"><span>01</span><strong>主題拆解</strong></div>
            <div class="workflow-step"><span>02</span><strong>來源驗證</strong></div>
            <div class="workflow-step"><span>03</span><strong>個股評估</strong></div>
            <div class="workflow-step"><span>04</span><strong>補強與重跑</strong></div>
        </section>
        <section class="workspace-ledger" aria-label="報告判讀基準">
            <div class="ledger-item"><span>品質門檻</span><strong>未過門檻先標示，不包裝成建議</strong></div>
            <div class="ledger-item"><span>資料來源</span><strong>新聞、市場、財務、公司文件分開查核</strong></div>
            <div class="ledger-item"><span>投資口徑</span><strong>正式分析不等於買進，分數只用於排序</strong></div>
        </section>
        """.format(today=today_taipei().isoformat()),
        unsafe_allow_html=True,
    )
    render_section_header("建立一次分析", "預設使用 AI 拆解主題並抓取國內外資料；不確定時維持預設即可。")
    analysis_config_col, analysis_result_col = st.columns([0.36, 0.64], gap="large")
    with analysis_config_col:
        with st.form("analysis_form"):
            st.markdown("#### 分析設定")
            st.markdown(
                '<div class="compact-note">輸入主題，系統會自行拆解子題並建立候選股票。</div>',
                unsafe_allow_html=True,
            )
            topic = st.text_input("分析主題", value="AI 產業鏈")
            lookback_days = st.slider("新聞與市場資料回看天數", min_value=7, max_value=60, value=14)
            investor_capital = st.number_input(
                "可投入總資金",
                min_value=10000,
                max_value=100000000,
                value=1000000,
                step=10000,
            )
            profile_label = st.selectbox(
                "投資人設定",
                options=["新手保守", "一般穩健", "積極成長"],
                index=0,
            )
            profile_map = {"新手保守": "beginner", "一般穩健": "balanced", "積極成長": "aggressive"}
            investor_profile = profile_map[profile_label]
            beginner_mode = investor_profile == "beginner"

            st.markdown("#### 風險與資金")
            max_position_pct = st.slider("單檔上限", min_value=1, max_value=20, value=10, format="%d%%")
            cash_reserve_pct = st.slider("保留現金", min_value=10, max_value=80, value=30, format="%d%%")
            discovery_limit = st.slider("資料抓取強度", min_value=2, max_value=20, value=5)

            with st.expander("進階選項"):
                ai_discovery_mode = st.checkbox("由 AI 拆解主題與建立候選清單", value=True)
                analysis_mode_label = st.radio(
                    "分析強度",
                    options=["快速預覽", "標準研究", "深度研究"],
                    index=1,
                    horizontal=True,
                )
                analysis_mode_map = {"快速預覽": "fast", "標準研究": "standard", "深度研究": "deep"}
                analysis_mode = analysis_mode_map[analysis_mode_label]
                deep_analysis = analysis_mode == "deep"
                include_international = st.checkbox("納入國際資料源", value=True)
                evidence_limit = st.slider(
                    "報告引用資料量",
                    min_value=40,
                    max_value=200,
                    value=180 if analysis_mode == "deep" else 120 if analysis_mode == "standard" else 80,
                    step=20,
                )
                tickers = st.multiselect(
                    "手動模式個股範圍",
                    options=sorted(SupplyChainWhitelist().allowed_tickers()),
                    default=[],
                )
                st.caption("分析任務一律交由 FastAPI / Celery 背景執行，送出後可用 task id 查詢進度。")

            run_sync = st.form_submit_button("執行分析", type="primary")

        if run_sync:
            if ai_discovery_mode:
                payload = {
                    "topic": topic,
                    "limit_per_query": int(discovery_limit),
                    "lookback_days": int(lookback_days),
                    "evidence_limit": int(evidence_limit),
                    "analysis_mode": analysis_mode,
                    "deep_analysis": bool(deep_analysis),
                    "include_international": bool(include_international),
                    "investor_capital": int(investor_capital),
                    "beginner_mode": bool(beginner_mode),
                    "investor_profile": investor_profile,
                    "max_position_pct": float(max_position_pct) / 100,
                    "cash_reserve_pct": float(cash_reserve_pct) / 100,
                }
                try:
                    task_response = api_task_post("/pipeline/run_discovered_async", payload)
                    st.session_state["last_async_task_id"] = task_response["task_id"]
                    st.session_state["last_analysis_task_type"] = "discovered"
                    st.success(f"已送出 AI 探索背景任務：{task_response['task_id']}")
                except requests.RequestException as exc:
                    st.error(f"AI 探索背景任務送出失敗：{request_error_message(exc)}")
            elif not tickers:
                st.warning("手動模式背景執行請至少選擇一檔白名單股票。")
            else:
                payload = {
                    "topic": topic,
                    "tickers": tickers,
                    "lookback_days": int(lookback_days),
                    "evidence_limit": int(evidence_limit),
                    "investor_capital": int(investor_capital),
                    "beginner_mode": bool(beginner_mode),
                    "investor_profile": investor_profile,
                    "max_position_pct": float(max_position_pct) / 100,
                    "cash_reserve_pct": float(cash_reserve_pct) / 100,
                }
                try:
                    task_response = api_task_post("/reports/generate_async", payload)
                    st.session_state["last_async_task_id"] = task_response["task_id"]
                    st.session_state["last_analysis_task_type"] = "manual"
                    st.success(f"已送出分析背景任務：{task_response['task_id']}")
                except requests.RequestException as exc:
                    st.error(f"分析背景任務送出失敗：{request_error_message(exc)}")

        with st.expander("疑難排解：查詢背景分析"):
            last_task_id = st.session_state.get("last_async_task_id")
            task_id = st.text_input("背景分析編號", value=last_task_id or "")
            render_task_status_panel(
                task_id=task_id,
                refresh_key="refresh_analysis_task_status",
                apply_result_key="apply_analysis_task_result",
            )
            if st.button("查詢紀錄", key="lookup_analysis_task_run"):
                if not task_id:
                    st.warning("請輸入 task id。")
                else:
                    try:
                        st.json(api_get(f"/tasks/{task_id}/run"))
                    except requests.HTTPError as exc:
                        if exc.response.status_code == 404:
                            st.info("尚未找到對應紀錄；任務剛送出時可能需要等待。")
                        else:
                            st.error(f"查詢失敗：{exc}")
                    except requests.RequestException as exc:
                        st.error(f"查詢失敗：{exc}")

    with analysis_result_col:
        result = st.session_state.get("last_analysis_result")
        if result:
            result = hydrate_active_report_result(result)
            report_markdown = result["report"]["markdown"]
            analysis_metrics = (result.get("quality_gate") or {}).get("metrics") or {}
            metric_cols = st.columns(4)
            metric_cols[0].metric("報告", f"#{result['report_id']}")
            metric_cols[1].metric(
                "正式分析股票",
                metric_count_from_payload(result, "promoted_tickers", analysis_metrics, "promoted_count", 0),
            )
            metric_cols[2].metric("候選清單", len(result.get("candidate_whitelist", [])))
            metric_cols[3].metric("設定總資金", f"{int(investor_capital):,}")
            render_market_errors(result)

            render_section_header("本次分析結果", "先看重點報告；資料細節只在需要查核時展開。")
            result_tabs = st.tabs(["重點報告", "資料查核"])
            with result_tabs[0]:
                st.download_button(
                    "下載 HTML 報告",
                    data=report_html(report_markdown, result),
                    file_name=f"report_{result['report_id']}.html",
                    mime="text/html",
                )
                render_reader_report(report_markdown, result)
            with result_tabs[1]:
                render_quality_gate(result)
                render_company_data_audit(int(result["report_id"]))
                render_follow_up_controls(int(result["report_id"]), report_markdown, scope="analysis_result")
                with st.expander("資料來源概況"):
                    render_source_audit(result)
                if result.get("candidate_whitelist"):
                    st.markdown("**候選清單驗證**")
                    st.dataframe(candidate_rows(result["candidate_whitelist"]), width="stretch", hide_index=True)
                with st.expander("進階：原始報告文字"):
                    st.markdown(report_markdown)
        else:
            st.markdown(
                """
                <div class="result-shell">
                    <div class="section-title">等待分析結果</div>
                    <div class="section-note">
                        左側完成設定後執行分析。結果會在這裡以 HTML 卡片報告呈現，資料來源與完整文字會收在次要區塊。
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
