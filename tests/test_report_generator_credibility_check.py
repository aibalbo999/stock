from datetime import date
from pathlib import Path

from app.data_sources.news import NewsFetcher
from app.models.schemas import MarketSnapshot, MonthlyRevenue, ReportRequest, RiskType
from app.services import report_credibility_check
from app.services.entity_mapping import EntityMapper
from app.services.report_generator import ReportGenerator
from app.services.whitelist import SupplyChainWhitelist
from report_generator_factories import make_finding


def test_credibility_check_summarizes_traceability_and_company_limits() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    credibility_source = Path("app/services/report_credibility_check.py").read_text()
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"], lookback_days=21)
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 需求成長",
            text="台積電 CoWoS 需求成長。",
            publisher="測試新聞A",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 先進封裝擴產受惠",
            text="台積電 先進封裝擴產受惠 AI 大單。",
            publisher="測試新聞B",
            published_at=date(2026, 5, 21),
        ),
    ]
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=2255.0)
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=349567000000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=18.5,
    )

    section = generator._render_credibility_check(
        request,
        ["2330"],
        documents,
        [make_finding("2330", "台積電", "台積電 CoWoS 需求成長。", RiskType.opportunity_or_growth)],
        [snapshot],
        [revenue],
    )

    assert "| 檢查項目 | 狀態 | 本次證據 | 對投資判斷的影響 |" in section
    assert "| 可追溯來源 | 可追溯 | 共 2 筆文本 |" in section
    assert "| 來源多樣性 | 偏少 | 2 個發布者 |" in section
    assert "### 個股可信度核對" in section
    assert "本段檢查正式報告的分析可信度" in section
    assert "| 全體來源時間戳 | 可判讀 | 2/2 筆 有日期；近 21 天 2/2 筆 |" in section
    assert "| 公司層級分析完整度 | 可用 | 高分析可信度 1 檔、中分析可信度 0 檔、低分析可信度 0 檔 |" in section
    assert "| 2330 台積電 | 高 | 2 筆 / 2 來源 | 1 筆 | 2026-05-21 |" in section
    assert "缺已揭露年度財報" in section
    assert "### 分析可信度判讀規則" in section
    assert "report_credibility_check" in generator_source
    assert "def render_credibility_check(" in credibility_source
    assert "def credibility_label(" in credibility_source
    assert "個股可信度核對" not in generator_source
    assert "分析可信度判讀規則" not in generator_source
    assert report_credibility_check.publisher_label(documents[0]) == "測試新聞A"
