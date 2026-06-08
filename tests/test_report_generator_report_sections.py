from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app.data_sources.news import NewsFetcher
from app.models.schemas import (
    EntityMatch,
    InvestorProfile,
    MarketSnapshot,
    MonthlyRevenue,
    ReportRequest,
    RiskFinding,
    RiskType,
    Source,
    ValuationMetric,
)
from app.services import (
    report_data_quality,
    report_notes,
    report_score_breakdown,
    report_source_coverage,
)
from app.services.entity_mapping import EntityMapper
from app.services.report_generator import ReportGenerator
from app.services.whitelist import SupplyChainWhitelist


def test_time_scope_note_distinguishes_current_history_and_scenario_scores() -> None:
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"], lookback_days=21)
    market_snapshots = [MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=100)]
    monthly_revenues = [
        MonthlyRevenue(
            ticker="2330",
            revenue_date=date(2026, 4, 10),
            revenue=1,
            revenue_year=2026,
            revenue_month=4,
        )
    ]
    valuation_metrics = [ValuationMetric(ticker="2330", trade_date=date(2026, 5, 20), pe_ratio=20)]
    note = ReportGenerator._render_time_scope_note(
        request,
        market_snapshots,
        monthly_revenues,
        valuation_metrics,
    )

    assert note == report_notes.render_time_scope_note(
        request,
        market_snapshots,
        monthly_revenues,
        valuation_metrics,
    )
    assert "「目前」指本報告生成時間" in note
    assert "近 21 天來源" in note
    assert "目前估值" in note
    assert "不是未來估值預測" in note
    assert "追價風險標籤" in note
    assert "不是預期報酬率、目標價或保證幅度" in note
    assert "不是未來走勢預測" in note


def test_report_note_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    report_sections_mixin_source = Path("app/services/report_generator_report_sections.py").read_text()
    notes_source = Path("app/services/report_notes.py").read_text()
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"], lookback_days=21)
    market_snapshots = [MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=100)]
    monthly_revenues = [
        MonthlyRevenue(
            ticker="2330",
            revenue_date=date(2026, 4, 10),
            revenue=1,
            revenue_year=2026,
            revenue_month=4,
        )
    ]
    valuation_metrics = [ValuationMetric(ticker="2330", trade_date=date(2026, 5, 20), pe_ratio=20)]

    assert "report_notes" not in generator_source
    assert "ReportGeneratorReportSectionsMixin" in generator_source
    assert "report_notes" in report_sections_mixin_source
    assert "def _render_time_scope_note(" in report_sections_mixin_source
    assert "def _render_decision_criteria_note(" in report_sections_mixin_source
    assert "def _render_time_scope_note(" not in generator_source
    assert "def render_time_scope_note(" in notes_source
    assert "def render_decision_criteria_note(" in notes_source
    assert "「目前」指本報告生成時間" not in generator_source
    assert "可小額分批研究" not in generator_source
    assert ReportGenerator._render_time_scope_note(
        request,
        market_snapshots,
        monthly_revenues,
        valuation_metrics,
    ) == report_notes.render_time_scope_note(
        request,
        market_snapshots,
        monthly_revenues,
        valuation_metrics,
    )


def test_decision_criteria_note_explains_financial_red_flags_and_actionable_rules() -> None:
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"], investor_profile=InvestorProfile.aggressive)
    note = ReportGenerator._render_decision_criteria_note(request)

    assert note == report_notes.render_decision_criteria_note(request)
    assert "目前情境降值分超過 12 分" in note
    assert "單純超過投資人門檻會先列觀察" in note
    assert "可小額分批研究" in note
    assert "財務/估值檢查" in note
    assert "財務紅旗存在" in note
    assert "追價風險標籤" in note


def test_score_breakdown_explains_factors_and_data_quality() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        close=2255.0,
        source="FinMind TaiwanStockPrice",
    )
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=349567000000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=18.5,
    )

    breakdown = generator._render_score_breakdown(["2330"], [], [], [snapshot], [revenue])

    assert "| 股票 | 目前情境升值分 | 目前情境降值分 | 主要加分 | 主要風險 | 資料提醒 |" in breakdown
    assert "| 2330 台積電 |" in breakdown
    assert "月營收年增率 18.50% +2" in breakdown
    assert "公司相關文本僅 0 筆" in breakdown


def test_score_breakdown_render_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    report_sections_mixin_source = Path("app/services/report_generator_report_sections.py").read_text()
    score_source = Path("app/services/report_score_breakdown.py").read_text()
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)

    assert "report_score_breakdown" not in generator_source
    assert "ReportGeneratorReportSectionsMixin" in generator_source
    assert "report_score_breakdown" in report_sections_mixin_source
    assert "def _render_score_breakdown(" in report_sections_mixin_source
    assert "def _render_score_breakdown(" not in generator_source
    assert "def render_score_breakdown(" in score_source
    assert "estimate_potential(" in score_source
    assert "此段拆解研究分級來源" not in generator_source
    assert generator._render_score_breakdown([], [], [], []) == report_score_breakdown.render_score_breakdown(
        tickers=[],
        documents=[],
        findings=[],
        market_snapshots=[],
        companies=generator.whitelist.companies(),
        related_documents_resolver=generator._related_documents,
        related_findings_resolver=generator._related_findings,
    )


def test_data_quality_section_explains_complete_and_missing_layers() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 需求成長",
            text="台積電 CoWoS 需求成長。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 先進封裝擴產",
            text="台積電 先進封裝擴產受惠 AI 需求。",
            publisher="測試新聞",
            published_at=date(2026, 5, 21),
        ),
    ]
    findings = [
        RiskFinding(
            risk_type=RiskType.short_term_volatility,
            topic="需求成長",
            evidence="台積電 CoWoS 需求成長。",
            source=Source(title="台積電 CoWoS 需求成長", publisher="測試新聞", published_at=date(2026, 5, 20)),
            related_companies=[
                EntityMatch(
                    ticker="2330",
                    name="台積電",
                    segment_id="foundry",
                    segment_name="晶圓代工",
                    matched_alias="台積電",
                )
            ],
        )
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

    section = generator._render_data_quality(
        ["2330", "2382"],
        documents,
        findings,
        [snapshot],
        [revenue],
    )

    assert "2330 台積電" in section
    assert "近況訊號" in section
    assert "完整，可進入二次篩選" in section
    assert "2382 廣達" in section
    assert "不足：公司文本不足、缺主題歸因、缺股價、缺月營收" in section
    assert "完整 1 檔、部分可用 0 檔、資料不足 1 檔" in section


def test_data_quality_render_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    report_sections_mixin_source = Path("app/services/report_generator_report_sections.py").read_text()
    data_quality_source = Path("app/services/report_data_quality.py").read_text()
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)

    assert "report_data_quality" not in generator_source
    assert "ReportGeneratorReportSectionsMixin" in generator_source
    assert "report_data_quality" in report_sections_mixin_source
    assert "def _render_data_quality(" in report_sections_mixin_source
    assert "def _render_data_quality(" not in generator_source
    assert "def render_data_quality(" in data_quality_source
    assert "data_quality_grade(" in data_quality_source
    assert "本段檢查每檔股票是否同時具備" not in generator_source
    assert generator._render_data_quality([], [], [], []) == report_data_quality.render_data_quality(
        tickers=[],
        documents=[],
        findings=[],
        market_snapshots=[],
        companies=generator.whitelist.companies(),
        related_documents_resolver=generator._related_documents,
        related_findings_resolver=generator._related_findings,
        company_filing_missing_resolver=generator._company_filing_missing,
    )


def test_source_coverage_summarizes_international_sources() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    documents = [
        NewsFetcher.from_manual_text(
            title="NVIDIA AI server supply chain Taiwan ODM",
            text="NVIDIA AI server supply chain mentions Quanta.",
            publisher="NVIDIA Blog",
            published_at=date(2026, 5, 24),
        ),
        NewsFetcher.from_manual_text(
            title="廣達 AI 伺服器出貨成長",
            text="廣達 AI 伺服器出貨成長。",
            publisher="測試新聞",
            published_at=date(2026, 5, 23),
        ),
    ]

    section = generator._render_source_coverage(
        ReportRequest(topic="AI 產業鏈", tickers=["2382"], evidence_limit=120),
        ["2382"],
        documents,
    )

    assert "國際來源 | 1 筆" in section
    assert "摘要使用證據上限 | 120 筆" in section
    assert "可追溯證據池總量 | 2 筆" in section
    assert "報告證據上限" not in section
    assert "實際納入證據" not in section
    assert "### 個股來源覆蓋" in section
    assert "| 2382 廣達 | 2 | 1 | 2026-05-24 | 2026-05-24 NVIDIA Blog" in section


def test_source_coverage_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    report_sections_mixin_source = Path("app/services/report_generator_report_sections.py").read_text()
    document_mixin_source = Path("app/services/report_generator_document.py").read_text()
    coverage_source = Path("app/services/report_source_coverage.py").read_text()
    document = NewsFetcher.from_manual_text(
        title="NVIDIA AI server supply chain",
        text="NVIDIA supply chain.",
        publisher="NVIDIA Blog",
        published_at=date(2026, 5, 24),
    )

    assert "report_source_coverage" not in generator_source
    assert "ReportGeneratorReportSectionsMixin" in generator_source
    assert "report_source_coverage" in report_sections_mixin_source
    assert "def _render_source_coverage(" in report_sections_mixin_source
    assert "def _render_source_coverage(" not in generator_source
    assert "def _is_international_source(" in document_mixin_source
    assert "def render_source_coverage(" in coverage_source
    assert "def is_international_source(" in coverage_source
    assert "def latest_source_date_label(" in coverage_source
    assert "本段說明本次可追溯證據池" not in generator_source
    assert ReportGenerator._is_international_source(document) == report_source_coverage.is_international_source(
        document
    )


def test_source_coverage_defensively_excludes_forum_documents() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SimpleNamespace(companies=lambda: [SimpleNamespace(ticker="1504", name="東元")])
    generator.mapper = EntityMapper(generator.whitelist)
    generator._document_match_cache = {}
    generator._related_documents = lambda _ticker, documents: documents
    request = ReportRequest(topic="機器人 產業鏈", tickers=["1504"])
    forum = NewsFetcher.from_manual_text(
        title="1504 東元 - 一堆看新聞做股票-股市爆料同學會",
        text="東元 機器人 散戶閒聊。",
        publisher="CMoney",
        published_at=date(2026, 5, 26),
    )
    formal = NewsFetcher.from_manual_text(
        title="東元受邀參加法人說明會",
        text="1504 東元 機電整合與智慧能源業務說明。",
        publisher="富聯網",
        published_at=date(2026, 5, 25),
    )

    coverage = generator._render_source_coverage(request, ["1504"], [forum, formal])

    assert "1504 東元" in coverage
    assert "股市爆料同學會" not in coverage
    assert "2026-05-25 富聯網" in coverage
