from datetime import date

from app.data_sources.news import NewsFetcher
from app.models.schemas import (
    EntityMatch,
    FinancialMetric,
    InvestorProfile,
    MarketSnapshot,
    MonthlyRevenue,
    ReportRequest,
    RiskFinding,
    RiskType,
    Source,
    ValuationMetric,
)
from app.services.entity_mapping import EntityMapper
from app.services.leading_signals import LeadingSignal, LeadingSignalAnalyzer
from app.services.llm_analysis import LLMSupplementValidator
from app.services.report_generator import ReportGenerator
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
    assert "| 股票 | 產業位置 | 股價 | 月營收 | 估值位置 | 財務信心 | 證據狀態 |" in company_analysis
    assert "| 2330 台積電 |" in company_analysis
    assert "#### 華爾街式完整分析框架" in company_analysis
    assert "商業模式與收入來源" in company_analysis
    assert "#### 過去 5 年財務檢查" in company_analysis
    assert "#### 競爭護城河" in company_analysis
    assert "#### 估值分析" in company_analysis
    assert "#### 未來成長潛力" in company_analysis
    assert "#### 多空辯論" in company_analysis
    assert "#### 是否應該投資" in company_analysis
    assert "淨利趨勢：目前無足夠數據判斷" in company_analysis
    assert "P/E 與同業比較：目前無足夠數據判斷" in company_analysis
    assert "新聞/RAG 證據：目前無足夠數據判斷" in company_analysis
    assert "觀察 / 資料不足" in recommendations
    assert "缺少新聞、財報或法說證據" in recommendations


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

    assert "2022 至 2026 營收成長 50.00%" in company_analysis
    assert "2026 負債權益比約 0.40 倍" in company_analysis
    assert "資料信心：低；估值位置：估值偏高。" in company_analysis
    assert "| 2330 台積電 | 晶圓代工 | 2026-05-22 收盤 2255.0 | 缺 | 估值偏高 | 低 |" in company_analysis
    assert "P/E 24.50、P/B 5.80、殖利率 1.60%" in company_analysis
    assert "P/E 高於同業平均 18.50" in company_analysis
    assert "P/B 高於同業平均 4.30" in company_analysis


def test_company_comparison_matrix_summarizes_decision_valuation_and_confidence() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
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
    assert "| 股票 | 判斷 | 升值 | 降值 | 估值位置 | 財務信心 | 核心提醒 |" in matrix
    assert "| 2330 台積電 | 可小額分批研究 |" in matrix
    assert "估值偏高" in matrix
    assert "高" in matrix


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

    assert "2026 負債權益比約 0.46 倍" in summary["debt_trend"]
    assert "2026 ROE 約 9.66%" in summary["roe_trend"]
    assert "687799687000.00%" not in summary["roe_trend"]


def test_valuation_position_and_financial_confidence_labels() -> None:
    peer = {"pe_avg": 20.0, "pb_avg": 5.0, "count": 3}

    assert ReportGenerator._valuation_position_label(
        ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=30, pb_ratio=8),
        peer,
    ) == "估值偏高"
    assert ReportGenerator._valuation_position_label(
        ValuationMetric(ticker="2382", trade_date=date(2026, 5, 22), pe_ratio=12, pb_ratio=3),
        peer,
    ) == "估值低於同業"
    assert ReportGenerator._financial_confidence_label(
        [FinancialMetric(ticker="2330", report_date=date(2026, 3, 31), statement_type="income_statement", metric="營業收入", value=1, source="test") for _ in range(40)],
        ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=20, pb_ratio=5),
        MonthlyRevenue(ticker="2330", revenue_date=date(2026, 4, 1), revenue=1, revenue_year=2026, revenue_month=4),
    ) == "高"


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
        [make_finding("2330", "台積電", "台積電 先進封裝擴產受惠 AI 大單。", RiskType.insufficient_data)],
        [snapshot],
        [revenue],
    )

    assert "**重點提醒：本次有 1 檔可小額研究" in snapshot_text
    assert "| 股票 | 判斷 | 資料等級 | 升值情境 | 降值風險 | 領先訊號 | 主要缺口 |" in snapshot_text
    assert "| 2330 台積電 | 可小額分批研究 | 完整 |" in snapshot_text
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
        [make_finding("2330", "台積電", "台積電 先進封裝擴產受惠 AI 大單。", RiskType.insufficient_data)],
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

    assert "升值潛力約" in screen
    assert "降值風險約" in screen
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

    assert "| 股票 | 升值 | 降值 | 主要加分 | 主要風險 | 資料提醒 |" in breakdown
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
    assert "領先訊號" in section
    assert "完整，可進入二次篩選" in section
    assert "2382 廣達" in section
    assert "不足：公司文本不足、缺 AI 歸因、缺股價、缺月營收" in section
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
    assert "### 個股來源覆蓋" in section
    assert "| 2382 廣達 | 2 | 1 | 2026-05-24 |" in section


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
    assert "缺 AI 歸因、缺月營收" in recommendations
    assert "可列小額分批研究" not in plan
    assert "目前無可配置標的" in plan


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

    assert "升值分數約" in screen
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
    assert "超過 5% 新手保守門檻" in plan


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
        [make_finding("2382", "廣達", "廣達 AI 伺服器受惠大單，但法人提醒風險。")],
        [snapshot],
        [revenue],
    )

    assert "總資金 3,000,000 元以內" in plan
    assert "一般穩健" in plan
    assert "降值觀察門檻 8%" in plan
    assert "可列小額分批研究" in plan
    assert "首筆配置草案" in plan
    assert "本輪首筆配置合計約" in plan
    assert plan.count("### 可小額分批研究") == 1


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
                RiskType.insufficient_data,
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
        "降值風險超過新手警戒門檻 12%，即使有上行情境也不適合追價。"
    )
    assert ReportGenerator._risk_warning_reason({"upside_pct": 8, "downside_pct": 13}) == (
        "降值風險高於升值潛力，對新手資金不適合追價。"
    )


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
    assert "估值低於同業" in signal.bullish_factors


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
    assert any("領先訊號偏多" in label for label, _score in estimate["upside_factors"])


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
    assert "領先訊號偏空" in reason


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
    assert "領先訊號由偏空轉為中性以上" in trigger
    assert "降值風險降至 5% 以下" in trigger


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
    assert "領先訊號由偏空轉為中性以上" in markdown
    assert "領先訊號維持偏空" in markdown
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
    assert "| 股票 | 方向 | 分數 |" in markdown
    assert "2330" in markdown
