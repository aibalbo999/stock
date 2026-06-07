from __future__ import annotations

# ruff: noqa: F403,F405
from app.ui.dashboard_core import *


def render_data_enrichment() -> None:
    whitelist = SupplyChainWhitelist()
    allowed_tickers = sorted(whitelist.allowed_tickers())
    data_tabs = st.tabs(["市場快取與刷新", "手動補充", "RSS 匯入"])

    with data_tabs[0]:
        render_section_header("市場資料", "刷新股價、五年財報與估值資料；這些資料會影響品質門檻與投資行動限制。")
        status_snapshot = db_status()
        table_counts = status_snapshot.get("tables", {})
        count_cols = st.columns(5)
        count_cols[0].metric("股價快取", table_counts.get("stock_price_snapshots", {}).get("count") or 0)
        count_cols[1].metric("月營收快取", table_counts.get("monthly_revenue_snapshots", {}).get("count") or 0)
        count_cols[2].metric("財報三表快取", table_counts.get("financial_metric_snapshots", {}).get("count") or 0)
        count_cols[3].metric("估值快取", table_counts.get("valuation_metric_snapshots", {}).get("count") or 0)
        count_cols[4].metric("公司文件", table_counts.get("company_filings", {}).get("count") or 0)

        default_market_tickers = ["2330"] if "2330" in allowed_tickers else allowed_tickers[:1]
        selected_market_tickers = st.multiselect(
            "選擇要刷新或補文件的股票",
            options=allowed_tickers,
            default=default_market_tickers,
        )
        col_start, col_end = st.columns(2)
        with col_start:
            market_start = st.date_input("起始日期", value=today_taipei().replace(day=1), key="market_start")
        with col_end:
            market_end = st.date_input("結束日期", value=today_taipei(), key="market_end")

        has_market_selection = bool(selected_market_tickers)
        has_valid_market_range = market_start <= market_end
        if not has_market_selection:
            st.caption("請先選擇至少一檔股票。")
        if not has_valid_market_range:
            st.error("起始日期不可晚於結束日期。")

        refresh_cols = st.columns(4)
        refresh_price = refresh_cols[0].button(
            "刷新股價",
            type="primary",
            disabled=not (has_market_selection and has_valid_market_range),
        )
        refresh_financials = refresh_cols[1].button("刷新 5 年財報", disabled=not has_market_selection)
        refresh_valuations = refresh_cols[2].button(
            "刷新估值",
            disabled=not (has_market_selection and has_valid_market_range),
        )
        refresh_filings = refresh_cols[3].button("補抓公司文件", disabled=not has_market_selection)

        data_task_payload = {
            "tickers": selected_market_tickers,
            **task_payload_dates(market_start, market_end),
        }
        if refresh_price:
            try:
                task_response = queue_data_operation("market_refresh", data_task_payload)
                st.session_state["last_data_task_id"] = task_response["task_id"]
                st.session_state.pop("refresh_data_task_status_status", None)
                st.success(f"已送出股價刷新背景任務：{task_response['task_id']}")
            except requests.RequestException as exc:
                st.error(f"股價刷新任務送出失敗：{request_error_message(exc)}")

        if refresh_financials:
            try:
                task_response = queue_data_operation(
                    "fundamentals_refresh",
                    {
                        "tickers": selected_market_tickers,
                        **task_payload_dates(market_end - timedelta(days=365 * 6), market_end),
                    },
                )
                st.session_state["last_data_task_id"] = task_response["task_id"]
                st.session_state.pop("refresh_data_task_status_status", None)
                st.success(f"已送出財報刷新背景任務：{task_response['task_id']}")
            except requests.RequestException as exc:
                st.error(f"財報刷新任務送出失敗：{request_error_message(exc)}")

        if refresh_valuations:
            try:
                task_response = queue_data_operation("valuation_refresh", data_task_payload)
                st.session_state["last_data_task_id"] = task_response["task_id"]
                st.session_state.pop("refresh_data_task_status_status", None)
                st.success(f"已送出估值刷新背景任務：{task_response['task_id']}")
            except requests.RequestException as exc:
                st.error(f"估值刷新任務送出失敗：{request_error_message(exc)}")

        if refresh_filings:
            try:
                task_response = queue_data_operation(
                    "company_filings_fetch",
                    {"tickers": selected_market_tickers},
                )
                st.session_state["last_data_task_id"] = task_response["task_id"]
                st.session_state.pop("refresh_data_task_status_status", None)
                st.success(f"已送出公司文件補抓背景任務：{task_response['task_id']}")
            except requests.RequestException as exc:
                st.error(f"公司文件補抓任務送出失敗：{request_error_message(exc)}")

        last_data_task_id = st.session_state.get("last_data_task_id")
        if last_data_task_id:
            with st.expander("背景資料任務狀態", expanded=True):
                data_task_id = st.text_input("資料任務編號", value=last_data_task_id, key="data_task_id_lookup")
                render_task_status_panel(
                    task_id=data_task_id,
                    refresh_key="refresh_data_task_status",
                )
        with session_scope() as session:
            cached_snapshots = MarketRepository(session).latest_by_tickers(allowed_tickers)
            cached_valuations = ValuationMetricRepository(session).latest_by_tickers(allowed_tickers)
            cached_filings = CompanyFilingRepository(session).latest_by_tickers(allowed_tickers, limit_per_ticker=2)
            cached_financial_count = len(FinancialMetricRepository(session).by_tickers(allowed_tickers))

        cache_tabs = st.tabs(["股價快取", "估值快取", "公司文件"])
        with cache_tabs[0]:
            if cached_snapshots:
                st.dataframe(
                    [
                        {
                            "股票": snapshot.ticker,
                            "交易日": snapshot.trade_date.isoformat(),
                            "收盤價": snapshot.close,
                            "漲跌": snapshot.spread,
                            "成交量": snapshot.trading_volume,
                            "來源": snapshot.source,
                            "更新時間 UTC": snapshot.fetched_at.isoformat(timespec="seconds"),
                        }
                        for snapshot in cached_snapshots
                    ],
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info("尚無市場資料快取。")
            st.caption(f"目前財報三表科目快取：{cached_financial_count} 筆")
        with cache_tabs[1]:
            if cached_valuations:
                st.dataframe(
                    [
                        {
                            "股票": valuation.ticker,
                            "交易日": valuation.trade_date.isoformat(),
                            "本益比": valuation.pe_ratio,
                            "股價淨值比": valuation.pb_ratio,
                            "殖利率": valuation.dividend_yield,
                            "來源": valuation.source,
                            "更新時間 UTC": valuation.fetched_at.isoformat(timespec="seconds"),
                        }
                        for valuation in cached_valuations
                    ],
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info("尚無估值資料快取。")
        with cache_tabs[2]:
            if cached_filings:
                st.dataframe(
                    [
                        {
                            "股票": filing.ticker,
                            "類型": filing.document_type,
                            "標題": filing.title,
                            "來源": filing.source.publisher,
                            "日期": filing.source.published_at.isoformat()
                            if filing.source.published_at
                            else None,
                        }
                        for filing in cached_filings
                    ],
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info("尚無公司文件快取。")

    with data_tabs[1]:
        render_section_header("手動補充", "補充新聞、法說或研究摘要，讓報告可以引用具體來源。")
        input_tabs = st.tabs(["新聞/研究摘要", "公司公開文件"])
        with input_tabs[0]:
            title = st.text_input("標題")
            publisher = st.text_input("來源", value="manual")
            published_at = st.date_input("日期", value=today_taipei())
            url = st.text_input("URL")
            text = st.text_area("內文", height=260)
            manual_news_ready = bool(title.strip() and text.strip())
            if not manual_news_ready:
                st.caption("請先填入標題與內文。")
            if st.button("匯入新聞/研究摘要", type="primary", disabled=not manual_news_ready):
                document = NewsFetcher.from_manual_text(
                    title=title.strip(),
                    text=text.strip(),
                    publisher=(publisher or "manual").strip(),
                    published_at=published_at,
                    url=url.strip() or None,
                )
                VectorStore().upsert_documents([document])
                matches = EntityMapper().match_document(document)
                with session_scope() as session:
                    NewsRepository(session).upsert_document(
                        document,
                        [match.model_dump(mode="json") for match in matches],
                    )
                st.success(f"已匯入：{document.id}")

        with input_tabs[1]:
            if not allowed_tickers:
                st.warning("目前沒有可選股票代號。")
            else:
                filing_ticker = st.selectbox(
                    "股票代號",
                    options=allowed_tickers,
                    index=allowed_tickers.index("2330") if "2330" in allowed_tickers else 0,
                )
                filing_company = st.text_input(
                    "公司名稱",
                    value=next((company.name for company in whitelist.companies() if company.ticker == filing_ticker), ""),
                )
                filing_type = st.selectbox(
                    "文件類型",
                    options=["annual_report", "investor_presentation", "prospectus", "material_information", "company_disclosure"],
                    format_func=lambda value: {
                        "annual_report": "年報",
                        "investor_presentation": "法說/投資人簡報",
                        "prospectus": "公開說明書",
                        "material_information": "重大訊息",
                        "company_disclosure": "其他公司揭露",
                    }.get(value, value),
                )
                filing_title = st.text_input("文件標題", key="filing_title")
                filing_publisher = st.text_input("文件來源", value="公司 IR / MOPS", key="filing_publisher")
                filing_date = st.date_input("文件日期", value=today_taipei(), key="filing_date")
                filing_url = st.text_input("文件 URL", key="filing_url")
                filing_text = st.text_area("文件文字", height=260, key="filing_text")
                filing_text_ready = bool(filing_title.strip() and filing_text.strip())
                filing_url_ready = bool(filing_url.strip())
                if not filing_text_ready and not filing_url_ready:
                    st.caption("貼上文件文字時需有標題；或提供文件 URL 後從 URL 匯入。")
                filing_import_cols = st.columns(2)
                import_text_filing = filing_import_cols[0].button(
                    "匯入公司文件",
                    type="primary",
                    disabled=not filing_text_ready,
                )
                import_url_filing = filing_import_cols[1].button(
                    "從 URL 抓取並匯入",
                    disabled=not filing_url_ready,
                )
                if import_text_filing:
                    document = CompanyFilingFetcher.from_manual_text(
                        ticker=filing_ticker,
                        company_name=filing_company,
                        document_type=filing_type,
                        title=filing_title.strip(),
                        text=filing_text.strip(),
                        publisher=(filing_publisher or "公司 IR / MOPS").strip(),
                        published_at=filing_date,
                        url=filing_url.strip() or None,
                    )
                    news_document = CompanyFilingRepository.to_news_document(document)
                    VectorStore().upsert_documents([news_document])
                    with session_scope() as session:
                        CompanyFilingRepository(session).upsert_document(document)
                    tier = filing_source_tier(document)
                    score = filing_quality_score(document, filing_ticker, filing_company)
                    st.success(f"已匯入公司文件：{document.id}")
                    st.caption(f"來源分級：{tier}；品質分數：{score}")
                if import_url_filing:
                    try:
                        task_response = queue_data_operation(
                            "company_filing_from_url",
                            {
                                "url": filing_url.strip(),
                                "ticker": filing_ticker,
                                "company_name": filing_company,
                                "document_type": filing_type,
                                "publisher": (filing_publisher or "公司 IR / MOPS").strip(),
                                "published_at": filing_date.isoformat(),
                            },
                        )
                        st.session_state["last_data_task_id"] = task_response["task_id"]
                        st.session_state.pop("refresh_data_task_status_status", None)
                        st.success(f"已送出 URL 公司文件匯入背景任務：{task_response['task_id']}")
                    except requests.RequestException as exc:
                        st.error(f"URL 公司文件匯入任務送出失敗：{request_error_message(exc)}")

        last_data_task_id = st.session_state.get("last_data_task_id")
        if last_data_task_id:
            with st.expander("背景資料任務狀態"):
                data_task_id = st.text_input("資料任務編號", value=last_data_task_id, key="manual_data_task_id_lookup")
                render_task_status_panel(
                    task_id=data_task_id,
                    refresh_key="refresh_manual_data_task_status",
                )

    with data_tabs[2]:
        render_section_header("RSS 匯入", "從既有資料源或指定 URL 抓取最新文本。")
        source_store = NewsSourceStore()
        configured_sources = source_store.load()
        if configured_sources:
            st.dataframe(
                [source.model_dump(mode="json") for source in configured_sources],
                width="stretch",
                hide_index=True,
            )
        feed_url = st.text_input("RSS URL")
        feed_publisher = st.text_input("來源名稱", value="rss")
        feed_limit = st.number_input("抓取筆數", min_value=1, max_value=50, value=10)
        feed_ready = bool(feed_url.strip())
        if not feed_ready:
            st.caption("請先輸入 RSS URL。")
        if st.button("抓取 RSS", type="primary", disabled=not feed_ready):
            try:
                task_response = queue_data_operation(
                    "feed_fetch",
                    {
                        "url": feed_url.strip(),
                        "publisher": (feed_publisher or "rss").strip(),
                        "limit": int(feed_limit),
                    },
                )
                st.session_state["last_data_task_id"] = task_response["task_id"]
                st.session_state.pop("refresh_data_task_status_status", None)
                st.success(f"已送出 RSS 抓取背景任務：{task_response['task_id']}")
            except requests.RequestException as exc:
                st.error(f"RSS 抓取任務送出失敗：{request_error_message(exc)}")

        last_data_task_id = st.session_state.get("last_data_task_id")
        if last_data_task_id:
            with st.expander("背景資料任務狀態"):
                data_task_id = st.text_input("資料任務編號", value=last_data_task_id, key="rss_data_task_id_lookup")
                render_task_status_panel(
                    task_id=data_task_id,
                    refresh_key="refresh_rss_data_task_status",
                )
