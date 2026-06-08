from datetime import date
from pathlib import Path
from typing import Optional

from app.data_sources.news import NewsFetcher
from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ReportRequest, ValuationMetric
from app.services.entity_mapping import EntityMapper
from app.services import (
    report_company_filing_checks,
    report_company_narrative,
    report_decision_contexts,
)
from app.services.report_generator import (
    ReportGenerator,
)
from app.services.whitelist import SupplyChainWhitelist


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

