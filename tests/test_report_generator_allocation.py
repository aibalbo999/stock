from pathlib import Path

from app.models.schemas import ReportRequest
from app.services import report_allocation
from app.services.report_generator import ReportGenerator


def test_report_allocation_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    allocation_mixin_source = Path("app/services/report_generator_allocation.py").read_text()
    allocation_source = Path("app/services/report_allocation.py").read_text()
    request = ReportRequest(
        topic="AI 產業鏈",
        tickers=["2330"],
        investor_capital=1_000_000,
        beginner_mode=True,
        max_position_pct=0.10,
        cash_reserve_pct=0.30,
    )
    candidates = [
        {"label": "2382 廣達", "upside_pct": 19, "downside_pct": 0},
        {"label": "3324 雙鴻", "upside_pct": 16, "downside_pct": 0},
    ]

    assert "report_allocation" not in generator_source
    assert "ReportGeneratorAllocationMixin" in generator_source
    assert "report_allocation" in allocation_mixin_source
    assert "def _allocation_amounts(" in allocation_mixin_source
    assert "def _render_allocation_plan(" in allocation_mixin_source
    assert "def allocation_amounts(" in allocation_source
    assert "def first_tranche_ratio(" in allocation_source
    assert "配置採淨分" not in generator_source
    assert "def _allocation_amounts(" not in generator_source
    assert "def _render_allocation_plan(" not in generator_source
    assert ReportGenerator._allocation_amounts(candidates, 50_000, 100_000) == (
        report_allocation.allocation_amounts(candidates, 50_000, 100_000)
    )
    assert ReportGenerator._render_allocation_plan(candidates, 50_000, 100_000) == (
        report_allocation.render_allocation_plan(candidates, 50_000, 100_000)
    )
    assert ReportGenerator._profile_label(request) == report_allocation.profile_label(request)
    assert ReportGenerator._downside_gate(request) == report_allocation.downside_gate(request)


def test_allocation_plan_caps_each_first_tranche_and_total_budget() -> None:
    rows = ReportGenerator._render_allocation_plan(
        [
            {"label": "2382 廣達", "upside_pct": 19, "downside_pct": 0},
            {"label": "3324 雙鴻", "upside_pct": 16, "downside_pct": 0},
        ],
        deployable=50_000,
        first_tranche=100_000,
    )

    assert rows[0].startswith("本輪首筆配置合計約 50,000 元；可投入上限 50,000 元。")
    assert "套用單檔首筆上限與萬元取整" in rows[0]
    assert "2382 廣達：首筆配置約 30,000 元" in rows[1]
    assert "淨分 19" in rows[1]
    assert "3324 雙鴻：首筆配置約 20,000 元" in rows[2]


def test_allocation_plan_keeps_all_research_candidates_in_total() -> None:
    rows = ReportGenerator._render_allocation_plan(
        [
            {"label": "2308 台達電", "upside_pct": 46, "downside_pct": 11},
            {"label": "4583 大銀微系統", "upside_pct": 24, "downside_pct": 8},
            {"label": "2359 所羅門", "upside_pct": 27, "downside_pct": 7},
            {"label": "1504 東元", "upside_pct": 30, "downside_pct": 0},
        ],
        deployable=700_000,
        first_tranche=50_000,
    )

    assert rows[0].startswith("本輪首筆配置合計約 180,000 元；")
    assert len([row for row in rows if row.startswith("- ")]) == 4
    assert "2308 台達電：首筆配置約 50,000 元" in rows[1]
    assert "4583 大銀微系統：首筆配置約 40,000 元" in rows[2]
    assert "2359 所羅門：首筆配置約 40,000 元" in rows[3]
    assert "1504 東元：首筆配置約 50,000 元" in rows[4]
