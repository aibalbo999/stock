from datetime import date
from pathlib import Path

from app.data_sources.news import NewsFetcher
from app.models.schemas import (
    EntityMatch,
    FinancialMetric,
    InvestorProfile,
    MarketSnapshot,
    MonthlyRevenue,
    ReportRequest,
    RiskFinding,
    RiskType,
    Source,
    ValuationMetric,
)
from app.services import report_investment_thesis
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


def test_investment_thesis_map_explains_reasons_sources_and_limits() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    generator._company_filing_missing = lambda ticker, documents: []
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"], beginner_mode=False)
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
    valuation = ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=18, pb_ratio=4)
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 AI 需求成長",
            text="台積電 AI 需求成長。",
            publisher="測試新聞A",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 大單",
            text="台積電 CoWoS 大單。",
            publisher="測試新聞B",
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

    thesis = generator._render_investment_thesis_map(
        request,
        ["2330"],
        documents,
        findings,
        [snapshot],
        [revenue],
        metrics,
        [valuation],
    )

    assert "## 投資理由地圖" not in thesis
    assert "這是研究假設，不是報酬保證或買賣指令" in thesis
    assert "### 2330 台積電" in thesis
    assert "具體投資理由" in thesis
    assert "目前情境升值分" in thesis
    assert "代表性來源：2026-05-21 測試新聞B《台積電 CoWoS 大單》" in thesis
    assert "2026-05-20 測試新聞A《台積電 AI 需求成長》" in thesis


def test_investment_thesis_map_logic_lives_outside_generator() -> None:
    generator = object.__new__(ReportGenerator)
    request = ReportRequest(tickers=[])
    generator_source = Path("app/services/report_generator.py").read_text()
    thesis_source = Path("app/services/report_investment_thesis.py").read_text()

    assert "report_investment_thesis" in generator_source
    assert "def render_investment_thesis_map(" in thesis_source
    assert "def thesis_reason(" in thesis_source
    assert "本段把每檔股票拆成" not in generator_source
    assert generator._render_investment_thesis_map(request, [], [], [], []) == (
        report_investment_thesis.render_investment_thesis_map(
            [],
            request,
            "",
            generator._representative_sources,
            generator._downside_source_references,
        )
    )


def test_yoy_growth_and_mom_decline_are_explained_together() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "2308",
                "name": "台達電",
                "segment": "電源與散熱",
                "status": "evidence_supported",
                "evidence_keywords": ["AI 電源"],
            }
        ]
    )
    generator.mapper = EntityMapper(generator.whitelist)
    generator._company_filing_missing = lambda ticker, documents: []
    request = ReportRequest(topic="AI 產業鏈", tickers=["2308"], investor_profile=InvestorProfile.balanced)
    snapshot = MarketSnapshot(ticker="2308", trade_date=date(2026, 5, 22), close=1000)
    revenue = MonthlyRevenue(
        ticker="2308",
        revenue_date=date(2026, 5, 10),
        revenue=10_000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=43.92,
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="台達電4月營收下滑 仍寫次高",
            text="台達電 4 月營收較上月下滑，但年增仍維持高檔。",
            publisher="測試新聞",
            published_at=date(2026, 5, 10),
        ),
        NewsFetcher.from_manual_text(
            title="台達電 AI 電源需求成長",
            text="台達電 AI 電源需求成長。",
            publisher="測試新聞B",
            published_at=date(2026, 5, 11),
        ),
    ]

    thesis = generator._render_investment_thesis_map(
        request,
        ["2308"],
        documents,
        [],
        [snapshot],
        [revenue],
        [],
        [],
        {},
    )

    assert "營收口徑提醒" in thesis
    assert "YoY 年增" in thesis
    assert "MoM 月減" in thesis


def test_thesis_reason_for_avoid_does_not_read_like_buy_reason() -> None:
    reason = ReportGenerator._thesis_reason(
        {
            "decision": "避開 / 降低曝險",
            "estimate": {
                "upside_pct": 33,
                "downside_pct": 17,
                "financial_assessment": {
                    "red_flag": True,
                    "risk_score": 10,
                    "risk_summary": "2021-2025 年度營收下滑 40.3%",
                },
            },
            "quality": {"grade": "supported", "missing": []},
        },
        ReportRequest(topic="機器人 產業鏈", tickers=["1303"], investor_profile=InvestorProfile.aggressive),
    )

    assert "本段不是買進理由" in reason
    assert "財務/估值紅旗偏重" in reason
