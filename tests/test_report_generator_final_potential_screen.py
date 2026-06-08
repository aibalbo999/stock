from datetime import date

from app.data_sources.news import NewsFetcher
from app.models.schemas import (
    FinancialMetric,
    InvestorProfile,
    MarketSnapshot,
    MonthlyRevenue,
    ReportRequest,
    ValuationMetric,
)
from app.services.entity_mapping import EntityMapper
from app.services.report_generator import ReportGenerator
from app.services.whitelist import SupplyChainWhitelist


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
