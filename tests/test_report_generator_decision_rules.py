from datetime import date
from pathlib import Path

from app.models.schemas import MarketSnapshot
from app.services.report_decision_rules import current_price_label, risk_warning_reason, sort_decision_contexts
from app.services.report_generator import ReportGenerator


def test_report_reading_order_groups_by_decision_then_current_price() -> None:
    contexts = [
        {
            "ticker": "9999",
            "decision": "避開 / 降低曝險",
            "snapshot": MarketSnapshot(ticker="9999", trade_date=date(2026, 5, 22), close=5000.0),
            "estimate": {"upside_pct": 30, "downside_pct": 40},
        },
        {
            "ticker": "2382",
            "decision": "可小額分批研究",
            "snapshot": MarketSnapshot(ticker="2382", trade_date=date(2026, 5, 22), close=300.0),
            "estimate": {"upside_pct": 18, "downside_pct": 3},
        },
        {
            "ticker": "2330",
            "decision": "可小額分批研究",
            "snapshot": MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=1000.0),
            "estimate": {"upside_pct": 12, "downside_pct": 4},
        },
        {
            "ticker": "2308",
            "decision": "觀察 / 等風險降低",
            "snapshot": MarketSnapshot(ticker="2308", trade_date=date(2026, 5, 22), close=200.0),
            "estimate": {"upside_pct": 24, "downside_pct": 11},
        },
    ]

    ordered = ReportGenerator._sort_decision_contexts(contexts)
    helper_ordered = sort_decision_contexts(contexts)

    assert [context["ticker"] for context in ordered] == ["2330", "2382", "2308", "9999"]
    assert helper_ordered == ordered


def test_decision_rule_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    decision_risk_mixin_source = Path("app/services/report_generator_decision_risk.py").read_text()
    decision_rule_source = Path("app/services/report_decision_rules.py").read_text()

    assert "report_decision_rules" not in generator_source
    assert "ReportGeneratorDecisionRiskMixin" in generator_source
    assert "report_decision_rules" in decision_risk_mixin_source
    assert "def _sort_decision_contexts(" in decision_risk_mixin_source
    assert "def _risk_warning_reason(" in decision_risk_mixin_source
    assert "def _sort_decision_contexts(" not in generator_source
    assert "def sort_decision_contexts(" in decision_rule_source
    assert "def recheck_trigger_text(" in decision_rule_source
    assert "def current_price_label(" in decision_rule_source
    assert "def risk_warning_reason(" in decision_rule_source


def test_current_price_label_summarizes_immediate_entry_condition() -> None:
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=100)
    quality = {"missing": [], "grade": "supported"}
    research_label = ReportGenerator._current_price_label(
        snapshot,
        {"upside_pct": 18, "downside_pct": 4},
        quality,
        "目前估值接近同業",
        None,
        "可小額分批研究",
        5,
    )
    assert (
        current_price_label(
            snapshot,
            {"upside_pct": 18, "downside_pct": 4},
            quality,
            "目前估值接近同業",
            None,
            "可小額分批研究",
            5,
        )
        == "可小額分批"
    )
    assert research_label == "可小額分批"
    assert (
        ReportGenerator._current_price_label(
            snapshot,
            {"upside_pct": 18, "downside_pct": 14},
            quality,
            "目前估值偏高",
            None,
            "避開 / 降低曝險",
            5,
        )
        == "不適合追價"
    )


def test_risk_warning_reason_distinguishes_threshold_from_relative_risk() -> None:
    balanced_case = {"upside_pct": 16, "downside_pct": 13}
    risk_heavy_case = {"upside_pct": 8, "downside_pct": 13}

    assert risk_warning_reason(balanced_case) == ReportGenerator._risk_warning_reason(balanced_case)
    assert ReportGenerator._risk_warning_reason(balanced_case) == (
        "財務或估值紅旗偏重，需先等基本面修復或補充來源驗證。"
    )
    assert risk_warning_reason(risk_heavy_case) == ReportGenerator._risk_warning_reason(risk_heavy_case)
    assert ReportGenerator._risk_warning_reason(risk_heavy_case) == (
        "目前情境降值分高於升值分，風險權重已壓過投資理由，不適合追價。"
    )
