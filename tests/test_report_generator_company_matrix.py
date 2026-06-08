from datetime import date
from pathlib import Path

from app.data_sources.news import NewsFetcher
from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ReportRequest, RiskType, ValuationMetric
from app.services import report_company_matrix
from app.services.entity_mapping import EntityMapper
from app.services.report_generator import ReportGenerator
from app.services.whitelist import SupplyChainWhitelist
from report_generator_factories import make_finding


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
