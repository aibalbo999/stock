from datetime import date
from pathlib import Path

from app.models.schemas import MonthlyRevenue
from app.services import report_formatting, report_scope_sections
from app.services.report_generator import ReportGenerator


def test_report_formatting_helpers_live_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    formatting_mixin_source = Path("app/services/report_generator_formatting.py").read_text()
    formatting_source = Path("app/services/report_formatting.py").read_text()

    assert "report_formatting" not in generator_source
    assert "ReportGeneratorFormattingMixin" in generator_source
    assert "report_formatting" in formatting_mixin_source
    assert "def _compact_text(" in formatting_mixin_source
    assert "def _table_row(" in formatting_mixin_source
    assert "def compact_text(" in formatting_source
    assert "def table_row(" in formatting_source
    assert "replace(\"|\", \"\\\\|\")" not in generator_source
    assert "def _compact_text(" not in generator_source
    assert "def _table_row(" not in generator_source
    assert ReportGenerator._table_row(["2330 | 台積電", "  可研究  "]) == report_formatting.table_row(
        ["2330 | 台積電", "  可研究  "]
    )
    assert ReportGenerator._compact_text("abc def ghi", 7) == report_formatting.compact_text("abc def ghi", 7)
    assert report_formatting.table_row(["2330 | 台積電", "  可研究  "]) == "| 2330 \\| 台積電 | 可研究 |"


def test_scope_section_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    market_scope_mixin_source = Path("app/services/report_generator_market_scope.py").read_text()
    scope_source = Path("app/services/report_scope_sections.py").read_text()
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=349567000000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=18.5,
        source="FinMind TaiwanStockMonthRevenue",
    )

    assert "report_scope_sections" not in generator_source
    assert "ReportGeneratorMarketScopeMixin" in generator_source
    assert "report_scope_sections" in market_scope_mixin_source
    assert "def _render_scope(" in market_scope_mixin_source
    assert "def _render_revenue_check(" in market_scope_mixin_source
    assert "def _render_revenue_check(" not in generator_source
    assert "def render_scope(" in scope_source
    assert "def render_revenue_check(" in scope_source
    assert "可先呼叫 /market/refresh" not in generator_source
    assert ReportGenerator._render_revenue_check(["2330"], [revenue]) == report_scope_sections.render_revenue_check(
        ["2330"],
        [revenue],
    )
