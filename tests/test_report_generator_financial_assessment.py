from datetime import date
from pathlib import Path

from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ValuationMetric
from app.services.report_financial_assessment import (
    financial_valuation_assessment,
    valuation_position_label,
)
from app.services.report_financial_narrative import financial_statement_summary
from app.services.report_generator import ReportGenerator
from app.services.report_potential import data_quality_grade


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
