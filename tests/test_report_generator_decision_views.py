from datetime import date
from pathlib import Path

from app.data_sources.news import NewsFetcher
from app.models.schemas import (
    EntityMatch,
    MarketSnapshot,
    MonthlyRevenue,
    ReportRequest,
    RiskFinding,
    RiskType,
    Source,
)
from app.services import (
    report_action_checklist,
    report_executive_snapshot,
    report_final_potential,
)
from app.services.entity_mapping import EntityMapper
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


def test_executive_snapshot_summarizes_decisions_in_table() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    snapshot_source = Path("app/services/report_executive_snapshot.py").read_text()
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
    assert "| 股票 | 判斷 | 最新可取得收盤價 | 追價風險標籤 | 資料等級 | 目前情境升值分 | 目前情境降值分 | 近況訊號 | 主要缺口 |" in snapshot_text
    assert "| 2330 台積電 | 可小額分批研究 | 2026-05-22 收盤 2255 | 可小額分批 | 完整 |" in snapshot_text
    assert "| 可小額研究 | 1 檔 |" in snapshot_text
    decision_views_mixin_source = Path("app/services/report_generator_decision_views.py").read_text()
    assert "report_executive_snapshot" not in generator_source
    assert "ReportGeneratorDecisionViewsMixin" in generator_source
    assert "report_executive_snapshot" in decision_views_mixin_source
    assert "def _render_executive_snapshot(" in decision_views_mixin_source
    assert "def _render_executive_snapshot(" not in generator_source
    assert "def render_executive_snapshot(" in snapshot_source
    assert "def decision_counts(" in snapshot_source
    assert "決策總覽" not in generator_source
    assert "品質門檻最多允許研究" not in generator_source
    assert report_executive_snapshot.is_low_attention_topic("AI 產業鏈低關注潛力股")


def test_executive_snapshot_warns_low_attention_topic_needs_radar_check() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(topic="AI 產業鏈低關注潛力股", tickers=["2330"], investor_capital=1_000_000)
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
            title="台積電 AI 需求成長",
            text="台積電 AI 需求成長。",
            publisher="測試新聞A",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 AI 伺服器需求延續",
            text="台積電 AI 伺服器需求延續。",
            publisher="測試新聞B",
            published_at=date(2026, 5, 21),
        ),
    ]

    snapshot_text = generator._render_executive_snapshot(
        request,
        ["2330"],
        documents,
        [make_finding("2330", "台積電", "台積電 AI 需求成長", RiskType.opportunity_or_growth)],
        [snapshot],
        [revenue],
    )

    assert "| 低關注核對 | 可小額研究不等於低關注" in snapshot_text
    assert "早期潛力雷達" in snapshot_text


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


def test_action_checklist_logic_lives_outside_generator() -> None:
    generator = object.__new__(ReportGenerator)
    request = ReportRequest(tickers=[])
    generator_source = Path("app/services/report_generator.py").read_text()
    checklist_source = Path("app/services/report_action_checklist.py").read_text()

    assert "report_action_checklist" in generator_source
    assert "def render_action_checklist(" in checklist_source
    assert "先處理資料缺口" not in generator_source
    assert generator._render_action_checklist(request, [], [], [], []) == (
        report_action_checklist.render_action_checklist([], ReportGenerator._downside_gate(request))
    )


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

    assert "### 升值分高但仍需觀察" in screen
    assert "升值分約" in screen
    assert "目前證據的情境降值分約" in screen
    assert "2330 台積電" in screen


def test_final_potential_screen_logic_lives_outside_generator() -> None:
    generator = object.__new__(ReportGenerator)
    generator_source = Path("app/services/report_generator.py").read_text()
    final_source = Path("app/services/report_final_potential.py").read_text()

    assert "report_final_potential" in generator_source
    assert "def render_final_potential_screen(" in final_source
    assert "def source_label(" in final_source
    assert "本段為非個人化情境篩選" not in generator_source
    assert generator._render_final_potential_screen([], [], [], []) == (
        report_final_potential.render_final_potential_screen([])
    )
