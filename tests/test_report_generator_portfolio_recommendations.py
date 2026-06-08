from datetime import date
from pathlib import Path

from app.data_sources.news import NewsFetcher
from app.models.schemas import (
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ReportRequest,
    RiskType,
    Source,
)
from app.services import report_investment_recommendations
from app.services.entity_mapping import EntityMapper
from app.services.report_generator import ReportGenerator
from app.services.whitelist import SupplyChainWhitelist
from report_generator_factories import make_finding


def unescaped_pipe_count(line: str) -> int:
    return sum(1 for index, char in enumerate(line) if char == "|" and (index == 0 or line[index - 1] != "\\"))


def test_investment_recommendations_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    decision_views_mixin_source = Path("app/services/report_generator_decision_views.py").read_text()
    recommendations_source = Path("app/services/report_investment_recommendations.py").read_text()
    request = ReportRequest(tickers=["2330"])
    context = {
        "ticker": "2330",
        "label": "2330 台積電",
        "current_price": "目前無足夠數據判斷",
        "current_price_label": "觀察等待",
        "decision": "觀察 / 資料待補",
        "rationale": "缺資料。",
        "documents": [],
        "snapshot": None,
        "revenue": None,
    }

    assert "report_investment_recommendations" not in generator_source
    assert "ReportGeneratorDecisionViewsMixin" in generator_source
    assert "report_investment_recommendations" in decision_views_mixin_source
    assert "def _render_investment_recommendations(" in decision_views_mixin_source
    assert "def _render_investment_recommendations(" not in generator_source
    assert "def render_investment_recommendations(" in recommendations_source
    assert "def recommendation_row(" in recommendations_source
    assert "未納入投資人風險承受度" not in generator_source
    assert "| 股票 | 最新可取得收盤價 | 追價風險標籤 | 建議 | 理由 | 單檔上限 | 來源 |" not in generator_source
    assert report_investment_recommendations.render_investment_recommendations(
        [context],
        request,
        "排序說明",
        lambda documents: "代表性來源",
    ) == (
        "以下為非個人化研究建議；未納入投資人風險承受度、持股成本與資金配置，不構成個別買賣指令。\n"
        "排序說明\n\n"
        "| 股票 | 最新可取得收盤價 | 追價風險標籤 | 建議 | 理由 | 單檔上限 | 來源 |\n"
        "|---|---|---|---|---|---:|---|\n"
        "| 2330 台積電 | 目前無足夠數據判斷 | 觀察等待 | 觀察 / 資料待補 | 缺資料。 | 不適用 / 0 元 | 目前無足夠數據判斷 |"
    )


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
