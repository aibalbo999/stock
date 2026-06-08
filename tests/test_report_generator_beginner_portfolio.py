from datetime import date
from pathlib import Path

from app.data_sources.news import NewsFetcher
from app.models.schemas import InvestorProfile, MarketSnapshot, MonthlyRevenue, ReportRequest, RiskType
from app.services import report_beginner_portfolio
from app.services.entity_mapping import EntityMapper
from app.services.report_generator import ReportGenerator
from app.services.whitelist import SupplyChainWhitelist
from report_generator_factories import make_finding


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


def test_beginner_portfolio_plan_logic_lives_outside_generator() -> None:
    generator = object.__new__(ReportGenerator)
    request = ReportRequest(tickers=[])
    generator_source = Path("app/services/report_generator.py").read_text()
    portfolio_source = Path("app/services/report_beginner_portfolio.py").read_text()

    assert "report_beginner_portfolio" in generator_source
    assert "def render_beginner_portfolio_plan(" in portfolio_source
    assert "def source_label(" in portfolio_source
    assert "資金設定：總資金" not in generator_source
    assert generator._render_beginner_portfolio_plan(request, [], [], [], []) == (
        report_beginner_portfolio.render_beginner_portfolio_plan(
            [],
            request,
            generator._decision_reason,
        )
    )


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
