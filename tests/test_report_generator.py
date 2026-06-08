from datetime import date
from pathlib import Path
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
from app.services.leading_signals import LeadingSignal
from app.services import (
    report_company_analysis,
    report_company_filing_checks,
    report_company_narrative,
    report_company_matrix,
    report_decision_contexts,
    report_early_potential,
)
from app.services.report_generator import (
    REPORT_READING_SORT_NOTE,
    ReportGenerator,
)
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
    direct_company_analysis = report_company_analysis.render_company_analysis_section(
        generator,
        ["2330"],
        [],
        [],
        [snapshot],
        reading_sort_note=REPORT_READING_SORT_NOTE,
    )
    recommendations = generator._render_investment_recommendations(
        ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
        ["2330"],
        [],
        [],
        [snapshot],
    )

    assert company_analysis == direct_company_analysis
    assert "### 2330 台積電" in company_analysis
    assert "### 個股速覽" in company_analysis
    assert "| 股票 | 產業位置 | 最新可取得收盤價 | 追價風險標籤 | 月營收 | 目前估值位置 | 財務信心 | 證據狀態 |" in company_analysis
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


def test_company_analysis_overview_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    analysis_source = Path("app/services/report_company_analysis.py").read_text()

    assert "report_company_analysis" in generator_source
    assert "def overview_row(" in analysis_source
    assert "def render_company_analysis_section(" in analysis_source
    assert "def render_company_analysis(" in analysis_source
    assert "### 個股速覽" not in generator_source
    assert "未指定白名單個股" not in generator_source
    assert "市場資料：" not in generator_source
    assert "月營收：" not in generator_source
    assert "風險/機會證據" not in generator_source
    assert report_company_analysis.render_company_analysis([], [], "排序說明") == (
        "### 個股速覽\n"
        "排序說明\n\n"
        "| 股票 | 產業位置 | 最新可取得收盤價 | 追價風險標籤 | 月營收 | 目前估值位置 | 財務信心 | 證據狀態 |\n"
        "|---|---|---|---|---|---|---|---|\n\n"
        "### 個股細節"
    )


def test_company_analysis_detail_block_helpers_format_market_revenue_and_evidence() -> None:
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        close=1000.0,
        spread=25.0,
        trading_volume=12345,
        source="FinMind TaiwanStockPrice",
    )
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 30),
        revenue=410_725_118_000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=25.0,
        source="FinMind TaiwanStockMonthRevenue",
    )
    document = NewsFetcher.from_manual_text(
        title="台積電 AI 需求成長",
        text="台積電 AI 需求成長。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )
    findings = [
        make_finding("2330", "台積電", f"測試風險證據 {index}", RiskType.structural_bottleneck)
        for index in range(4)
    ]

    market_line = report_company_analysis.market_data_line(snapshot)
    revenue_line = report_company_analysis.monthly_revenue_line(revenue)
    finding_lines = report_company_analysis.evidence_lines([document], findings)

    assert "2026-05-22 收盤 1000.0" in market_line
    assert "成交量 12345" in market_line
    assert report_company_analysis.market_data_line(None) == "- 市場資料：目前無足夠數據判斷。"
    assert "2026-04 營收 410,725,118,000" in revenue_line
    assert "年增率 25.00%" in revenue_line
    assert report_company_analysis.monthly_revenue_line(None) == "- 月營收：目前無足夠數據判斷。"
    assert finding_lines[0].startswith("- 風險/機會證據：structural_bottleneck；測試風險證據 0")
    assert finding_lines[-1] == "- 其餘 1 筆證據已收斂於風險摘要與資料來源附錄。"
    assert report_company_analysis.evidence_lines([document], []) == [
        "- 新聞/研究證據：找到 1 筆相關文本，但未形成可歸因風險。"
    ]
    assert report_company_analysis.evidence_lines([], []) == ["- 新聞/研究證據：目前無足夠數據判斷。"]


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
    generator_source = Path("app/services/report_generator.py").read_text()
    analysis_source = Path("app/services/report_company_analysis.py").read_text()
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
    assert "def basic_intro(" in analysis_source
    assert "本主題關聯關鍵字" not in generator_source


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
    assert "| 股票 | 判斷 | 最新可取得收盤價 | 追價風險標籤 | 目前情境升值分 | 目前情境降值分 | 目前估值位置 | 財務信心 | 核心提醒 |" in matrix
    assert "| 2330 台積電 | 觀察 / 等風險降低 |" in matrix
    assert "等風險下降" in matrix
    assert "估值偏高" in matrix
    assert "高" in matrix


def test_company_comparison_matrix_logic_lives_outside_generator() -> None:
    generator = object.__new__(ReportGenerator)
    request = ReportRequest(tickers=[])
    generator_source = Path("app/services/report_generator.py").read_text()
    decision_views_mixin_source = Path("app/services/report_generator_decision_views.py").read_text()
    matrix_source = Path("app/services/report_company_matrix.py").read_text()

    assert "report_company_matrix" not in generator_source
    assert "ReportGeneratorDecisionViewsMixin" in generator_source
    assert "report_company_matrix" in decision_views_mixin_source
    assert "def _render_company_comparison_matrix(" in decision_views_mixin_source
    assert "def _company_matrix_reminder(" in decision_views_mixin_source
    assert "def _render_company_comparison_matrix(" not in generator_source
    assert "def render_company_comparison_matrix(" in matrix_source
    assert "def company_matrix_reminder(" in matrix_source
    assert "這張表用來比較正式分析股票" not in generator_source
    assert generator._render_company_comparison_matrix(request, [], [], [], []) == (
        report_company_matrix.render_company_comparison_matrix([], {}, {}, "")
    )


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


def test_early_potential_radar_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    early_source = Path("app/services/report_early_potential.py").read_text()
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    document = NewsFetcher.from_manual_text(
        title="台積電 AI 需求",
        text="台積電 AI 需求。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    assert "report_early_potential" in generator_source
    assert "def render_early_potential_radar(" in early_source
    assert "def candidate_audit_evidence_counts(" in early_source
    assert "def publisher_count(" in early_source
    assert "本段專門找" not in generator_source
    assert generator._publisher_count([document]) == report_early_potential.publisher_count([document])
    assert generator._candidate_audit_evidence_counts() == report_early_potential.candidate_audit_evidence_counts(
        generator.whitelist.candidate_audit()
    )


def test_company_narrative_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    company_mixin_source = Path("app/services/report_generator_company.py").read_text()
    narrative_source = Path("app/services/report_company_narrative.py").read_text()

    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 1),
        revenue=349567000000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=18.5,
    )
    valuation = ValuationMetric(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        pe_ratio=20,
        pb_ratio=5,
        dividend_yield=1.5,
    )

    assert "ReportGeneratorCompanyNarrativeMixin" in generator_source
    assert "report_company_narrative" not in generator_source
    assert "from app.services import report_company_narrative" in company_mixin_source
    assert "def _company_revenue_summary(" in company_mixin_source
    assert "def _dcf_proxy_text(" in company_mixin_source
    assert "def _moat_factor_text(" in company_mixin_source
    assert "def company_quick_take(" in narrative_source
    assert "def valuation_summary(" in narrative_source
    assert "def financial_confidence_label(" in narrative_source
    assert "def moat_factor_text(" in narrative_source
    assert "def dcf_proxy_text(" in narrative_source
    assert "def growth_opportunity_text(" in narrative_source
    assert "def render_wall_street_company_sections(" in narrative_source
    assert "無法判斷近期營收動能" not in generator_source
    assert "硬體與供應鏈公司通常不是典型網路效應" not in generator_source
    assert "系統暫不硬算目標價" not in generator_source
    assert "華爾街式完整分析框架" not in generator_source
    assert ReportGenerator._company_revenue_summary(revenue) == report_company_narrative.company_revenue_summary(revenue)
    assert ReportGenerator._valuation_summary(valuation, {"pe_avg": 20, "pb_avg": 5, "count": 3}) == (
        report_company_narrative.valuation_summary(valuation, {"pe_avg": 20, "pb_avg": 5, "count": 3})
    )
    assert ReportGenerator._dcf_proxy_text(
        {"fcf_trend": "自由現金流成長 12.00%。"},
        valuation,
    ) == report_company_narrative.dcf_proxy_text(
        {"fcf_trend": "自由現金流成長 12.00%。"},
        valuation,
    )


def test_company_filing_check_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    document_mixin_source = Path("app/services/report_generator_document.py").read_text()
    filing_source = Path("app/services/report_company_filing_checks.py").read_text()

    assert "ReportGeneratorDocumentMixin" in generator_source
    assert "report_company_filing_checks" not in generator_source
    assert "report_company_filing_checks" in document_mixin_source
    assert "def _company_filing_missing(" in document_mixin_source
    assert "def company_filing_missing(" in filing_source
    assert "HIGH_QUALITY_FILING_SCORE" in filing_source
    assert "REQUIRED_CORE_DOCUMENT_TYPES" not in generator_source
    assert "filing_quality_score(" not in generator_source
    assert ReportGenerator._filing_type_label("annual_report") == report_company_filing_checks.filing_type_label(
        "annual_report"
    )


def test_decision_context_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    context_source = Path("app/services/report_decision_contexts.py").read_text()

    assert "report_decision_contexts" in generator_source
    assert "def build_decision_contexts(" in context_source
    assert "def ordered_tickers_for_reading(" in context_source
    assert "snapshots = {snapshot.ticker" not in generator_source
    assert "peer_valuation_summary = generator._peer_valuation_summary" in context_source
    assert report_decision_contexts.build_decision_contexts


def test_stale_company_text_downgrades_actionable_decision() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "2059",
                "name": "川湖",
                "segment": "伺服器導軌",
                "status": "evidence_supported",
                "evidence_keywords": ["AI 伺服器"],
            }
        ]
    )
    generator.mapper = EntityMapper(generator.whitelist)
    generator._company_filing_missing = lambda ticker, documents: []
    request = ReportRequest(topic="AI 產業鏈低關注潛力股", tickers=["2059"], lookback_days=120)
    old_document = NewsFetcher.from_manual_text(
        title="川湖 AI 伺服器導軌需求成長",
        text="文件類型：annual_report\n川湖 AI 伺服器導軌需求成長。",
        publisher="公開資訊觀測站 MOPS",
        published_at=date(2025, 6, 6),
    )
    snapshot = MarketSnapshot(ticker="2059", trade_date=date(2026, 5, 29), close=5065)
    revenue = MonthlyRevenue(
        ticker="2059",
        revenue_date=date(2026, 5, 1),
        revenue=100,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=79.1,
    )
    metrics = make_financial_metrics("2059", [100, 130, 160, 200], [10, 15, 22, 32])
    valuation = ValuationMetric(ticker="2059", trade_date=date(2026, 5, 29), pe_ratio=20, pb_ratio=3)

    context = generator._decision_contexts(
        request,
        ["2059"],
        [old_document],
        [],
        [snapshot],
        [revenue],
        metrics,
        [valuation],
        {},
    )[0]

    assert "缺近 120 天公司文本" in context["quality"]["missing"]
    assert context["decision"] == "觀察 / 資料待補"


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


def test_final_screen_separates_high_upside_but_blocked_risk() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "1303",
                "name": "南亞",
                "segment": "塑化材料",
                "status": "evidence_supported",
                "evidence_keywords": ["工程塑膠"],
            }
        ]
    )
    generator.mapper = EntityMapper(generator.whitelist)
    generator._company_filing_missing = lambda ticker, documents: []
    request = ReportRequest(
        topic="機器人 產業鏈",
        tickers=["1303"],
        beginner_mode=False,
        investor_profile=InvestorProfile.aggressive,
    )
    snapshot = MarketSnapshot(ticker="1303", trade_date=date(2026, 5, 22), close=40)
    revenue = MonthlyRevenue(
        ticker="1303",
        revenue_date=date(2026, 5, 10),
        revenue=10_000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=19.4,
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="南亞 工程塑膠需求成長",
            text="南亞 工程塑膠需求成長。",
            publisher="測試新聞A",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="南亞 電子材料受惠",
            text="南亞 電子材料受惠題材。",
            publisher="測試新聞B",
            published_at=date(2026, 5, 21),
        ),
    ]
    metrics = []
    for year, sales, profit in [(2022, 100.0, 10.0), (2025, 59.7, 2.84)]:
        metrics.extend(
            [
                FinancialMetric(
                    ticker="1303",
                    report_date=date(year, 12, 31),
                    statement_type="income_statement",
                    metric="營業收入",
                    value=sales,
                    source="test",
                ),
                FinancialMetric(
                    ticker="1303",
                    report_date=date(year, 12, 31),
                    statement_type="income_statement",
                    metric="本期淨利",
                    value=profit,
                    source="test",
                ),
            ]
        )

    screen = generator._render_final_potential_screen(
        ["1303"],
        documents,
        [],
        [snapshot],
        [revenue],
        metrics,
        [ValuationMetric(ticker="1303", trade_date=date(2026, 5, 22), pb_ratio=1.2)],
        request=request,
    )

    assert "### 升值分高但風險壓過" in screen
    assert "1303 南亞：升值分約" in screen
    assert "最終判斷為「避開 / 降低曝險」" in screen
    assert "### 目前情境升值分較高" not in screen


def test_severe_financial_red_flags_cap_upside_score() -> None:
    documents = [
        NewsFetcher.from_manual_text(
            title=f"南電 ABF 載板 AI 需求受惠 {index}",
            text="南電 ABF 載板 AI 需求受惠，產能與訂單題材升溫。",
            publisher=f"測試新聞{index}",
            published_at=date(2026, 5, 20),
        )
        for index in range(6)
    ]
    snapshot = MarketSnapshot(ticker="8046", trade_date=date(2026, 5, 22), close=800)
    revenue = MonthlyRevenue(
        ticker="8046",
        revenue_date=date(2026, 5, 10),
        revenue=10_000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=39.4,
    )
    metrics = []
    for year, sales, profit in [(2021, 100.0, 30.0), (2025, 75.6, 10.1)]:
        metrics.extend(
            [
                FinancialMetric(
                    ticker="8046",
                    report_date=date(year, 12, 31),
                    statement_type="income_statement",
                    metric="營業收入",
                    value=sales,
                    source="test",
                ),
                FinancialMetric(
                    ticker="8046",
                    report_date=date(year, 12, 31),
                    statement_type="income_statement",
                    metric="本期淨利",
                    value=profit,
                    source="test",
                ),
            ]
        )

    estimate = ReportGenerator._estimate_potential(
        documents,
        [make_finding("8046", "南電", "ABF 供需吃緊", RiskType.structural_bottleneck)],
        snapshot,
        revenue,
        financial_metrics=metrics,
    )

    assert estimate["upside_pct"] <= 20
    assert "基本面紅旗" in estimate["upside_reason"]
    assert "已將升值分" in estimate["upside_cap_note"]


def test_aggressive_profile_observes_high_upside_when_downside_exceeds_gate_only() -> None:
    estimate = {"upside_pct": 45, "downside_pct": 16}
    quality = {"grade": "supported", "missing": []}

    rating = ReportGenerator._decision_label(estimate, quality, [], 12)

    assert rating == "觀察 / 等風險降低"


def test_estimate_potential_does_not_call_zero_news_hits_a_positive_reason() -> None:
    snapshot = MarketSnapshot(ticker="2059", trade_date=date(2026, 5, 22), close=100)
    revenue = MonthlyRevenue(
        ticker="2059",
        revenue_date=date(2026, 4, 10),
        revenue=100,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=79.1,
    )
    document = NewsFetcher.from_manual_text(
        title="川湖 伺服器滑軌出貨",
        text="川湖 伺服器滑軌出貨。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    estimate = ReportGenerator._estimate_potential([document], [], snapshot, revenue)

    assert estimate["upside_pct"] > 10
    assert "新聞/RAG 本身未形成主要升值加分" in estimate["upside_reason"]
    assert "正向關鍵證據 0 項" not in estimate["upside_reason"]


def test_estimate_potential_explains_valuation_risk_without_zero_news_risk() -> None:
    snapshot = MarketSnapshot(ticker="2383", trade_date=date(2026, 5, 22), close=100)
    valuation = ValuationMetric(ticker="2383", trade_date=date(2026, 5, 22), pe_ratio=60, pb_ratio=10)

    estimate = ReportGenerator._estimate_potential(
        [],
        [],
        snapshot,
        None,
        None,
        [],
        valuation,
        {"pe_avg": 20, "pb_avg": 3},
    )

    assert estimate["downside_pct"] > 5
    assert "新聞/RAG 未偵測到主要負向或瓶頸證據" in estimate["downside_reason"]
    assert "負向/瓶頸證據 0 項" not in estimate["downside_reason"]
