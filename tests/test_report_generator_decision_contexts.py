from datetime import date

from app.data_sources.news import NewsFetcher
from app.models.schemas import MarketSnapshot, MonthlyRevenue, ReportRequest, ValuationMetric
from app.services.entity_mapping import EntityMapper
from app.services.report_generator import ReportGenerator
from app.services.whitelist import SupplyChainWhitelist
from report_generator_factories import make_financial_metrics


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
