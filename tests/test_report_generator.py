from datetime import date
from typing import Optional

from app.data_sources.news import NewsFetcher
from app.models.schemas import (
    EntityMatch,
    FinancialMetric,
    InvestorProfile,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ReportRequest,
    RiskFinding,
    RiskType,
    Source,
    ValuationMetric,
)
from app.services.entity_mapping import EntityMapper
from app.services.leading_signals import LeadingSignal, LeadingSignalAnalyzer
from app.services.llm_analysis import LLMSupplementValidator
from app.services.report_generator import ReportExecutionError, ReportGenerator
from app.services.whitelist import SupplyChainWhitelist


def make_finding(
    ticker: str,
    name: str,
    evidence: str,
    risk_type: RiskType = RiskType.short_term_volatility,
) -> RiskFinding:
    return RiskFinding(
        risk_type=risk_type,
        topic="測試主題",
        evidence=evidence,
        source=Source(title=evidence, publisher="測試新聞", published_at=date(2026, 5, 22)),
        related_companies=[
            EntityMatch(
                ticker=ticker,
                name=name,
                segment_id="test",
                segment_name="測試產業",
                matched_alias=name,
            )
        ],
    )


def unescaped_pipe_count(line: str) -> int:
    return sum(1 for index, char in enumerate(line) if char == "|" and (index == 0 or line[index - 1] != "\\"))


def make_financial_metrics(
    ticker: str,
    revenues: list[float],
    net_incomes: list[float],
    liabilities: Optional[list[float]] = None,
    equities: Optional[list[float]] = None,
) -> list[FinancialMetric]:
    years = list(range(2022, 2022 + len(revenues)))
    liabilities = liabilities or [100.0 for _ in years]
    equities = equities or [200.0 for _ in years]
    metrics: list[FinancialMetric] = []
    for year, revenue, net_income, liability, equity in zip(years, revenues, net_incomes, liabilities, equities):
        report_date = date(year, 3, 31)
        metrics.extend(
            [
                FinancialMetric(
                    ticker=ticker,
                    report_date=report_date,
                    statement_type="income_statement",
                    metric="營業收入",
                    value=revenue,
                    source="test",
                ),
                FinancialMetric(
                    ticker=ticker,
                    report_date=report_date,
                    statement_type="income_statement",
                    metric="本期淨利",
                    value=net_income,
                    source="test",
                ),
                FinancialMetric(
                    ticker=ticker,
                    report_date=report_date,
                    statement_type="balance_sheet",
                    metric="負債總額",
                    value=liability,
                    source="test",
                ),
                FinancialMetric(
                    ticker=ticker,
                    report_date=report_date,
                    statement_type="balance_sheet",
                    metric="權益總額",
                    value=equity,
                    source="test",
                ),
            ]
        )
    return metrics


def test_llm_supplement_requires_source_timestamp() -> None:
    document = NewsFetcher.from_manual_text(
        title="CoWoS 產能滿載影響 AI 伺服器交期",
        text="台積電 CoWoS 產能滿載。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    assert (
        LLMSupplementValidator.render_markdown("沒有來源的補充分析", [document])
        == "LLM 補充分析未通過來源檢查；目前無足夠數據判斷。"
    )


def test_llm_supplement_accepts_timestamped_source() -> None:
    document = NewsFetcher.from_manual_text(
        title="CoWoS 產能滿載影響 AI 伺服器交期",
        text="台積電 CoWoS 產能滿載。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    text = """
    {
      "items": [
        {
          "claim": "瓶頸在 CoWoS。",
          "source_type": "news",
          "source_date": "2026-05-20",
          "source_publisher": "測試新聞",
          "source_title": "CoWoS 產能滿載影響 AI 伺服器交期",
          "source_id": ""
        }
      ]
    }
    """

    assert LLMSupplementValidator.render_markdown(text, [document]) == (
        "- 瓶頸在 CoWoS。 來源：2026-05-20 測試新聞 CoWoS 產能滿載影響 AI 伺服器交期"
    )


def test_llm_supplement_accepts_market_source() -> None:
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        close=2255.0,
        source="FinMind TaiwanStockPrice",
    )
    text = """
    {
      "items": [
        {
          "claim": "2330 收盤價為 2255.0。",
          "source_type": "market",
          "source_date": "2026-05-22",
          "source_publisher": "FinMind TaiwanStockPrice",
          "source_title": "",
          "source_id": "2330"
        }
      ]
    }
    """

    assert LLMSupplementValidator.render_markdown(text, [], [snapshot]) == (
        "- 2330 收盤價為 2255.0。 來源：2026-05-22 FinMind TaiwanStockPrice 2330"
    )


def test_generate_keeps_last_evidence_documents_for_quality_gate() -> None:
    document = NewsFetcher.from_manual_text(
        title="台積電 CoWoS 產能滿載",
        text="台積電 CoWoS 產能滿載，AI 供應鏈交期拉長。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    class FakeRiskAnalyzer:
        def analyze_documents(self, documents):
            assert documents == [document]
            return []

    class FakeMapper:
        def filter_allowed_tickers(self, tickers):
            return tickers

    class FakeLLM:
        def generate_with_metadata(self, prompt):
            return object()

    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.last_evidence_documents = []
    generator.risk_analyzer = FakeRiskAnalyzer()
    generator.mapper = FakeMapper()
    generator.llm = FakeLLM()
    generator._latest_market_snapshots = lambda tickers: []
    generator._latest_monthly_revenues = lambda tickers: []
    generator._financial_metrics = lambda tickers: []
    generator._latest_valuations = lambda tickers: []
    generator._render_markdown = lambda *args, **kwargs: "# 測試報告"

    response = ReportGenerator.generate(
        generator,
        ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
        documents=[document],
    )

    assert response.markdown == "# 測試報告"
    assert generator.last_evidence_documents == [document]


def test_llm_evidence_digest_is_bounded_to_reduce_timeout_risk() -> None:
    documents = [
        NewsFetcher.from_manual_text(
            title=f"測試新聞 {index}",
            text=f"第 {index} 筆來源 " + ("AI 伺服器需求與供應鏈驗證。" * 80),
            publisher="測試新聞",
            published_at=date(2026, 5, 1),
        )
        for index in range(65)
    ]

    digest = ReportGenerator._format_llm_evidence(documents)

    assert "測試新聞 0" in digest
    assert "測試新聞 59" in digest
    assert "測試新聞 60" not in digest
    assert "其餘 5 筆來源保留於系統資料庫" in digest
    assert "AI 伺服器需求與供應鏈驗證。" * 20 not in digest


def test_generate_fails_when_dynamic_candidates_are_not_loaded() -> None:
    document = NewsFetcher.from_manual_text(
        title="台達電 機器人伺服驅動",
        text="台達電機器人伺服驅動與控制器需求升溫。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    class FakeRiskAnalyzer:
        def analyze_documents(self, documents):
            return []

    class FakeLLM:
        called = False

        def generate_with_metadata(self, prompt):
            self.called = True
            raise AssertionError("LLM should not be called when execution guard blocks the report")

    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    generator.risk_analyzer = FakeRiskAnalyzer()
    generator.llm = FakeLLM()
    generator.last_evidence_documents = []
    generator.last_llm_result = None
    generator.last_filtered_tickers = []
    generator.last_dropped_tickers = []

    try:
        ReportGenerator.generate(
            generator,
            ReportRequest(topic="機器人 產業鏈", tickers=["2308"]),
            documents=[document],
        )
    except ReportExecutionError as exc:
        assert "必須套用候選公司動態白名單" in str(exc)
    else:
        raise AssertionError("ReportExecutionError was not raised")

    assert generator.last_filtered_tickers == []
    assert generator.last_dropped_tickers == ["2308"]
    assert generator.llm.called is False


def test_generate_fails_when_any_requested_ticker_is_dropped() -> None:
    document = NewsFetcher.from_manual_text(
        title="AI 產業鏈",
        text="AI 伺服器與機器人供應鏈需求升溫。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    class FakeRiskAnalyzer:
        def analyze_documents(self, documents):
            return []

    class FakeLLM:
        called = False

        def generate_with_metadata(self, prompt):
            self.called = True
            raise AssertionError("LLM should not be called when one requested ticker is dropped")

    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    generator.risk_analyzer = FakeRiskAnalyzer()
    generator.llm = FakeLLM()
    generator.last_evidence_documents = []
    generator.last_llm_result = None
    generator.last_filtered_tickers = []
    generator.last_dropped_tickers = []

    try:
        ReportGenerator.generate(
            generator,
            ReportRequest(topic="AI 與機器人混合主題", tickers=["2330", "2308"]),
            documents=[document],
        )
    except ReportExecutionError as exc:
        assert "2308" in str(exc)
        assert "缺漏個股分析" in str(exc)
    else:
        raise AssertionError("ReportExecutionError was not raised")

    assert generator.last_filtered_tickers == ["2330"]
    assert generator.last_dropped_tickers == ["2308"]
    assert generator.llm.called is False


def test_generate_allows_discovered_tickers_when_dynamic_whitelist_is_loaded() -> None:
    document = NewsFetcher.from_manual_text(
        title="台達電 機器人伺服驅動",
        text="台達電機器人伺服驅動與控制器需求升溫。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "2308",
                "name": "台達電",
                "segment": "伺服驅動與控制系統",
                "status": "evidence_supported",
                "evidence_keywords": ["伺服", "控制器", "機器人"],
            }
        ]
    )

    class FakeRiskAnalyzer:
        def analyze_documents(self, documents):
            return []

    class FakeLLM:
        def generate_with_metadata(self, prompt):
            return type("Result", (), {"text": "{}", "fallback": True, "model": None, "key_index": None})()

    generator = object.__new__(ReportGenerator)
    generator.whitelist = whitelist
    generator.mapper = EntityMapper(generator.whitelist)
    generator.risk_analyzer = FakeRiskAnalyzer()
    generator.llm = FakeLLM()
    generator.last_evidence_documents = []
    generator.last_llm_result = None
    generator.last_filtered_tickers = []
    generator.last_dropped_tickers = []
    generator._latest_market_snapshots = lambda tickers: []
    generator._latest_monthly_revenues = lambda tickers: []
    generator._financial_metrics = lambda tickers: []
    generator._latest_valuations = lambda tickers: []
    generator._leading_signals = lambda tickers, valuations: {}
    generator._render_markdown = lambda *args, **kwargs: "# 測試報告"

    response = ReportGenerator.generate(
        generator,
        ReportRequest(topic="機器人 產業鏈", tickers=["2308"]),
        documents=[document],
    )

    assert response.markdown == "# 測試報告"
    assert generator.last_filtered_tickers == ["2308"]
    assert generator.last_dropped_tickers == []


def test_company_analysis_and_recommendations_do_not_overstate_market_only_data() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        close=2255.0,
        spread=25.0,
        trading_volume=26823133,
        source="FinMind TaiwanStockPrice",
    )

    company_analysis = generator._render_company_analysis(["2330"], [], [], [snapshot])
    recommendations = generator._render_investment_recommendations(
        ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
        ["2330"],
        [],
        [],
        [snapshot],
    )

    assert "### 2330 台積電" in company_analysis
    assert "### 個股速覽" in company_analysis
    assert "| 股票 | 產業位置 | 股價 | 當下股價標籤 | 月營收 | 目前估值位置 | 財務信心 | 證據狀態 |" in company_analysis
    assert "| 2330 台積電 |" in company_analysis
    assert "#### 華爾街式完整分析框架" in company_analysis
    assert "商業模式與收入來源" in company_analysis
    assert "#### 已揭露年度財務檢查" in company_analysis
    assert "#### 競爭護城河" in company_analysis
    assert "#### 估值分析" in company_analysis
    assert "#### 未來成長假設" in company_analysis
    assert "#### 多空辯論" in company_analysis
    assert "#### 是否應該投資" in company_analysis
    assert "淨利趨勢：目前無足夠數據判斷" in company_analysis
    assert "P/E 與同業比較：目前無足夠數據判斷" in company_analysis
    assert "新聞/研究證據：目前無足夠數據判斷" in company_analysis
    assert "觀察 / 資料不足" in recommendations
    assert "缺少新聞、財報或法說證據" in recommendations


def test_report_reading_order_groups_by_decision_then_current_price() -> None:
    contexts = [
        {
            "ticker": "9999",
            "decision": "避開 / 降低曝險",
            "snapshot": MarketSnapshot(ticker="9999", trade_date=date(2026, 5, 22), close=5000.0),
            "estimate": {"upside_pct": 30, "downside_pct": 40},
        },
        {
            "ticker": "2382",
            "decision": "可小額分批研究",
            "snapshot": MarketSnapshot(ticker="2382", trade_date=date(2026, 5, 22), close=300.0),
            "estimate": {"upside_pct": 18, "downside_pct": 3},
        },
        {
            "ticker": "2330",
            "decision": "可小額分批研究",
            "snapshot": MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=1000.0),
            "estimate": {"upside_pct": 12, "downside_pct": 4},
        },
        {
            "ticker": "2308",
            "decision": "觀察 / 等風險降低",
            "snapshot": MarketSnapshot(ticker="2308", trade_date=date(2026, 5, 22), close=200.0),
            "estimate": {"upside_pct": 24, "downside_pct": 11},
        },
    ]

    ordered = ReportGenerator._sort_decision_contexts(contexts)

    assert [context["ticker"] for context in ordered] == ["2330", "2382", "2308", "9999"]


def test_company_analysis_orders_rows_and_details_for_readability() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(topic="AI 產業鏈", tickers=["2382", "2330"])
    snapshots = [
        MarketSnapshot(ticker="2382", trade_date=date(2026, 5, 22), close=300.0),
        MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=1000.0),
    ]

    company_analysis = generator._render_company_analysis(
        ["2382", "2330"],
        [],
        [],
        snapshots,
        request=request,
    )

    assert "排序：先依判斷結果分組" in company_analysis
    assert company_analysis.index("| 2330 台積電 |") < company_analysis.index("| 2382 廣達 |")
    assert company_analysis.index("### 2330 台積電") < company_analysis.index("### 2382 廣達")


def test_complete_market_data_still_requires_company_filings_for_actionable_rating() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    generator._company_filing_missing = lambda ticker, documents: ["缺公司公開文件（年報）"]
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"], beginner_mode=False)
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=1000.0)
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 30),
        revenue=300_000_000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=20.0,
    )
    metrics = [
        FinancialMetric(
            ticker="2330",
            report_date=date(2025, 12, 31),
            statement_type="income_statement",
            metric="營業收入",
            value=1000.0,
            source="FinMind TaiwanStockFinancialStatements",
        )
    ]
    valuation = ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=18.0)
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 AI 需求成長",
            text="台積電 AI 需求成長，先進製程需求強勁。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 擴產",
            text="台積電 CoWoS 擴產帶動 AI 伺服器供應鏈。",
            publisher="測試新聞",
            published_at=date(2026, 5, 21),
        ),
    ]

    snapshot_markdown = generator._render_executive_snapshot(
        request,
        ["2330"],
        documents,
        [],
        [snapshot],
        [revenue],
        metrics,
        [valuation],
    )
    recommendations = generator._render_investment_recommendations(
        request,
        ["2330"],
        documents,
        [],
        [snapshot],
        [revenue],
        metrics,
        [valuation],
    )

    assert "| 2330 台積電 | 觀察 / 資料待補 | 2026-05-22 收盤 1000 | 觀察等待 | 待補 |" in snapshot_markdown
    assert "品質門檻最多允許研究約" in snapshot_markdown
    assert "本次實際配置以投資建議與資金控管為準" in snapshot_markdown
    assert "缺公司公開文件（年報）" in snapshot_markdown
    assert "觀察 / 資料待補" in recommendations
    assert "且資料層完整" not in recommendations


def test_company_analysis_uses_financial_and_valuation_data() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=2255.0)
    metrics = [
        FinancialMetric(
            ticker="2330",
            report_date=date(2022, 12, 31),
            statement_type="income_statement",
            metric="營業收入",
            value=1000,
            source="FinMind TaiwanStockFinancialStatements",
        ),
        FinancialMetric(
            ticker="2330",
            report_date=date(2026, 12, 31),
            statement_type="income_statement",
            metric="營業收入",
            value=1500,
            source="FinMind TaiwanStockFinancialStatements",
        ),
        FinancialMetric(
            ticker="2330",
            report_date=date(2026, 12, 31),
            statement_type="balance_sheet",
            metric="負債總計",
            value=400,
            source="FinMind TaiwanStockBalanceSheet",
        ),
        FinancialMetric(
            ticker="2330",
            report_date=date(2026, 12, 31),
            statement_type="balance_sheet",
            metric="權益總計",
            value=1000,
            source="FinMind TaiwanStockBalanceSheet",
        ),
    ]
    valuations = [
        ValuationMetric(
            ticker="2330",
            trade_date=date(2026, 5, 22),
            pe_ratio=24.5,
            pb_ratio=5.8,
            dividend_yield=1.6,
        ),
        ValuationMetric(
            ticker="2382",
            trade_date=date(2026, 5, 22),
            pe_ratio=12.5,
            pb_ratio=2.8,
            dividend_yield=4.0,
        )
    ]

    company_analysis = generator._render_company_analysis(
        ["2330", "2382"],
        [],
        [],
        [snapshot],
        [],
        metrics,
        valuations,
    )

    assert "2022 年度至 2026 年度營收成長 50.00%" in company_analysis
    assert "2026 年度負債權益比約 0.40 倍" in company_analysis
    assert "資料信心：低；目前估值位置：目前估值偏高。" in company_analysis
    assert "#### 公司基本介紹" in company_analysis
    assert "- 基本定位：2330 台積電，本報告歸類在「晶圓代工」。" in company_analysis
    assert "- 常見名稱/代號：TSMC、Taiwan Semiconductor、台灣積體電路" in company_analysis
    assert "| 2330 台積電 | 晶圓代工 | 2026-05-22 收盤 2255.0 | 等風險下降 | 缺 | 目前估值偏高 | 低 |" in company_analysis
    assert "P/E 24.50、P/B 5.80、殖利率 1.60%" in company_analysis
    assert "P/E 高於同業平均 18.50" in company_analysis
    assert "P/B 高於同業平均 4.30" in company_analysis


def test_company_basic_intro_uses_dynamic_candidate_context() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "2308",
                "name": "台達電",
                "segment": "伺服驅動與控制系統",
                "rationale": "電源、伺服驅動與控制器可支援機器人平台",
                "evidence_keywords": ["伺服驅動", "控制器", "機器人"],
                "status": "evidence_supported",
            }
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)
    document = NewsFetcher.from_manual_text(
        title="台達電 機器人伺服驅動",
        text="台達電 2308 機器人伺服驅動與控制器需求升溫。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    company_analysis = generator._render_company_analysis(
        ["2308"],
        [document],
        [],
        [],
        [],
        [],
        [],
    )

    assert "#### 公司基本介紹" in company_analysis
    assert "基本定位：2308 台達電，本報告歸類在「伺服驅動與控制系統」。電源、伺服驅動與控制器可支援機器人平台。" in company_analysis
    assert "本主題關聯關鍵字：伺服驅動、控制器、機器人" in company_analysis
    assert "另有 1 筆公司相關文本、1 個來源供交叉檢查" in company_analysis


def test_company_analysis_operation_conclusion_matches_investment_decision() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"], investor_profile=InvestorProfile.aggressive)
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=100)
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=1000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=35,
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 AI 需求成長",
            text="台積電 AI 需求成長。",
            publisher="測試新聞A",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 大單",
            text="台積電 CoWoS 大單。",
            publisher="測試新聞B",
            published_at=date(2026, 5, 21),
        ),
    ]
    findings = [make_finding("2330", "台積電", "台積電 AI 需求成長", RiskType.opportunity_or_growth)]
    metrics = make_financial_metrics(
        "2330",
        revenues=[100, 90, 80, 70, 60],
        net_incomes=[10, 5, 1, -2, -5],
        liabilities=[250, 260, 270, 280, 300],
        equities=[100, 100, 100, 100, 100],
    )
    valuation = ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=80, pb_ratio=10)

    company_analysis = generator._render_company_analysis(
        ["2330"],
        documents,
        findings,
        [snapshot],
        [revenue],
        metrics,
        [valuation],
        request=request,
    )

    assert "本次操作結論：避開 / 降低曝險" in company_analysis
    assert "此結論沿用投資建議總表" in company_analysis
    assert "最終結論：持有" not in company_analysis


def test_company_analysis_uses_official_filings_to_reduce_generic_data_gaps() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    filing = NewsDocument(
        id="filing-demo",
        title="股東會年報",
        text="2330 台積電\n文件類型：annual_report\nAI 伺服器 CoWoS 先進製程 客戶 認證 產能",
        source=Source(title="股東會年報", publisher="公開資訊觀測站 MOPS", published_at=date(2026, 5, 21)),
    )
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 1),
        revenue=410_725_118_000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=25.0,
    )
    valuation = ValuationMetric(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        pe_ratio=24.5,
        pb_ratio=5.8,
    )

    company_analysis = generator._render_company_analysis(
        ["2330"],
        [filing],
        [],
        [],
        [revenue],
        [],
        [valuation],
    )

    assert "已納入 1 份官方/公司公開文件" in company_analysis
    assert "可用 P/E 24.50 作為相對估值交叉檢查" in company_analysis
    assert "月營收年增 25.00%" in company_analysis
    assert "硬體與供應鏈公司通常不是典型網路效應" in company_analysis


def test_company_comparison_matrix_summarizes_decision_valuation_and_confidence() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    generator._company_filing_missing = lambda ticker, documents: []
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"])
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=2255.0)
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 1),
        revenue=410_725_118_000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=25.0,
    )
    metrics = [
        FinancialMetric(
            ticker="2330",
            report_date=date(2026, 3, 31),
            statement_type="income_statement",
            metric="營業收入",
            value=1,
            source="test",
        )
        for _ in range(40)
    ]
    valuations = [
        ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=30, pb_ratio=8),
        ValuationMetric(ticker="2382", trade_date=date(2026, 5, 22), pe_ratio=12, pb_ratio=3),
    ]
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 AI 需求成長",
            text="台積電 AI 需求成長。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 大單",
            text="台積電 CoWoS 大單。",
            publisher="測試新聞",
            published_at=date(2026, 5, 21),
        ),
    ]
    findings = [
        make_finding(
            "2330",
            "台積電",
            "台積電 CoWoS 需求成長",
            RiskType.opportunity_or_growth,
        )
    ]

    matrix = generator._render_company_comparison_matrix(
        request,
        ["2330"],
        documents,
        findings,
        [snapshot],
        [revenue],
        metrics,
        valuations,
    )

    assert "個股比較矩陣" not in matrix
    assert "| 股票 | 判斷 | 目前股價 | 當下股價標籤 | 目前情境升值分 | 目前情境降值分 | 目前估值位置 | 財務信心 | 核心提醒 |" in matrix
    assert "| 2330 台積電 | 觀察 / 等風險降低 |" in matrix
    assert "等風險下降" in matrix
    assert "估值偏高" in matrix
    assert "高" in matrix


def test_investment_thesis_map_explains_reasons_sources_and_limits() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    generator._company_filing_missing = lambda ticker, documents: []
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"], beginner_mode=False)
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=2255.0)
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 1),
        revenue=410_725_118_000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=25.0,
    )
    metrics = [
        FinancialMetric(
            ticker="2330",
            report_date=date(2026, 3, 31),
            statement_type="income_statement",
            metric="營業收入",
            value=1,
            source="test",
        )
        for _ in range(40)
    ]
    valuation = ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=18, pb_ratio=4)
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 AI 需求成長",
            text="台積電 AI 需求成長。",
            publisher="測試新聞A",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 大單",
            text="台積電 CoWoS 大單。",
            publisher="測試新聞B",
            published_at=date(2026, 5, 21),
        ),
    ]
    findings = [
        make_finding(
            "2330",
            "台積電",
            "台積電 CoWoS 需求成長",
            RiskType.opportunity_or_growth,
        )
    ]

    thesis = generator._render_investment_thesis_map(
        request,
        ["2330"],
        documents,
        findings,
        [snapshot],
        [revenue],
        metrics,
        [valuation],
    )

    assert "## 投資理由地圖" not in thesis
    assert "這是研究假設，不是報酬保證或買賣指令" in thesis
    assert "### 2330 台積電" in thesis
    assert "具體投資理由" in thesis
    assert "目前情境升值分" in thesis
    assert "代表性來源：2026-05-20 測試新聞A《台積電 AI 需求成長》" in thesis


def test_early_potential_radar_prioritizes_low_attention_strengthening_signals() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"])
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=100)
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 1),
        revenue=100,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=35,
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 AI 需求成長",
            text="台積電 AI 需求成長。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 大單",
            text="台積電 CoWoS 大單。",
            publisher="測試新聞",
            published_at=date(2026, 5, 21),
        ),
    ]
    signal = LeadingSignal(
        ticker="2330",
        score=7,
        upside_bonus=7,
        downside_penalty=0,
        bullish_factors=["月營收年增 35.0%"],
    )

    radar = generator._render_early_potential_radar(
        request,
        ["2330"],
        documents,
        [],
        [snapshot],
        [revenue],
        {"2330": signal},
    )

    assert "早期線索分" in radar
    assert "報導較少" in radar
    assert "台積電" in radar
    assert "報導較少不是利多" in radar


def test_early_potential_profile_penalizes_crowded_ideas() -> None:
    documents = [
        NewsFetcher.from_manual_text(
            title=f"台積電 AI 新聞 {index}",
            text="台積電 AI 需求成長。",
            publisher=f"媒體{index}",
            published_at=date(2026, 5, 20),
        )
        for index in range(20)
    ]

    profile = ReportGenerator._early_potential_profile(documents, None, None, 30, 0)

    assert profile["attention_label"] == "截至目前大量報導"
    assert profile["early_potential_reason"] == "截至目前題材已被大量報導，較不像尚未被市場發現。"


def test_early_potential_profile_penalizes_high_turnover_names() -> None:
    snapshot = MarketSnapshot(
        ticker="3037",
        trade_date=date(2026, 5, 29),
        close=1055,
        trading_money=22_254_481_820,
        source="FinMind TaiwanStockPrice",
    )

    profile = ReportGenerator._early_potential_profile([], None, None, 30, 0, snapshot)

    assert profile["attention_label"] == "截至目前成交熱度高"
    assert "較不像尚未被市場注意的冷門線索" in profile["early_potential_reason"]


def test_early_potential_radar_uses_candidate_audit_evidence_counts() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "3037",
                "name": "欣興",
                "segment": "PCB",
                "rationale": "AI 伺服器載板",
                "evidence_keywords": ["AI 伺服器", "PCB"],
                "evidence_count": 13,
                "evidence_source_count": 9,
                "evidence_titles": [],
                "status": "evidence_supported",
                "validation_reason": "通過正式分析門檻。",
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)
    request = ReportRequest(topic="AI 產業鏈", tickers=["3037"])
    snapshot = MarketSnapshot(
        ticker="3037",
        trade_date=date(2026, 5, 22),
        close=180.0,
        source="FinMind TaiwanStockPrice",
    )
    revenue = MonthlyRevenue(
        ticker="3037",
        revenue_date=date(2026, 5, 1),
        revenue=100,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=35,
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="欣興 AI 伺服器載板需求",
            text="欣興 AI 伺服器 PCB 載板需求成長。",
            publisher="公司文本",
            published_at=date(2026, 5, 20),
        )
    ]
    signal = LeadingSignal(
        ticker="3037",
        score=7,
        upside_bonus=7,
        downside_penalty=0,
        bullish_factors=["月營收年增 35.0%"],
    )

    radar = generator._render_early_potential_radar(
        request,
        ["3037"],
        documents,
        [],
        [snapshot],
        [revenue],
        {"3037": signal},
    )

    assert "3037 欣興" not in radar
    assert "報導較少 |" not in radar
    assert "公司文本 1 筆 / 1 來源" not in radar


def test_early_potential_radar_excludes_avoid_decisions() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "4540",
                "name": "盟立",
                "segment": "自動化設備",
                "rationale": "機器人自動化",
                "evidence_keywords": ["機器人"],
                "status": "evidence_supported",
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)
    request = ReportRequest(topic="機器人 產業鏈", tickers=["4540"])
    snapshot = MarketSnapshot(
        ticker="4540",
        trade_date=date(2026, 5, 29),
        close=68.6,
        source="FinMind TaiwanStockPrice",
    )
    revenue = MonthlyRevenue(
        ticker="4540",
        revenue_date=date(2026, 5, 1),
        revenue=100,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=35,
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="盟立機器人自動化需求成長",
            text="盟立機器人自動化需求成長。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        )
    ]
    signal = LeadingSignal(
        ticker="4540",
        score=-6,
        upside_bonus=7,
        downside_penalty=25,
        bearish_factors=["20 日股價動能轉弱"],
    )

    radar = generator._render_early_potential_radar(
        request,
        ["4540"],
        documents,
        [],
        [snapshot],
        [revenue],
        {"4540": signal},
    )

    assert "4540 盟立" not in radar
    assert "已排除避開/降低曝險標的" in radar


def test_financial_summary_ignores_percentage_and_total_liability_equity_fields() -> None:
    metrics = [
        FinancialMetric(
            ticker="2330",
            report_date=date(2026, 3, 31),
            statement_type="income_statement",
            metric="IncomeAfterTaxes",
            origin_name="本期淨利（淨損）",
            value=572_801_304_000,
            source="FinMind TaiwanStockFinancialStatements",
        ),
        FinancialMetric(
            ticker="2330",
            report_date=date(2026, 3, 31),
            statement_type="balance_sheet",
            metric="Liabilities",
            origin_name="負債總額",
            value=2_728_560_764_000,
            source="FinMind TaiwanStockBalanceSheet",
        ),
        FinancialMetric(
            ticker="2330",
            report_date=date(2026, 3, 31),
            statement_type="balance_sheet",
            metric="Liabilities_per",
            origin_name="負債總額",
            value=31.5,
            source="FinMind TaiwanStockBalanceSheet",
        ),
        FinancialMetric(
            ticker="2330",
            report_date=date(2026, 3, 31),
            statement_type="balance_sheet",
            metric="CurrentContractLiabilities",
            origin_name="合約負債",
            value=12_000_000,
            source="FinMind TaiwanStockBalanceSheet",
        ),
        FinancialMetric(
            ticker="2330",
            report_date=date(2026, 3, 31),
            statement_type="balance_sheet",
            metric="TotalLiabilitiesEquity",
            origin_name="負債及權益總計",
            value=8_660_949_685_000,
            source="FinMind TaiwanStockBalanceSheet",
        ),
        FinancialMetric(
            ticker="2330",
            report_date=date(2026, 3, 31),
            statement_type="balance_sheet",
            metric="Equity",
            origin_name="權益總額",
            value=5_932_388_921_000,
            source="FinMind TaiwanStockBalanceSheet",
        ),
        FinancialMetric(
            ticker="2330",
            report_date=date(2026, 3, 31),
            statement_type="balance_sheet",
            metric="Equity_per",
            origin_name="權益總額",
            value=68.5,
            source="FinMind TaiwanStockBalanceSheet",
        ),
    ]

    summary = ReportGenerator._financial_statement_summary(metrics)

    assert "2026 年度負債權益比約 0.46 倍" in summary["debt_trend"]
    assert "2026 年度 ROE 約 9.66%" in summary["roe_trend"]
    assert "687799687000.00%" not in summary["roe_trend"]


def test_financial_assessment_uses_total_liabilities_not_contract_liabilities() -> None:
    metrics = [
        FinancialMetric(
            ticker="4583",
            report_date=date(2026, 3, 31),
            statement_type="balance_sheet",
            metric="Equity",
            origin_name="權益總額",
            value=9_672_704_000,
            source="FinMind TaiwanStockBalanceSheet",
        ),
        FinancialMetric(
            ticker="4583",
            report_date=date(2026, 3, 31),
            statement_type="balance_sheet",
            metric="Liabilities",
            origin_name="負債總額",
            value=1_910_837_000,
            source="FinMind TaiwanStockBalanceSheet",
        ),
        FinancialMetric(
            ticker="4583",
            report_date=date(2026, 3, 31),
            statement_type="balance_sheet",
            metric="CurrentContractLiabilities",
            origin_name="合約負債",
            value=21_324_000,
            source="FinMind TaiwanStockBalanceSheet",
        ),
    ]

    summary = ReportGenerator._financial_statement_summary(metrics)
    assessment = ReportGenerator._financial_valuation_assessment(metrics)

    assert "負債權益比約 0.20 倍" in summary["debt_trend"]
    assert "負債權益比約 0.20 倍" in assessment["summary"]
    assert "負債權益比約 0.00 倍" not in assessment["summary"]


def test_valuation_position_and_financial_confidence_labels() -> None:
    peer = {"pe_avg": 20.0, "pb_avg": 5.0, "count": 3}

    assert ReportGenerator._valuation_position_label(
        ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=30, pb_ratio=8),
        peer,
    ) == "目前估值偏高"
    assert ReportGenerator._valuation_position_label(
        ValuationMetric(ticker="2382", trade_date=date(2026, 5, 22), pe_ratio=12, pb_ratio=3),
        peer,
    ) == "目前估值低於同業"
    assert ReportGenerator._valuation_position_label(
        ValuationMetric(ticker="4540", trade_date=date(2026, 5, 22), pe_ratio=None, pb_ratio=3),
        peer,
        has_negative_profitability=True,
    ) == "獲利為負，不判低估"
    assert ReportGenerator._financial_confidence_label(
        [FinancialMetric(ticker="2330", report_date=date(2026, 3, 31), statement_type="income_statement", metric="營業收入", value=1, source="test") for _ in range(40)],
        ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=20, pb_ratio=5),
        MonthlyRevenue(ticker="2330", revenue_date=date(2026, 4, 1), revenue=1, revenue_year=2026, revenue_month=4),
    ) == "高"


def test_current_price_label_summarizes_immediate_entry_condition() -> None:
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=100)
    quality = {"missing": [], "grade": "supported"}
    assert (
        ReportGenerator._current_price_label(
            snapshot,
            {"upside_pct": 18, "downside_pct": 4},
            quality,
            "目前估值接近同業",
            None,
            "可小額分批研究",
            5,
        )
        == "可小額分批"
    )
    assert (
        ReportGenerator._current_price_label(
            snapshot,
            {"upside_pct": 18, "downside_pct": 14},
            quality,
            "目前估值偏高",
            None,
            "避開 / 降低曝險",
            5,
        )
        == "不適合追價"
    )


def test_time_scope_note_distinguishes_current_history_and_scenario_scores() -> None:
    note = ReportGenerator._render_time_scope_note(
        ReportRequest(topic="AI 產業鏈", tickers=["2330"], lookback_days=21),
        [MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=100)],
        [
            MonthlyRevenue(
                ticker="2330",
                revenue_date=date(2026, 4, 10),
                revenue=1,
                revenue_year=2026,
                revenue_month=4,
            )
        ],
        [ValuationMetric(ticker="2330", trade_date=date(2026, 5, 20), pe_ratio=20)],
    )

    assert "「目前」指本報告生成時間" in note
    assert "近 21 天來源" in note
    assert "目前估值" in note
    assert "不是未來估值預測" in note
    assert "當下股價標籤" in note
    assert "不是預期報酬率、目標價或保證幅度" in note
    assert "不是未來走勢預測" in note


def test_decision_criteria_note_explains_financial_red_flags_and_actionable_rules() -> None:
    note = ReportGenerator._render_decision_criteria_note(
        ReportRequest(topic="AI 產業鏈", tickers=["2330"], investor_profile=InvestorProfile.aggressive)
    )

    assert "目前情境降值分超過 12 分" in note
    assert "單純超過投資人門檻會先列觀察" in note
    assert "可小額分批研究" in note
    assert "財務/估值檢查" in note
    assert "財務紅旗存在" in note
    assert "當下股價標籤" in note


def test_executive_snapshot_summarizes_decisions_in_table() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"], investor_capital=1_000_000)
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        close=2255.0,
        source="FinMind TaiwanStockPrice",
    )
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=349567000000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=18.5,
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 需求成長",
            text="台積電 CoWoS 需求成長。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 先進封裝擴產受惠",
            text="台積電 先進封裝擴產受惠 AI 大單。",
            publisher="測試新聞",
            published_at=date(2026, 5, 21),
        ),
    ]

    snapshot_text = generator._render_executive_snapshot(
        request,
        ["2330"],
        documents,
        [make_finding("2330", "台積電", "台積電 先進封裝擴產受惠 AI 大單。", RiskType.opportunity_or_growth)],
        [snapshot],
        [revenue],
    )

    assert "**重點提醒：本次有 1 檔可小額研究" in snapshot_text
    assert "| 股票 | 判斷 | 目前股價 | 當下股價標籤 | 資料等級 | 目前情境升值分 | 目前情境降值分 | 近況訊號 | 主要缺口 |" in snapshot_text
    assert "| 2330 台積電 | 可小額分批研究 | 2026-05-22 收盤 2255 | 可小額分批 | 完整 |" in snapshot_text
    assert "| 可小額研究 | 1 檔 |" in snapshot_text


def test_action_checklist_groups_research_and_watch_items() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330", "2382"], investor_capital=1_000_000)
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        close=2255.0,
        source="FinMind TaiwanStockPrice",
    )
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=349567000000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=18.5,
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 需求成長",
            text="台積電 CoWoS 需求成長。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 先進封裝擴產受惠",
            text="台積電 先進封裝擴產受惠 AI 大單。",
            publisher="測試新聞",
            published_at=date(2026, 5, 21),
        ),
    ]

    checklist = generator._render_action_checklist(
        request,
        ["2330", "2382"],
        documents,
        [make_finding("2330", "台積電", "台積電 先進封裝擴產受惠 AI 大單。", RiskType.opportunity_or_growth)],
        [snapshot],
        [revenue],
    )

    assert "### 可立即研究" in checklist
    assert "2330 台積電：可看資金控管建議中的首筆配置" in checklist
    assert "### 待補資料 / 觀察" in checklist
    assert "2382 廣達：資料不足" in checklist
    assert "重新評估條件" in checklist


def test_final_potential_screen_reports_upside_and_downside_thresholds() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        close=2255.0,
        source="FinMind TaiwanStockPrice",
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 需求成長且產能滿載",
            text="台積電 CoWoS 需求成長。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 先進封裝擴產受惠 AI 大單",
            text="台積電 先進封裝擴產受惠 AI 大單。",
            publisher="測試新聞",
            published_at=date(2026, 5, 21),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 產能不足帶來交期風險",
            text="台積電 CoWoS 產能不足帶來交期風險。",
            publisher="測試新聞",
            published_at=date(2026, 5, 22),
        ),
    ]
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=349567000000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=18.5,
    )
    findings = [
        RiskFinding(
            risk_type=RiskType.short_term_volatility,
            topic="CoWoS 產能",
            evidence="台積電 CoWoS 產能不足帶來交期風險。",
            source=Source(
                title="台積電 CoWoS 產能不足帶來交期風險",
                publisher="測試新聞",
                published_at=date(2026, 5, 22),
            ),
            related_companies=[
                EntityMatch(
                    ticker="2330",
                    name="台積電",
                    segment_id="foundry",
                    segment_name="晶圓代工",
                    matched_alias="台積電",
                )
            ],
        )
    ]

    screen = generator._render_final_potential_screen(["2330"], documents, findings, [snapshot], [revenue])

    assert "目前證據的情境升值分約" in screen
    assert "目前證據的情境降值分約" in screen
    assert "2330 台積電" in screen


def test_monthly_revenue_check_and_estimate_use_yoy() -> None:
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        close=2255.0,
        source="FinMind TaiwanStockPrice",
    )
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=349567000000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=18.5,
    )

    estimate = ReportGenerator._estimate_potential([], [], snapshot, revenue)
    check = ReportGenerator._render_revenue_check(["2330"], [revenue])

    assert estimate["upside_pct"] > 10
    assert "月營收年增率 18.50%" in estimate["upside_reason"]
    assert ("月營收年增率 18.50%", 2) in estimate["upside_factors"]
    assert "月營收用來確認題材是否反映到公司基本面" in check
    assert "年增率 18.50%" in check


def test_estimate_potential_reads_document_body_for_risk_keywords() -> None:
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=100)
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 AI 需求",
            text="法人提醒毛利下滑與庫存風險仍需觀察。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 先進封裝",
            text="AI 需求成長，但產能不足可能延遲出貨。",
            publisher="測試新聞",
            published_at=date(2026, 5, 21),
        ),
    ]

    estimate = ReportGenerator._estimate_potential(documents, [], snapshot)

    assert estimate["downside_pct"] > 5
    assert any("負向字詞" in label for label, _score in estimate["downside_factors"])


def test_financial_red_flag_blocks_actionable_decision() -> None:
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=100)
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=1000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=30,
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 AI 需求成長",
            text="台積電 AI 需求成長。",
            publisher="測試新聞A",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 大單",
            text="台積電 CoWoS 大單。",
            publisher="測試新聞B",
            published_at=date(2026, 5, 21),
        ),
    ]
    findings = [make_finding("2330", "台積電", "台積電 AI 需求成長", RiskType.opportunity_or_growth)]
    metrics = make_financial_metrics(
        "2330",
        revenues=[100, 90, 80, 70, 60],
        net_incomes=[10, 8, 4, 1, -5],
        liabilities=[200, 220, 240, 260, 300],
        equities=[100, 100, 100, 100, 100],
    )
    valuation = ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=80, pb_ratio=10)

    estimate = ReportGenerator._estimate_potential(
        documents,
        findings,
        snapshot,
        revenue,
        None,
        metrics,
        valuation,
        {"pe_avg": 20, "pb_avg": 2, "count": 4},
    )
    quality = ReportGenerator._data_quality_grade(
        documents,
        findings,
        snapshot,
        revenue,
        metrics,
        valuation,
        True,
        None,
        [],
    )
    decision = ReportGenerator._decision_label(estimate, quality, findings, 12)
    reason = ReportGenerator._decision_reason(
        decision,
        estimate,
        quality,
        findings,
        documents,
        12,
        ReportRequest(topic="AI 產業鏈", tickers=["2330"], investor_profile=InvestorProfile.aggressive),
    )

    assert estimate["financial_red_flag"] is True
    assert decision == "避開 / 降低曝險"
    assert "財務/估值紅旗" in reason


def test_score_breakdown_explains_factors_and_data_quality() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        close=2255.0,
        source="FinMind TaiwanStockPrice",
    )
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=349567000000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=18.5,
    )

    breakdown = generator._render_score_breakdown(["2330"], [], [], [snapshot], [revenue])

    assert "| 股票 | 目前情境升值分 | 目前情境降值分 | 主要加分 | 主要風險 | 資料提醒 |" in breakdown
    assert "| 2330 台積電 |" in breakdown
    assert "月營收年增率 18.50% +2" in breakdown
    assert "公司相關文本僅 0 筆" in breakdown


def test_data_quality_section_explains_complete_and_missing_layers() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 需求成長",
            text="台積電 CoWoS 需求成長。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 先進封裝擴產",
            text="台積電 先進封裝擴產受惠 AI 需求。",
            publisher="測試新聞",
            published_at=date(2026, 5, 21),
        ),
    ]
    findings = [
        RiskFinding(
            risk_type=RiskType.short_term_volatility,
            topic="需求成長",
            evidence="台積電 CoWoS 需求成長。",
            source=Source(title="台積電 CoWoS 需求成長", publisher="測試新聞", published_at=date(2026, 5, 20)),
            related_companies=[
                EntityMatch(
                    ticker="2330",
                    name="台積電",
                    segment_id="foundry",
                    segment_name="晶圓代工",
                    matched_alias="台積電",
                )
            ],
        )
    ]
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=2255.0)
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=349567000000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=18.5,
    )

    section = generator._render_data_quality(
        ["2330", "2382"],
        documents,
        findings,
        [snapshot],
        [revenue],
    )

    assert "2330 台積電" in section
    assert "近況訊號" in section
    assert "完整，可進入二次篩選" in section
    assert "2382 廣達" in section
    assert "不足：公司文本不足、缺主題歸因、缺股價、缺月營收" in section
    assert "完整 1 檔、部分可用 0 檔、資料不足 1 檔" in section


def test_source_coverage_summarizes_international_sources() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    documents = [
        NewsFetcher.from_manual_text(
            title="NVIDIA AI server supply chain Taiwan ODM",
            text="NVIDIA AI server supply chain mentions Quanta.",
            publisher="NVIDIA Blog",
            published_at=date(2026, 5, 24),
        ),
        NewsFetcher.from_manual_text(
            title="廣達 AI 伺服器出貨成長",
            text="廣達 AI 伺服器出貨成長。",
            publisher="測試新聞",
            published_at=date(2026, 5, 23),
        ),
    ]

    section = generator._render_source_coverage(
        ReportRequest(topic="AI 產業鏈", tickers=["2382"], evidence_limit=120),
        ["2382"],
        documents,
    )

    assert "國際來源 | 1 筆" in section
    assert "摘要使用證據上限 | 120 筆" in section
    assert "可追溯證據池總量 | 2 筆" in section
    assert "報告證據上限" not in section
    assert "實際納入證據" not in section
    assert "### 個股來源覆蓋" in section
    assert "| 2382 廣達 | 2 | 1 | 2026-05-24 |" in section


def test_credibility_check_summarizes_traceability_and_company_limits() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"], lookback_days=21)
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 需求成長",
            text="台積電 CoWoS 需求成長。",
            publisher="測試新聞A",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 先進封裝擴產受惠",
            text="台積電 先進封裝擴產受惠 AI 大單。",
            publisher="測試新聞B",
            published_at=date(2026, 5, 21),
        ),
    ]
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=2255.0)
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=349567000000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=18.5,
    )

    section = generator._render_credibility_check(
        request,
        ["2330"],
        documents,
        [make_finding("2330", "台積電", "台積電 CoWoS 需求成長。", RiskType.opportunity_or_growth)],
        [snapshot],
        [revenue],
    )

    assert "| 檢查項目 | 狀態 | 本次證據 | 對投資判斷的影響 |" in section
    assert "| 可追溯來源 | 可追溯 | 共 2 筆文本 |" in section
    assert "| 來源多樣性 | 偏少 | 2 個發布者 |" in section
    assert "### 個股可信度核對" in section
    assert "| 2330 台積電 | 中 | 2 筆 / 2 來源 | 1 筆 | 2026-05-21 |" in section
    assert "缺已揭露年度財報" in section
    assert "### 可信度判讀規則" in section


def test_evidence_ranking_expands_topic_with_company_aliases() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    generator.risk_analyzer = None
    request = ReportRequest(topic="AI 產業鏈", tickers=["2382"])
    related = NewsFetcher.from_manual_text(
        title="廣達 AI 伺服器出貨成長",
        text="廣達電腦 AI 伺服器出貨成長，法人看好後續需求。",
        publisher="測試新聞",
        published_at=date(2026, 5, 24),
    )
    unrelated = NewsFetcher.from_manual_text(
        title="大盤震盪整理",
        text="市場觀望氣氛濃厚。",
        publisher="測試新聞",
        published_at=date(2026, 5, 24),
    )

    documents = generator._rank_evidence_documents(request, [unrelated, related])

    assert documents == [related]


def test_evidence_ranking_uses_dynamic_evidence_keywords_without_entity_match() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "6669",
                "name": "緯穎",
                "segment": "AI 伺服器",
                "rationale": "",
                "evidence_keywords": ["資料中心"],
                "evidence_count": 1,
                "evidence_titles": [],
                "status": "evidence_supported",
            }
        ]
    )
    generator = object.__new__(ReportGenerator)
    generator.whitelist = whitelist
    generator.mapper = EntityMapper(whitelist)
    request = ReportRequest(topic="AI 產業鏈", tickers=["6669"])
    keyword_only = NewsFetcher.from_manual_text(
        title="資料中心需求成長",
        text="資料中心需求帶動 AI 基礎建設。",
        publisher="測試新聞",
        published_at=date(2026, 5, 24),
    )

    documents = generator._rank_evidence_documents(request, [keyword_only])

    assert documents == [keyword_only]
    assert generator._related_documents("6669", documents) == []


def test_candidate_audit_report_keeps_excluded_company_reasons() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "2382",
                "name": "廣達",
                "segment": "系統組裝",
                "rationale": "",
                "evidence_keywords": ["AI 伺服器"],
                "evidence_count": 2,
                "evidence_source_count": 2,
                "evidence_titles": [],
                "evidence_sources": [
                    {
                        "title": "廣達 AI 伺服器訂單",
                        "publisher": "測試新聞",
                        "published_at": "2026-05-24",
                        "url": "https://example.com/quanta",
                    }
                ],
                "evidence_confidence_score": 92,
                "evidence_confidence_label": "高",
                "latest_evidence_date": "2026-05-24",
                "status": "evidence_supported",
                "validation_reason": "通過正式分析門檻：至少 2 篇公司主題證據。",
                "next_action": "納入正式分析。",
            },
            {
                "ticker": "3324",
                "name": "雙鴻",
                "segment": "散熱模組",
                "rationale": "",
                "evidence_keywords": ["液冷"],
                "evidence_count": 1,
                "evidence_source_count": 1,
                "evidence_titles": [],
                "status": "weak_evidence",
                "validation_reason": "弱證據：目前只有 1 篇、1 個來源。",
                "next_action": "補抓公司新聞、法說會、月營收與國際供應鏈資料後再驗證。",
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)

    markdown = generator._render_candidate_audit(["2382"])

    assert "| AI 初始候選 | 2 |" in markdown
    assert "| 正式分析 | 1 |" in markdown
    assert "3324 雙鴻" in markdown
    assert "弱證據觀察" in markdown
    assert "補抓公司新聞" in markdown
    assert "候選公司代表來源" in markdown
    assert "廣達 AI 伺服器訂單" in markdown
    assert "測試新聞" in markdown
    assert "高 92，最新 2026-05-24" in markdown


def test_candidate_audit_fallback_uses_low_confidence_reason() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "3324",
                "name": "雙鴻",
                "segment": "散熱模組",
                "rationale": "",
                "evidence_keywords": ["液冷"],
                "evidence_count": 2,
                "evidence_source_count": 2,
                "evidence_titles": [],
                "evidence_confidence_score": 60,
                "evidence_confidence_label": "中",
                "status": "weak_evidence",
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)

    markdown = generator._render_candidate_audit([])

    assert "弱證據：篇數與來源數達標，但證據信心只有 60 分" in markdown
    assert "補抓有日期、近期且不同發布者" in markdown
    assert "中 60" in markdown


def test_candidate_audit_dedupes_repeated_revalidation_reason() -> None:
    repeated_reason = (
        "上一版通過正式分析門檻；"
        "本次補強重驗證未穩定重建既有正式證據，先保留上一版正式分析；"
        "本次補強重驗證未穩定重建既有正式證據，先保留上一版正式分析"
    )
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "3037",
                "name": "欣興",
                "segment": "PCB",
                "rationale": "",
                "evidence_keywords": ["AI 伺服器"],
                "evidence_count": 13,
                "evidence_source_count": 9,
                "evidence_titles": [],
                "status": "evidence_supported",
                "validation_reason": repeated_reason,
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)

    markdown = generator._render_candidate_audit(["3037"])

    assert markdown.count("本次補強重驗證未穩定重建既有正式證據") == 1


def test_candidate_audit_filters_unrelated_release_note_sources() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "5443",
                "name": "均豪",
                "segment": "半導體自動化",
                "rationale": "機械手臂與自動化設備",
                "evidence_keywords": ["自動化", "機械手臂"],
                "evidence_count": 1,
                "evidence_source_count": 1,
                "evidence_titles": ["May 21, 2026"],
                "evidence_sources": [
                    {
                        "title": "May 21, 2026",
                        "publisher": "Google Cloud Release Notes",
                        "published_at": "2026-05-21",
                        "url": "https://cloud.google.com/release-notes",
                    }
                ],
                "status": "weak_evidence",
                "validation_reason": "弱證據：目前只有 1 篇、1 個來源。",
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)

    markdown = generator._render_candidate_audit([])

    assert "Google Cloud Release Notes" not in markdown
    assert "| 5443 均豪 | 半導體自動化 | 弱證據觀察 | 0 篇 / 0 來源 |" in markdown


def test_partial_quality_upside_stays_on_watchlist_without_allocation() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(
        topic="AI 產業鏈",
        tickers=["2330"],
        investor_capital=1_000_000,
        beginner_mode=True,
    )
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        close=2255.0,
        source="FinMind TaiwanStockPrice",
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 需求成長",
            text="台積電 CoWoS 需求成長。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 先進封裝擴產受惠",
            text="台積電 先進封裝擴產受惠 AI 大單。",
            publisher="測試新聞",
            published_at=date(2026, 5, 21),
        ),
    ]

    recommendations = generator._render_investment_recommendations(
        request,
        ["2330"],
        documents,
        [],
        [snapshot],
    )
    plan = generator._render_beginner_portfolio_plan(
        request,
        ["2330"],
        documents,
        [],
        [snapshot],
    )

    assert "觀察 / 資料待補" in recommendations
    assert "缺月營收" in recommendations
    assert "可列小額分批研究" not in plan
    assert "目前無可配置標的" in plan


def test_insufficient_data_finding_blocks_actionable_recommendation() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"], beginner_mode=False)
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=2255.0)
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=349567000000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=18.5,
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 需求成長",
            text="台積電 CoWoS 需求成長。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 先進封裝擴產受惠",
            text="台積電 先進封裝擴產受惠 AI 大單。",
            publisher="測試新聞",
            published_at=date(2026, 5, 21),
        ),
    ]

    recommendations = generator._render_investment_recommendations(
        request,
        ["2330"],
        documents,
        [
            make_finding(
                "2330",
                "台積電",
                "資料不足，需補官方來源。",
                RiskType.insufficient_data,
            )
        ],
        [snapshot],
        [revenue],
    )

    assert "| 2330 台積電 | 2026-05-22 收盤 2255 | 觀察等待 | 觀察 / 資料待補 |" in recommendations
    assert "模型或來源判定資料仍不足" in recommendations
    assert "不適用 / 0 元" in recommendations
    assert "可小額分批研究" not in recommendations


def test_final_screen_does_not_promote_weak_evidence_revenue_only_score() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        close=2255.0,
        source="FinMind TaiwanStockPrice",
    )
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=349567000000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=18.5,
    )

    screen = generator._render_final_potential_screen(["2330"], [], [], [snapshot], [revenue])

    assert "目前證據的情境升值分約" in screen
    assert "資料品質不足" in screen
    assert "情境升值潛力約" not in screen


def test_beginner_plan_keeps_downside_over_five_on_watchlist() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(
        topic="AI 產業鏈",
        tickers=["2382"],
        investor_capital=1_000_000,
        beginner_mode=True,
        max_position_pct=0.10,
        cash_reserve_pct=0.30,
    )
    snapshot = MarketSnapshot(
        ticker="2382",
        trade_date=date(2026, 5, 22),
        close=316.0,
        source="FinMind TaiwanStockPrice",
    )
    revenue = MonthlyRevenue(
        ticker="2382",
        revenue_date=date(2026, 5, 1),
        revenue=339921315000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=120.71,
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="廣達 AI 伺服器需求成長",
            text="廣達 AI 伺服器需求成長。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="廣達 AI 伺服器出貨受惠大單但有毛利風險",
            text="廣達 AI 伺服器受惠大單，但法人提醒毛利風險。",
            publisher="測試新聞",
            published_at=date(2026, 5, 21),
        ),
    ]

    plan = generator._render_beginner_portfolio_plan(
        request,
        ["2382"],
        documents,
        [make_finding("2382", "廣達", "廣達 AI 伺服器出貨受惠大單但有毛利風險。")],
        [snapshot],
        [revenue],
    )

    assert "可列小額分批研究" not in plan
    assert "觀察 / 等風險降低" in plan
    assert "超過 5 分，依新手保守設定先列觀察" in plan


def test_recommendations_keep_beginner_downside_over_five_on_watchlist() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(topic="AI 產業鏈", tickers=["2382"], beginner_mode=True)
    snapshot = MarketSnapshot(
        ticker="2382",
        trade_date=date(2026, 5, 22),
        close=316.0,
        source="FinMind TaiwanStockPrice",
    )
    revenue = MonthlyRevenue(
        ticker="2382",
        revenue_date=date(2026, 5, 1),
        revenue=339921315000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=120.71,
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="廣達 AI 伺服器需求成長",
            text="廣達 AI 伺服器需求成長。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="廣達 AI 伺服器受惠大單但有毛利風險",
            text="廣達 AI 伺服器受惠大單但有毛利風險。",
            publisher="測試新聞",
            published_at=date(2026, 5, 21),
        ),
    ]

    recommendations = generator._render_investment_recommendations(
        request,
        ["2382"],
        documents,
        [make_finding("2382", "廣達", "廣達 AI 伺服器受惠大單但有毛利風險。")],
        [snapshot],
        [revenue],
    )

    assert "觀察 / 等風險降低" in recommendations
    assert "可小額分批研究" not in recommendations
    assert "| 2382 廣達 | 2026-05-22 收盤 316 | 等風險下降 | 觀察 / 等風險降低 |" in recommendations
    assert "不適用 / 0 元" in recommendations


def test_balanced_profile_allows_variable_capital_and_wider_downside_gate() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(
        topic="AI 產業鏈",
        tickers=["2382"],
        investor_capital=3_000_000,
        beginner_mode=False,
        investor_profile=InvestorProfile.balanced,
        max_position_pct=0.10,
        cash_reserve_pct=0.30,
    )
    snapshot = MarketSnapshot(
        ticker="2382",
        trade_date=date(2026, 5, 22),
        close=316.0,
        source="FinMind TaiwanStockPrice",
    )
    revenue = MonthlyRevenue(
        ticker="2382",
        revenue_date=date(2026, 5, 1),
        revenue=339921315000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=120.71,
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="廣達 AI 伺服器需求成長",
            text="廣達 AI 伺服器需求成長。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="廣達 AI 伺服器出貨受惠大單但有風險",
            text="廣達 AI 伺服器受惠大單，但法人提醒風險。",
            publisher="測試新聞",
            published_at=date(2026, 5, 21),
        ),
    ]

    plan = generator._render_beginner_portfolio_plan(
        request,
        ["2382"],
        documents,
        [
            make_finding(
                "2382",
                "廣達",
                "廣達 AI 伺服器受惠大單，但法人提醒風險。",
                RiskType.opportunity_or_growth,
            )
        ],
        [snapshot],
        [revenue],
    )

    assert "總資金 3,000,000 元以內" in plan
    assert "一般穩健" in plan
    assert "目前情境降值觀察門檻 8 分" in plan
    assert "可列小額分批研究" in plan
    assert "首筆配置草案" in plan
    assert "本輪首筆配置合計約" in plan
    assert plan.count("### 可小額分批研究") == 1


def test_portfolio_plan_does_not_allocate_observation_decision() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(
        topic="AI 產業鏈",
        tickers=["2382"],
        investor_capital=1_000_000,
        beginner_mode=False,
        investor_profile=InvestorProfile.aggressive,
    )
    snapshot = MarketSnapshot(
        ticker="2382",
        trade_date=date(2026, 5, 22),
        close=316.0,
        source="FinMind TaiwanStockPrice",
    )
    revenue = MonthlyRevenue(
        ticker="2382",
        revenue_date=date(2026, 5, 1),
        revenue=339921315000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=120.71,
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="廣達 AI 伺服器需求成長",
            text="廣達 AI 伺服器需求成長。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="廣達 AI 伺服器出貨短期波動",
            text="廣達 AI 伺服器受惠大單，但短期出貨波動仍待觀察。",
            publisher="測試新聞",
            published_at=date(2026, 5, 21),
        ),
    ]
    findings = [make_finding("2382", "廣達", "廣達 AI 伺服器出貨短期波動。")]

    plan = generator._render_beginner_portfolio_plan(
        request,
        ["2382"],
        documents,
        findings,
        [snapshot],
        [revenue],
    )
    snapshot_text = generator._render_executive_snapshot(
        request,
        ["2382"],
        documents,
        findings,
        [snapshot],
        [revenue],
    )

    assert "| 可小額研究 | 0 檔 |" in snapshot_text
    assert "目前無可配置標的" in plan
    assert "首筆配置約" not in plan
    assert "可列小額分批研究" not in plan
    assert "2382 廣達：觀察。原因：主要證據偏短期波動" in plan


def test_beginner_portfolio_plan_caps_position_size() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(
        topic="AI 產業鏈",
        tickers=["2330"],
        investor_capital=1_000_000,
        beginner_mode=True,
        max_position_pct=0.10,
        cash_reserve_pct=0.30,
    )
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        close=2255.0,
        source="FinMind TaiwanStockPrice",
    )
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=349567000000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=18.5,
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 需求成長",
            text="台積電 CoWoS 需求成長。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 先進封裝擴產受惠",
            text="台積電 先進封裝擴產受惠 AI 大單。",
            publisher="測試新聞",
            published_at=date(2026, 5, 21),
        ),
    ]

    plan = generator._render_beginner_portfolio_plan(
        request,
        ["2330"],
        documents,
        [
            make_finding(
                "2330",
                "台積電",
                "台積電 先進封裝擴產受惠 AI 大單。",
                RiskType.opportunity_or_growth,
            )
        ],
        [snapshot],
        [revenue],
    )

    assert "總資金 1,000,000 元以內" in plan
    assert "單檔上限約 100,000 元" in plan
    assert "首筆約 30,000 元" in plan


def test_allocation_plan_caps_each_first_tranche_and_total_budget() -> None:
    rows = ReportGenerator._render_allocation_plan(
        [
            {"label": "2382 廣達", "upside_pct": 19, "downside_pct": 0},
            {"label": "3324 雙鴻", "upside_pct": 16, "downside_pct": 0},
        ],
        deployable=50_000,
        first_tranche=100_000,
    )

    assert rows[0] == "本輪首筆配置合計約 50,000 元；可投入上限 50,000 元。"
    assert "2382 廣達：首筆配置約 30,000 元" in rows[1]
    assert "3324 雙鴻：首筆配置約 20,000 元" in rows[2]


def test_risk_warning_reason_distinguishes_threshold_from_relative_risk() -> None:
    assert ReportGenerator._risk_warning_reason({"upside_pct": 16, "downside_pct": 13}) == (
        "財務或估值紅旗偏重，需先等基本面修復或補充來源驗證。"
    )
    assert ReportGenerator._risk_warning_reason({"upside_pct": 8, "downside_pct": 13}) == (
        "目前情境降值分高於升值分，風險權重已壓過投資理由，不適合追價。"
    )


def test_aggressive_profile_observes_high_upside_when_downside_exceeds_gate_only() -> None:
    estimate = {"upside_pct": 45, "downside_pct": 16}
    quality = {"grade": "supported", "missing": []}

    rating = ReportGenerator._decision_label(estimate, quality, [], 12)

    assert rating == "觀察 / 等風險降低"


def test_leading_signal_analyzer_scores_price_revenue_and_valuation() -> None:
    prices = [
        MarketSnapshot(
            ticker="2330",
            trade_date=date(2026, 1, day),
            close=100 + day,
            trading_volume=1_000,
        )
        for day in range(1, 31)
    ]
    prices[-1] = prices[-1].model_copy(update={"close": 140, "trading_volume": 2_000})
    revenues = [
        MonthlyRevenue(
            ticker="2330",
            revenue_date=date(2026, month, 10),
            revenue=1000 + month,
            revenue_year=2026,
            revenue_month=month,
            yoy_pct=10 + month,
        )
        for month in range(1, 5)
    ]
    valuation = ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=12, pb_ratio=2)

    signal = LeadingSignalAnalyzer().analyze(
        "2330",
        prices,
        revenues,
        valuation,
        {"pe_avg": 20, "pb_avg": 3},
    )

    assert signal.direction == "偏多"
    assert signal.upside_bonus > 0
    assert signal.downside_penalty == 0
    assert "目前估值低於同業" in signal.bullish_factors


def test_negative_profitability_removes_low_valuation_from_leading_signal() -> None:
    signal = LeadingSignal(
        ticker="4540",
        score=6,
        upside_bonus=6,
        downside_penalty=0,
        bullish_factors=["月營收年增 33.4%", "目前估值低於同業"],
        valuation_label="目前估值低於同業",
    )

    sanitized = ReportGenerator._sanitize_leading_signal_for_profitability(signal, True)

    assert sanitized.upside_bonus == 4
    assert sanitized.valuation_label == "獲利為負，不判低估"
    assert "目前估值低於同業" not in sanitized.summary


def test_estimate_potential_uses_leading_signal_bonus() -> None:
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        close=2255.0,
        source="FinMind TaiwanStockPrice",
    )
    signal = LeadingSignalAnalyzer().analyze(
        "2330",
        [
            MarketSnapshot(ticker="2330", trade_date=date(2026, 1, day), close=100 + day, trading_volume=1000)
            for day in range(1, 31)
        ],
        [],
    )

    estimate = ReportGenerator._estimate_potential([], [], snapshot, None, signal)

    assert estimate["upside_pct"] > 10
    assert any("近況訊號偏多" in label for label, _score in estimate["upside_factors"])


def test_bearish_leading_signal_blocks_actionable_rating() -> None:
    signal = LeadingSignal(
        ticker="2330",
        score=-6,
        upside_bonus=0,
        downside_penalty=6,
        bearish_factors=["20 日股價轉弱 -12.0%"],
    )
    estimate = {"upside_pct": 18, "downside_pct": 4}
    quality = {"grade": "supported", "missing": []}

    rating = ReportGenerator._decision_label(estimate, quality, [], 5, signal)
    reason = ReportGenerator._decision_reason(
        rating,
        estimate,
        quality,
        [],
        [],
        5,
        ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
        signal,
    )

    assert rating == "觀察 / 等風險降低"
    assert "近況訊號偏空" in reason


def test_structural_bottleneck_reason_names_specific_evidence() -> None:
    finding = make_finding(
        "2395",
        "研華",
        "產能吃緊造成交期延長",
        RiskType.structural_bottleneck,
    )
    estimate = {"upside_pct": 18, "downside_pct": 4}
    quality = {"grade": "supported", "missing": []}

    rating = ReportGenerator._decision_label(estimate, quality, [finding], 12)
    reason = ReportGenerator._decision_reason(
        rating,
        estimate,
        quality,
        [finding],
        [],
        12,
        ReportRequest(topic="機器人 產業鏈", tickers=["2395"]),
    )

    assert rating == "觀察 / 等風險降低"
    assert "瓶頸/限制證據：產能吃緊造成交期延長" in reason
    assert "存在結構性瓶頸證據" not in reason


def test_investment_recommendations_escape_source_title_pipes() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    title = "台積電法說超標演出| 個人理財| 理財"
    document = NewsDocument(
        id="pipe-title",
        title=title,
        text="台積電 2330 AI 伺服器 先進製程 需求 成長",
        source=Source(title=title, publisher="經濟日報", published_at=date(2026, 3, 2)),
    )
    finding = make_finding(
        "2330",
        "台積電",
        "產能吃緊造成交期延長",
        RiskType.structural_bottleneck,
    )
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 29), close=1200.0)

    recommendations = generator._render_investment_recommendations(
        ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
        ["2330"],
        [document],
        [finding],
        [snapshot],
    )
    row = next(line for line in recommendations.splitlines() if line.startswith("| 2330 "))

    assert "台積電法說超標演出\\| 個人理財\\| 理財" in row
    assert unescaped_pipe_count(row) == 8


def test_recheck_trigger_text_uses_signal_risk_and_missing_data() -> None:
    signal = LeadingSignal(
        ticker="2330",
        score=-6,
        upside_bonus=0,
        downside_penalty=6,
        bearish_factors=["20 日股價轉弱 -12.0%"],
    )

    trigger = ReportGenerator._recheck_trigger_text(
        {
            "estimate": {"upside_pct": 18, "downside_pct": 9},
            "quality": {"missing": ["缺估值"]},
            "leading_signal": signal,
        }
    )

    assert "補齊缺估值" in trigger
    assert "近況訊號由偏空轉為中性以上" in trigger
    assert "目前情境降值分降至 5 分以下" in trigger

    aggressive_trigger = ReportGenerator._recheck_trigger_text(
        {
            "estimate": {"upside_pct": 18, "downside_pct": 14},
            "quality": {"missing": []},
            "leading_signal": signal,
        },
        downside_gate=12,
    )
    assert "目前情境降值分降至 12 分以下" in aggressive_trigger

    aggressive_avoid = ReportGenerator._avoid_trigger_text(
        {"estimate": {"upside_pct": 18, "downside_pct": 9}},
        downside_gate=12,
    )
    assert "目前情境降值分仍高於 5 分" not in aggressive_avoid


def test_monitoring_checklist_renders_recheck_and_avoid_rules() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"])
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=100)
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=100,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=20,
    )
    signal = LeadingSignal(
        ticker="2330",
        score=-6,
        upside_bonus=0,
        downside_penalty=6,
        bearish_factors=["20 日股價轉弱 -12.0%"],
    )

    markdown = generator._render_monitoring_checklist(
        request,
        ["2330"],
        [
            NewsFetcher.from_manual_text(
                title="台積電 AI 需求成長",
                text="台積電 AI 需求成長。",
                publisher="測試新聞",
                published_at=date(2026, 5, 20),
            ),
            NewsFetcher.from_manual_text(
                title="台積電 CoWoS 大單",
                text="台積電 CoWoS 大單。",
                publisher="測試新聞",
                published_at=date(2026, 5, 21),
            ),
        ],
        [make_finding("2330", "台積電", "台積電 AI 需求成長", RiskType.opportunity_or_growth)],
        [snapshot],
        [revenue],
        [
            FinancialMetric(
                ticker="2330",
                report_date=date(2026, 3, 31),
                statement_type="income_statement",
                metric="營收",
                value=1,
                source="test",
            )
        ],
        [ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=20, pb_ratio=3)],
        {"2330": signal},
    )

    assert "| 股票 | 目前動作 | 重新研究條件 |" in markdown
    assert "近況訊號由偏空轉為中性以上" in markdown
    assert "近況訊號維持偏空" in markdown
    assert "每週" in markdown


def test_render_leading_signal_check_outputs_table() -> None:
    signal = LeadingSignalAnalyzer().analyze(
        "2330",
        [
            MarketSnapshot(ticker="2330", trade_date=date(2026, 1, day), close=100 + day, trading_volume=1000)
            for day in range(1, 31)
        ],
        [],
    )

    markdown = ReportGenerator._render_leading_signal_check(["2330"], {"2330": signal})

    assert "領先訊號檢查" not in markdown
    assert "| 股票 | 近況方向 | 分數 |" in markdown
    assert "2330" in markdown
