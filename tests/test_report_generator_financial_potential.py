from __future__ import annotations

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
    ReportRequest,
    RiskFinding,
    RiskType,
    Source,
    ValuationMetric,
)
from app.services.report_financial_assessment import (
    financial_valuation_assessment,
    valuation_position_label,
)
from app.services.report_financial_narrative import financial_statement_summary
from app.services.entity_mapping import EntityMapper
from app.services.report_generator import ReportGenerator
from app.services.report_potential import data_quality_grade, estimate_potential
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
    helper_summary = financial_statement_summary(metrics)

    assert "2026 年度負債權益比約 0.46 倍" in summary["debt_trend"]
    assert "2026 年度 ROE 約 9.66%" in summary["roe_trend"]
    assert "687799687000.00%" not in summary["roe_trend"]
    assert helper_summary == summary


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


def test_financial_narrative_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    financial_mixin_source = Path("app/services/report_generator_financial.py").read_text()
    narrative_source = Path("app/services/report_financial_narrative.py").read_text()

    assert "ReportGeneratorFinancialMixin" in generator_source
    assert "from app.services.report_financial_narrative import" in financial_mixin_source
    assert "def _financial_statement_summary(" not in generator_source
    assert "def _financial_statement_summary(" in financial_mixin_source
    assert "def financial_statement_summary(" in narrative_source
    assert "def metric_series(" in narrative_source
    assert "def balance_sheet_total_series(" in narrative_source
    assert "需補 FinMind 財報三表" not in generator_source


def test_valuation_position_and_financial_confidence_labels() -> None:
    peer = {"pe_avg": 20.0, "pb_avg": 5.0, "count": 3}

    assert ReportGenerator._valuation_position_label(
        ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=30, pb_ratio=8),
        peer,
    ) == "目前估值偏高"
    assert valuation_position_label(
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
        [
            FinancialMetric(
                ticker="2330",
                report_date=date(2026, 3, 31),
                statement_type="income_statement",
                metric="營業收入",
                value=1,
                source="test",
            )
            for _ in range(40)
        ],
        ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=20, pb_ratio=5),
        MonthlyRevenue(ticker="2330", revenue_date=date(2026, 4, 1), revenue=1, revenue_year=2026, revenue_month=4),
    ) == "高"
    stale_valuation = ValuationMetric(
        ticker="2382",
        trade_date=date(2026, 5, 22),
        pe_ratio=12,
        pb_ratio=3,
        source="FinMind TaiwanStockPER; cached-stale",
    )
    assert ReportGenerator._valuation_position_label(stale_valuation, peer) == "估值為快取救援，需刷新"
    assert ReportGenerator._financial_confidence_label(
        [
            FinancialMetric(
                ticker="2330",
                report_date=date(2026, 3, 31),
                statement_type="income_statement",
                metric="營業收入",
                value=1,
                source="FinMind TaiwanStockFinancialStatements; cached-stale",
            )
            for _ in range(40)
        ],
        ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=20, pb_ratio=5),
        MonthlyRevenue(ticker="2330", revenue_date=date(2026, 4, 1), revenue=1, revenue_year=2026, revenue_month=4),
    ) == "中"


def test_stale_market_data_downgrades_company_quality_and_valuation_assessment() -> None:
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        close=100,
        source="FinMind TaiwanStockPrice; cached-stale",
    )
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 1),
        revenue=1,
        revenue_year=2026,
        revenue_month=4,
        source="FinMind TaiwanStockMonthRevenue; cached-stale",
    )
    metrics = [
        FinancialMetric(
            ticker="2330",
            report_date=date(2026, 3, 31),
            statement_type="income_statement",
            metric="營業收入",
            value=100,
            source="FinMind TaiwanStockFinancialStatements; cached-stale",
        )
    ]
    valuation = ValuationMetric(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        pe_ratio=12,
        pb_ratio=3,
        source="FinMind TaiwanStockPER; cached-stale",
    )

    quality = ReportGenerator._data_quality_grade(
        [],
        [],
        snapshot,
        revenue,
        metrics,
        valuation,
        include_fundamentals=True,
        company_filing_missing=[],
    )
    helper_quality = data_quality_grade(
        [],
        [],
        snapshot,
        revenue,
        metrics,
        valuation,
        include_fundamentals=True,
        company_filing_missing=[],
    )
    assessment = ReportGenerator._financial_valuation_assessment(
        metrics,
        valuation,
        {"pe_avg": 20.0, "pb_avg": 5.0, "count": 3},
    )
    helper_assessment = financial_valuation_assessment(
        metrics,
        valuation,
        {"pe_avg": 20.0, "pb_avg": 5.0, "count": 3},
    )

    assert helper_assessment == assessment
    assert helper_quality == quality
    assert quality["grade"] == "partial"
    assert "股價為快取救援" in quality["missing"]
    assert "財報為快取救援" in quality["missing"]
    assert "估值資料為快取救援，刷新前不判定低估/高估" in assessment["cautions"]
    assert "目前估值低於同業" not in assessment["upside_summary"]


def test_financial_assessment_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    financial_mixin_source = Path("app/services/report_generator_financial.py").read_text()
    assessment_source = Path("app/services/report_financial_assessment.py").read_text()

    assert "ReportGeneratorFinancialMixin" in generator_source
    assert "from app.services.report_financial_assessment import" in financial_mixin_source
    assert "def _financial_valuation_assessment(" not in generator_source
    assert "def _financial_valuation_assessment(" in financial_mixin_source
    assert "def financial_valuation_assessment(" in assessment_source
    assert "def valuation_position_label(" in assessment_source
    assert "財務資料為快取救援" not in generator_source


def test_potential_scoring_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    potential_mixin_source = Path("app/services/report_generator_potential.py").read_text()
    potential_source = Path("app/services/report_potential.py").read_text()

    assert "report_potential" not in generator_source
    assert "ReportGeneratorPotentialMixin" in generator_source
    assert "report_potential" in potential_mixin_source
    assert "def _estimate_potential(" in potential_mixin_source
    assert "def _data_quality_grade(" in potential_mixin_source
    assert "def estimate_potential(" in potential_source
    assert "def data_quality_grade(" in potential_source
    assert "PotentialScoringEngine" not in generator_source
    assert "def _estimate_potential(" not in generator_source
    assert "def _data_quality_grade(" not in generator_source


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
    helper_estimate = estimate_potential([], [], snapshot, revenue)
    check = ReportGenerator._render_revenue_check(["2330"], [revenue])

    assert helper_estimate == estimate
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


def test_severe_annual_decline_gets_high_financial_risk_score() -> None:
    snapshot = MarketSnapshot(ticker="1303", trade_date=date(2026, 5, 22), close=40)
    revenue = MonthlyRevenue(
        ticker="1303",
        revenue_date=date(2026, 5, 10),
        revenue=10_000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=19.4,
    )
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
                FinancialMetric(
                    ticker="1303",
                    report_date=date(year, 12, 31),
                    statement_type="balance_sheet",
                    metric="負債總額",
                    value=100.0,
                    source="test",
                ),
                FinancialMetric(
                    ticker="1303",
                    report_date=date(year, 12, 31),
                    statement_type="balance_sheet",
                    metric="權益總額",
                    value=200.0,
                    source="test",
                ),
            ]
        )

    estimate = ReportGenerator._estimate_potential(
        [
            NewsFetcher.from_manual_text(
                title="南亞 工程塑膠需求觀察",
                text="南亞 工程塑膠需求觀察。",
                publisher="測試新聞A",
                published_at=date(2026, 5, 20),
            ),
            NewsFetcher.from_manual_text(
                title="南亞 電子材料受惠題材",
                text="南亞 電子材料受惠題材。",
                publisher="測試新聞B",
                published_at=date(2026, 5, 21),
            ),
        ],
        [],
        snapshot,
        revenue,
        None,
        metrics,
        None,
    )

    assert estimate["financial_assessment"]["risk_score"] >= 7
    assert estimate["downside_pct"] >= 13
    assert "2022-2025 年度營收下滑 40.3%" in estimate["downside_reason"]
    assert "2022-2025 年度淨利下滑 71.6%" in estimate["downside_reason"]


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
