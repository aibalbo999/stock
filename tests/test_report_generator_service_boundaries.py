from datetime import date
from pathlib import Path

from app.models.schemas import MonthlyRevenue, ValuationMetric
from app.services import (
    report_company_filing_checks,
    report_company_narrative,
    report_decision_contexts,
)
from app.services.report_generator import ReportGenerator


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
