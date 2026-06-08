from datetime import date
from pathlib import Path

from app.data_sources.news import NewsFetcher
from app.models.schemas import (
    EntityMatch,
    FinancialMetric,
    MarketSnapshot,
    MonthlyRevenue,
    ReportRequest,
    RiskFinding,
    RiskType,
    Source,
    ValuationMetric,
)
from app.services import report_leading_signal, report_monitoring_checklist
from app.services.entity_mapping import EntityMapper
from app.services.leading_signals import LeadingSignal, LeadingSignalAnalyzer
from app.services.report_decision_rules import recheck_trigger_text
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


def test_leading_signal_analyzer_scores_price_revenue_and_valuation() -> None:
    prices = [
        MarketSnapshot(
            ticker="2330",
            trade_date=date(2026, 1, day),
            close=100 + day,
            trading_volume=1_000,
        )
        for day in range(1, 31)
    ]
    prices[-1] = prices[-1].model_copy(update={"close": 140, "trading_volume": 2_000})
    revenues = [
        MonthlyRevenue(
            ticker="2330",
            revenue_date=date(2026, month, 10),
            revenue=1000 + month,
            revenue_year=2026,
            revenue_month=month,
            yoy_pct=10 + month,
        )
        for month in range(1, 5)
    ]
    valuation = ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=12, pb_ratio=2)

    signal = LeadingSignalAnalyzer().analyze(
        "2330",
        prices,
        revenues,
        valuation,
        {"pe_avg": 20, "pb_avg": 3},
    )

    assert signal.direction == "偏多"
    assert signal.upside_bonus > 0
    assert signal.downside_penalty == 0
    assert "目前估值低於同業" in signal.bullish_factors


def test_negative_profitability_removes_low_valuation_from_leading_signal() -> None:
    signal = LeadingSignal(
        ticker="4540",
        score=6,
        upside_bonus=6,
        downside_penalty=0,
        bullish_factors=["月營收年增 33.4%", "目前估值低於同業"],
        valuation_label="目前估值低於同業",
    )

    sanitized = ReportGenerator._sanitize_leading_signal_for_profitability(signal, True)

    assert sanitized.upside_bonus == 4
    assert sanitized.valuation_label == "獲利為負，不判低估"
    assert "目前估值低於同業" not in sanitized.summary


def test_estimate_potential_uses_leading_signal_bonus() -> None:
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        close=2255.0,
        source="FinMind TaiwanStockPrice",
    )
    signal = LeadingSignalAnalyzer().analyze(
        "2330",
        [
            MarketSnapshot(ticker="2330", trade_date=date(2026, 1, day), close=100 + day, trading_volume=1000)
            for day in range(1, 31)
        ],
        [],
    )

    estimate = ReportGenerator._estimate_potential([], [], snapshot, None, signal)

    assert estimate["upside_pct"] > 10
    assert any("近況" in label for label, _score in estimate["upside_factors"])


def test_bearish_leading_signal_does_not_create_positive_score_text() -> None:
    snapshot = MarketSnapshot(ticker="6235", trade_date=date(2026, 5, 22), close=100)
    signal = LeadingSignal(
        ticker="6235",
        score=-7,
        upside_bonus=4,
        downside_penalty=7,
        bearish_factors=["20 日股價轉弱 -12.0%"],
    )

    estimate = ReportGenerator._estimate_potential([], [], snapshot, None, signal)

    assert "近況訊號偏空觸發正向加分" not in estimate["upside_reason"]
    assert not any("近況訊號偏多" in label for label, _score in estimate["upside_factors"])
    assert "近況訊號偏空觸發風險加分 7 點" in estimate["downside_reason"]


def test_neutral_leading_signal_describes_subitems_not_directional_trigger() -> None:
    snapshot = MarketSnapshot(ticker="3131", trade_date=date(2026, 5, 22), close=100)
    signal = LeadingSignal(
        ticker="3131",
        score=0,
        upside_bonus=6,
        downside_penalty=8,
        bullish_factors=["月營收年增 28.0%"],
        bearish_factors=["目前估值偏高"],
    )

    estimate = ReportGenerator._estimate_potential([], [], snapshot, None, signal)

    assert "近況正向子項目加分 6 點" in estimate["upside_reason"]
    assert "近況風險子項目風險加分 8 點" in estimate["downside_reason"]
    assert "近況訊號中性觸發" not in estimate["upside_reason"]
    assert "近況訊號中性觸發" not in estimate["downside_reason"]
    assert any("近況正向子項目" in label for label, _score in estimate["upside_factors"])
    assert any("近況風險子項目" in label for label, _score in estimate["downside_factors"])


def test_bearish_leading_signal_blocks_actionable_rating() -> None:
    signal = LeadingSignal(
        ticker="2330",
        score=-6,
        upside_bonus=0,
        downside_penalty=6,
        bearish_factors=["20 日股價轉弱 -12.0%"],
    )
    estimate = {"upside_pct": 18, "downside_pct": 4}
    quality = {"grade": "supported", "missing": []}

    rating = ReportGenerator._decision_label(estimate, quality, [], 5, signal)
    reason = ReportGenerator._decision_reason(
        rating,
        estimate,
        quality,
        [],
        [],
        5,
        ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
        signal,
    )

    assert rating == "觀察 / 等風險降低"
    assert "近況訊號偏空" in reason


def test_recheck_trigger_text_uses_signal_risk_and_missing_data() -> None:
    signal = LeadingSignal(
        ticker="2330",
        score=-6,
        upside_bonus=0,
        downside_penalty=6,
        bearish_factors=["20 日股價轉弱 -12.0%"],
    )

    trigger = ReportGenerator._recheck_trigger_text(
        {
            "estimate": {"upside_pct": 18, "downside_pct": 9},
            "quality": {"missing": ["缺估值"]},
            "leading_signal": signal,
        }
    )
    helper_trigger = recheck_trigger_text(
        {
            "estimate": {"upside_pct": 18, "downside_pct": 9},
            "quality": {"missing": ["缺估值"]},
            "leading_signal": signal,
        }
    )

    assert helper_trigger == trigger
    assert "補齊缺估值" in trigger
    assert "近況訊號由偏空轉為中性以上" in trigger
    assert "目前情境降值分降至 5 分以下" in trigger

    aggressive_trigger = ReportGenerator._recheck_trigger_text(
        {
            "estimate": {"upside_pct": 18, "downside_pct": 14},
            "quality": {"missing": []},
            "leading_signal": signal,
        },
        downside_gate=12,
    )
    assert "目前情境降值分降至 12 分以下" in aggressive_trigger

    aggressive_avoid = ReportGenerator._avoid_trigger_text(
        {"estimate": {"upside_pct": 18, "downside_pct": 9}},
        downside_gate=12,
    )
    assert "目前情境降值分仍高於 5 分" not in aggressive_avoid


def test_monitoring_checklist_renders_recheck_and_avoid_rules() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"])
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=100)
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=100,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=20,
    )
    signal = LeadingSignal(
        ticker="2330",
        score=-6,
        upside_bonus=0,
        downside_penalty=6,
        bearish_factors=["20 日股價轉弱 -12.0%"],
    )

    markdown = generator._render_monitoring_checklist(
        request,
        ["2330"],
        [
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
        ],
        [make_finding("2330", "台積電", "台積電 AI 需求成長", RiskType.opportunity_or_growth)],
        [snapshot],
        [revenue],
        [
            FinancialMetric(
                ticker="2330",
                report_date=date(2026, 3, 31),
                statement_type="income_statement",
                metric="營收",
                value=1,
                source="test",
            )
        ],
        [ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=20, pb_ratio=3)],
        {"2330": signal},
    )

    assert "| 股票 | 目前動作 | 重新研究條件 |" in markdown
    assert "近況訊號由偏空轉為中性以上" in markdown
    assert "近況訊號維持偏空" in markdown
    assert "每週" in markdown


def test_monitoring_checklist_logic_lives_outside_generator() -> None:
    generator = object.__new__(ReportGenerator)
    request = ReportRequest(tickers=[])
    generator_source = Path("app/services/report_generator.py").read_text()
    monitoring_source = Path("app/services/report_monitoring_checklist.py").read_text()

    assert "report_monitoring_checklist" in generator_source
    assert "def render_monitoring_checklist(" in monitoring_source
    assert "這張表把觀察與避開名單轉成" not in generator_source
    assert generator._render_monitoring_checklist(request, [], [], [], []) == (
        report_monitoring_checklist.render_monitoring_checklist([], ReportGenerator._downside_gate(request))
    )


def test_render_leading_signal_check_outputs_table() -> None:
    signal = LeadingSignalAnalyzer().analyze(
        "2330",
        [
            MarketSnapshot(ticker="2330", trade_date=date(2026, 1, day), close=100 + day, trading_volume=1000)
            for day in range(1, 31)
        ],
        [],
    )

    markdown = ReportGenerator._render_leading_signal_check(["2330"], {"2330": signal})

    assert "領先訊號檢查" not in markdown
    assert "| 股票 | 近況方向 | 分數 |" in markdown
    assert "2330" in markdown


def test_leading_signal_render_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    leading_source = Path("app/services/report_leading_signal.py").read_text()

    assert "report_leading_signal" in generator_source
    assert "def render_leading_signal_check(" in leading_source
    assert "def format_optional_pct(" in leading_source
    assert "本段使用截至最新資料日" not in generator_source
    assert ReportGenerator._render_leading_signal_check([], {}) == report_leading_signal.render_leading_signal_check(
        [],
        {},
    )
    assert ReportGenerator._format_optional_pct(1.23) == report_leading_signal.format_optional_pct(1.23)
    assert ReportGenerator._format_optional_ratio(2.34) == report_leading_signal.format_optional_ratio(2.34)
