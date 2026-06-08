from __future__ import annotations

from datetime import date
from pathlib import Path

from app.data_sources.news import NewsFetcher
from app.models.schemas import (
    FinancialMetric,
    InvestorProfile,
    MarketSnapshot,
    MonthlyRevenue,
    ReportRequest,
    RiskType,
    ValuationMetric,
)
from app.services.entity_mapping import EntityMapper
from app.services.report_generator import ReportGenerator
from app.services.report_potential import estimate_potential
from app.services.whitelist import SupplyChainWhitelist
from report_generator_factories import make_financial_metrics, make_finding


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
