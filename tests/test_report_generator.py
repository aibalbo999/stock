from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

from app.data_sources.news import NewsFetcher
from app.models.schemas import (
    EntityMatch,
    FinancialMetric,
    InvestorProfile,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ReportRequest,
    RiskFinding,
    RiskType,
    Source,
    ValuationMetric,
)
from app.services.entity_mapping import EntityMapper
from app.services.leading_signals import LeadingSignal, LeadingSignalAnalyzer
from app.services.llm_analysis import LLMSupplementValidator
from app.services.llm_client import LLMResult
from app.services.report_financial_assessment import (
    financial_valuation_assessment,
    valuation_position_label,
)
from app.services.report_financial_narrative import financial_statement_summary
from app.services import (
    report_appendix,
    report_allocation,
    report_company_analysis,
    report_company_filing_checks,
    report_company_narrative,
    report_company_matrix,
    report_credibility_check,
    report_decision_narrative,
    report_decision_contexts,
    report_early_potential,
    report_execution,
    report_formatting,
    report_generation_flow,
    report_investment_thesis,
    report_leading_signal,
    report_markdown_sections,
    report_market_snapshots,
    report_monitoring_checklist,
    report_risk_overview,
    report_scope_sections,
)
from app.services.report_generator import (
    REPORT_READING_SORT_NOTE,
    ReportExecutionError,
    ReportGenerator,
    report_execution_summary,
)
from app.services.report_decision_rules import (
    current_price_label,
    recheck_trigger_text,
    risk_warning_reason,
    sort_decision_contexts,
)
from app.services.report_potential import data_quality_grade, estimate_potential
from app.services.report_prompt_builder import build_report_prompt, format_evidence_digest, format_llm_evidence
from app.services.report_source_references import representative_sources
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


def test_report_execution_summary_includes_retrieval_trace() -> None:
    generator = SimpleNamespace(
        last_evidence_documents=[],
        last_excluded_low_quality_documents=[],
        last_filtered_tickers=[],
        last_dropped_tickers=[],
        last_llm_result=LLMResult(
            text="ok",
            provider="litellm",
            model="gemini/gemini-test",
            observability={"latency_ms": 12.5, "total_token_estimate": 42},
        ),
        vector_store=SimpleNamespace(
            last_retrieval_trace={
                "strategy": "hybrid-vector-bm25-rerank",
                "candidates": [{"id": "doc-1", "final_score": 1.2}],
            }
        ),
    )

    summary = report_execution_summary(generator)

    assert summary["retrieval_trace"]["strategy"] == "hybrid-vector-bm25-rerank"
    assert summary["retrieval_trace"]["candidates"][0]["final_score"] == 1.2
    assert summary["llm"]["observability"]["latency_ms"] == 12.5
    assert summary["llm"]["observability"]["total_token_estimate"] == 42


def test_report_execution_summary_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    execution_source = Path("app/services/report_execution.py").read_text()

    assert report_execution_summary is report_execution.report_execution_summary
    assert "def report_execution_summary(" not in generator_source
    assert "def report_execution_summary(" in execution_source
    assert "summarize_llm_attempts(" in execution_source


def make_financial_metrics(
    ticker: str,
    revenues: list[float],
    net_incomes: list[float],
    liabilities: Optional[list[float]] = None,
    equities: Optional[list[float]] = None,
) -> list[FinancialMetric]:
    years = list(range(2022, 2022 + len(revenues)))
    liabilities = liabilities or [100.0 for _ in years]
    equities = equities or [200.0 for _ in years]
    metrics: list[FinancialMetric] = []
    for year, revenue, net_income, liability, equity in zip(years, revenues, net_incomes, liabilities, equities):
        report_date = date(year, 3, 31)
        metrics.extend(
            [
                FinancialMetric(
                    ticker=ticker,
                    report_date=report_date,
                    statement_type="income_statement",
                    metric="營業收入",
                    value=revenue,
                    source="test",
                ),
                FinancialMetric(
                    ticker=ticker,
                    report_date=report_date,
                    statement_type="income_statement",
                    metric="本期淨利",
                    value=net_income,
                    source="test",
                ),
                FinancialMetric(
                    ticker=ticker,
                    report_date=report_date,
                    statement_type="balance_sheet",
                    metric="負債總額",
                    value=liability,
                    source="test",
                ),
                FinancialMetric(
                    ticker=ticker,
                    report_date=report_date,
                    statement_type="balance_sheet",
                    metric="權益總額",
                    value=equity,
                    source="test",
                ),
            ]
        )
    return metrics


def test_llm_supplement_requires_source_timestamp() -> None:
    document = NewsFetcher.from_manual_text(
        title="CoWoS 產能滿載影響 AI 伺服器交期",
        text="台積電 CoWoS 產能滿載。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    assert (
        LLMSupplementValidator.render_markdown("沒有來源的補充分析", [document])
        == "LLM 補充分析未通過來源檢查；目前無足夠數據判斷。"
    )


def test_llm_supplement_accepts_timestamped_source() -> None:
    document = NewsFetcher.from_manual_text(
        title="CoWoS 產能滿載影響 AI 伺服器交期",
        text="台積電 CoWoS 產能滿載。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    text = """
    {
      "items": [
        {
          "claim": "瓶頸在 CoWoS。",
          "source_type": "news",
          "source_date": "2026-05-20",
          "source_publisher": "測試新聞",
          "source_title": "CoWoS 產能滿載影響 AI 伺服器交期",
          "source_id": ""
        }
      ]
    }
    """

    assert LLMSupplementValidator.render_markdown(text, [document]) == (
        "- 瓶頸在 CoWoS。 來源：2026-05-20 測試新聞 CoWoS 產能滿載影響 AI 伺服器交期"
    )


def test_llm_supplement_accepts_fuzzy_news_source_title() -> None:
    document = NewsFetcher.from_manual_text(
        title="CoWoS 產能滿載影響 AI 伺服器交期",
        text="台積電 CoWoS 產能滿載。",
        publisher="測試新聞股份有限公司",
        published_at=date(2026, 5, 20),
    )
    text = """
    {
      "items": [
        {
          "claim": "瓶頸仍集中在 CoWoS。",
          "source_type": "news",
          "source_date": "2026-05-20",
          "source_publisher": "測試新聞",
          "source_title": "CoWoS產能滿載影響交期",
          "source_id": ""
        }
      ]
    }
    """

    assert LLMSupplementValidator.render_markdown(text, [document]) == (
        "- 瓶頸仍集中在 CoWoS。 來源：2026-05-20 測試新聞 CoWoS產能滿載影響交期"
    )


def test_llm_supplement_accepts_market_source() -> None:
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        close=2255.0,
        source="FinMind TaiwanStockPrice",
    )
    text = """
    {
      "items": [
        {
          "claim": "2330 收盤價為 2255.0。",
          "source_type": "market",
          "source_date": "2026-05-22",
          "source_publisher": "FinMind TaiwanStockPrice",
          "source_title": "",
          "source_id": "2330"
        }
      ]
    }
    """

    assert LLMSupplementValidator.render_markdown(text, [], [snapshot]) == (
        "- 2330 收盤價為 2255.0。 來源：2026-05-22 FinMind TaiwanStockPrice 2330"
    )


def test_llm_supplement_rejects_news_claim_when_source_maps_to_another_company() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "2308",
                "name": "台達電",
                "segment": "電源與伺服",
                "status": "evidence_supported",
            },
            {
                "ticker": "2301",
                "name": "光寶科",
                "segment": "電源供應器",
                "status": "evidence_supported",
            },
        ]
    )
    mapper = EntityMapper(whitelist)
    document = NewsFetcher.from_manual_text(
        title="光寶科 AI 電源出貨升溫",
        text="光寶科受惠 AI 伺服器電源供應器需求增加。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )
    text = """
    {
      "items": [
        {
          "claim": "台達電 AI 電源出貨升溫。",
          "source_type": "news",
          "source_date": "2026-05-20",
          "source_publisher": "測試新聞",
          "source_title": "光寶科 AI 電源出貨升溫",
          "source_id": "2308"
        }
      ]
    }
    """

    rendered = LLMSupplementValidator.render_markdown(
        text,
        [document],
        news_ticker_resolver=lambda doc: [match.ticker for match in mapper.match_document(doc)],
        claim_ticker_resolver=lambda claim: [match.ticker for match in mapper.match_text(claim)],
    )

    assert rendered == "LLM 補充分析未通過來源檢查；目前無足夠數據判斷。"


def test_llm_supplement_accepts_news_claim_when_source_id_matches_company() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "2308",
                "name": "台達電",
                "segment": "電源與伺服",
                "status": "evidence_supported",
            }
        ]
    )
    mapper = EntityMapper(whitelist)
    document = NewsFetcher.from_manual_text(
        title="台達電 AI 電源出貨升溫",
        text="台達電受惠 AI 伺服器電源與伺服控制需求增加。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )
    text = """
    {
      "items": [
        {
          "claim": "台達電 AI 電源出貨升溫。",
          "source_type": "news",
          "source_date": "2026-05-20",
          "source_publisher": "測試新聞",
          "source_title": "台達電 AI 電源出貨升溫",
          "source_id": "2308"
        }
      ]
    }
    """

    rendered = LLMSupplementValidator.render_markdown(
        text,
        [document],
        news_ticker_resolver=lambda doc: [match.ticker for match in mapper.match_document(doc)],
        claim_ticker_resolver=lambda claim: [match.ticker for match in mapper.match_text(claim)],
    )

    assert rendered == (
        "- 台達電 AI 電源出貨升溫。 來源：2026-05-20 測試新聞 台達電 AI 電源出貨升溫"
    )


def test_generate_keeps_last_evidence_documents_for_quality_gate() -> None:
    document = NewsFetcher.from_manual_text(
        title="台積電 CoWoS 產能滿載",
        text="台積電 CoWoS 產能滿載，AI 供應鏈交期拉長。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    class FakeRiskAnalyzer:
        def analyze_documents(self, documents):
            assert documents == [document]
            return []

    class FakeMapper:
        def filter_allowed_tickers(self, tickers):
            return tickers

    class FakeLLM:
        def generate_with_metadata(self, prompt):
            return object()

    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.last_evidence_documents = []
    generator.risk_analyzer = FakeRiskAnalyzer()
    generator.mapper = FakeMapper()
    generator.llm = FakeLLM()
    generator._latest_market_snapshots = lambda tickers: []
    generator._latest_monthly_revenues = lambda tickers: []
    generator._financial_metrics = lambda tickers: []
    generator._latest_valuations = lambda tickers: []
    generator._render_markdown = lambda *args, **kwargs: "# 測試報告"

    response = ReportGenerator.generate(
        generator,
        ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
        documents=[document],
    )

    assert response.markdown == "# 測試報告"
    assert generator.last_evidence_documents == [document]


def test_generate_blocks_report_integrity_failure_before_response() -> None:
    document = NewsFetcher.from_manual_text(
        title="台達電 AI 電源需求成長",
        text="2308 台達電 AI 電源需求成長。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    class FakeRiskAnalyzer:
        def analyze_documents(self, documents):
            assert documents == [document]
            return []

    class FakeMapper:
        def filter_allowed_tickers(self, tickers):
            return tickers

    class FakeLLM:
        def generate_with_metadata(self, prompt):
            return object()

    invalid_markdown = """
    # 機器人 產業鏈 自動分析報告

    ## 資金控管建議
    ### 首筆配置草案
    本輪首筆配置合計約 90,000 元；可投入上限 700,000 元。
    - 2308 台達電：首筆配置約 50,000 元；淨分 35。

    ### 可小額分批研究
    - 2308 台達電：可列小額分批研究。首筆約 50,000 元。
    - 1504 東元：可列小額分批研究。首筆約 40,000 元。
    """

    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.last_evidence_documents = []
    generator.risk_analyzer = FakeRiskAnalyzer()
    generator.mapper = FakeMapper()
    generator.llm = FakeLLM()
    generator._latest_market_snapshots = lambda tickers: []
    generator._latest_monthly_revenues = lambda tickers: []
    generator._financial_metrics = lambda tickers: []
    generator._latest_valuations = lambda tickers: []
    generator._render_markdown = lambda *args, **kwargs: invalid_markdown

    with pytest.raises(ReportExecutionError) as exc:
        ReportGenerator.generate(
            generator,
            ReportRequest(topic="機器人 產業鏈", tickers=["2308", "1504"]),
            documents=[document],
        )

    assert "首筆配置草案的合計金額與逐檔配置明細加總不一致" in str(exc.value)
    assert "可立即研究或可小額分批研究名單中的股票沒有出現在首筆配置草案" in str(exc.value)


def test_llm_evidence_digest_is_bounded_to_reduce_timeout_risk() -> None:
    documents = [
        NewsFetcher.from_manual_text(
            title=f"測試新聞 {index}",
            text=f"第 {index} 筆來源 " + ("AI 伺服器需求與供應鏈驗證。" * 80),
            publisher="測試新聞",
            published_at=date(2026, 5, 1),
        )
        for index in range(65)
    ]

    digest = ReportGenerator._format_llm_evidence(documents)
    helper_digest = format_llm_evidence(documents)

    assert "測試新聞 0" in digest
    assert "測試新聞 59" in digest
    assert "測試新聞 60" not in digest
    assert "其餘 5 筆來源保留於系統資料庫" in digest
    assert "AI 伺服器需求與供應鏈驗證。" * 20 not in digest
    assert helper_digest == digest


def test_llm_evidence_digest_includes_company_mapping_for_attribution() -> None:
    document = NewsFetcher.from_manual_text(
        title="台達電 AI 電源出貨升溫",
        text="台達電受惠 AI 伺服器電源需求增加。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    digest = ReportGenerator._format_llm_evidence(
        [document],
        ticker_label_resolver=lambda doc: ["2308 台達電"],
    )

    assert "source_date=2026-05-20" in digest
    assert "source_title=台達電 AI 電源出貨升溫" in digest
    assert "source_id=2308" in digest
    assert "公司對應=2308 台達電" in digest


def test_report_prompt_builder_keeps_graphrag_and_source_contract() -> None:
    document = NewsFetcher.from_manual_text(
        title="台達電 AI 電源出貨升溫",
        text="台達電受惠 AI 伺服器電源需求增加。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    prompt = build_report_prompt(
        whitelist_context="2308 台達電",
        graph_context="GraphRAG 路徑推理：2308 -> 2382",
        evidence_documents=[document],
        market_snapshots=[],
        ticker_label_resolver=lambda _doc: ["2308 台達電"],
    )

    assert "GraphRAG 路徑推理：2308 -> 2382" in prompt
    assert "source_title=台達電 AI 電源出貨升溫" in prompt
    assert "source_id=2308" in prompt
    assert "目前無市場資料快取" in prompt


def test_report_prompt_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    generation_flow_source = Path("app/services/report_generation_flow.py").read_text()
    prompt_builder_source = Path("app/services/report_prompt_builder.py").read_text()

    assert "report_generation_flow.generate_report(" in generator_source
    assert "report_prompt_builder.build_report_prompt(" in generation_flow_source
    assert "REPORT_PROMPT_TEMPLATE.format(" not in generator_source
    assert "def build_report_prompt(" in prompt_builder_source
    assert "def format_evidence_digest(" in prompt_builder_source
    assert "def format_llm_evidence(" in prompt_builder_source
    assert "doc.text[:500]" not in generator_source


def test_report_generation_flow_orchestrates_generate_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    generation_flow_source = Path("app/services/report_generation_flow.py").read_text()

    assert report_generation_flow.generate_report
    assert "def generate_report(" in generation_flow_source
    assert "filter_formal_evidence_documents(" in generation_flow_source
    assert "remove_low_quality_investor_forum_lines(" in generation_flow_source
    assert "generator.last_dropped_tickers" in generation_flow_source
    assert "generator.last_dropped_tickers" not in generator_source
    assert "filter_formal_evidence_documents(" not in generator_source


def test_evidence_digest_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    prompt_appendix_mixin_source = Path("app/services/report_generator_prompt_appendix.py").read_text()
    prompt_builder_source = Path("app/services/report_prompt_builder.py").read_text()
    document = NewsFetcher.from_manual_text(
        title="台積電 AI 需求成長",
        text="台積電 AI 伺服器需求成長。" * 40,
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    digest = ReportGenerator._format_evidence([document])

    assert "report_prompt_builder" not in generator_source
    assert "ReportGeneratorPromptAppendixMixin" in generator_source
    assert "format_evidence_digest" in prompt_appendix_mixin_source
    assert "def _format_evidence(" in prompt_appendix_mixin_source
    assert "def _format_evidence(" not in generator_source
    assert "doc.text[:500]" in prompt_builder_source
    assert digest == format_evidence_digest([document])
    assert "2026-05-20 測試新聞 台積電 AI 需求成長" in digest
    assert len(digest) < len(document.text) + 80


def test_report_market_snapshot_fetching_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    market_scope_mixin_source = Path("app/services/report_generator_market_scope.py").read_text()
    snapshot_source = Path("app/services/report_market_snapshots.py").read_text()
    generator = object.__new__(ReportGenerator)

    assert "report_market_snapshots" not in generator_source
    assert "ReportGeneratorMarketScopeMixin" in generator_source
    assert "report_market_snapshots" in market_scope_mixin_source
    assert "def _latest_market_snapshots(" in market_scope_mixin_source
    assert "def _leading_signals(" in market_scope_mixin_source
    assert "def _latest_market_snapshots(" not in generator_source
    assert "def latest_market_snapshots(" in snapshot_source
    assert "def leading_signals(" in snapshot_source
    assert "MarketRepository(" not in generator_source
    assert "LeadingSignalAnalyzer" not in generator_source
    assert generator._latest_market_snapshots([]) == report_market_snapshots.latest_market_snapshots(
        [],
        session_scope_func=lambda: None,
    )
    assert generator._leading_signals([], []) == report_market_snapshots.leading_signals(
        [],
        [],
        session_scope_func=lambda: None,
    )


def test_report_markdown_section_orchestration_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    section_source = Path("app/services/report_markdown_sections.py").read_text()

    assert "report_markdown_sections" in generator_source
    assert "def render_markdown(" in section_source
    assert "def build_sections(" in section_source
    assert "ReportSection(" in section_source
    assert "ReportMarkdownRenderer" in section_source
    assert "ReportSection(" not in generator_source
    assert "ReportMarkdownRenderer" not in generator_source
    assert report_markdown_sections.build_sections


def test_generate_fails_when_dynamic_candidates_are_not_loaded() -> None:
    document = NewsFetcher.from_manual_text(
        title="上銀 機器人線性滑軌",
        text="上銀機器人線性滑軌與滾珠螺桿需求升溫。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    class FakeRiskAnalyzer:
        def analyze_documents(self, documents):
            return []

    class FakeLLM:
        called = False

        def generate_with_metadata(self, prompt):
            self.called = True
            raise AssertionError("LLM should not be called when execution guard blocks the report")

    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    generator.risk_analyzer = FakeRiskAnalyzer()
    generator.llm = FakeLLM()
    generator.last_evidence_documents = []
    generator.last_llm_result = None
    generator.last_filtered_tickers = []
    generator.last_dropped_tickers = []

    try:
        ReportGenerator.generate(
            generator,
            ReportRequest(topic="機器人 產業鏈", tickers=["2049"]),
            documents=[document],
        )
    except ReportExecutionError as exc:
        assert "必須套用候選公司動態白名單" in str(exc)
    else:
        raise AssertionError("ReportExecutionError was not raised")

    assert generator.last_filtered_tickers == []
    assert generator.last_dropped_tickers == ["2049"]
    assert generator.llm.called is False


def test_generate_fails_when_any_requested_ticker_is_dropped() -> None:
    document = NewsFetcher.from_manual_text(
        title="AI 產業鏈",
        text="AI 伺服器與機器人供應鏈需求升溫。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    class FakeRiskAnalyzer:
        def analyze_documents(self, documents):
            return []

    class FakeLLM:
        called = False

        def generate_with_metadata(self, prompt):
            self.called = True
            raise AssertionError("LLM should not be called when one requested ticker is dropped")

    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    generator.risk_analyzer = FakeRiskAnalyzer()
    generator.llm = FakeLLM()
    generator.last_evidence_documents = []
    generator.last_llm_result = None
    generator.last_filtered_tickers = []
    generator.last_dropped_tickers = []

    try:
        ReportGenerator.generate(
            generator,
            ReportRequest(topic="AI 與機器人混合主題", tickers=["2330", "2049"]),
            documents=[document],
        )
    except ReportExecutionError as exc:
        assert "2049" in str(exc)
        assert "缺漏個股分析" in str(exc)
    else:
        raise AssertionError("ReportExecutionError was not raised")

    assert generator.last_filtered_tickers == ["2330"]
    assert generator.last_dropped_tickers == ["2049"]
    assert generator.llm.called is False


def test_generate_allows_discovered_tickers_when_dynamic_whitelist_is_loaded() -> None:
    document = NewsFetcher.from_manual_text(
        title="台達電 機器人伺服驅動",
        text="台達電機器人伺服驅動與控制器需求升溫。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "2308",
                "name": "台達電",
                "segment": "伺服驅動與控制系統",
                "status": "evidence_supported",
                "evidence_keywords": ["伺服", "控制器", "機器人"],
            }
        ]
    )

    class FakeRiskAnalyzer:
        def analyze_documents(self, documents):
            return []

    class FakeLLM:
        def generate_with_metadata(self, prompt):
            return type("Result", (), {"text": "{}", "fallback": True, "model": None, "key_index": None})()

    generator = object.__new__(ReportGenerator)
    generator.whitelist = whitelist
    generator.mapper = EntityMapper(generator.whitelist)
    generator.risk_analyzer = FakeRiskAnalyzer()
    generator.llm = FakeLLM()
    generator.last_evidence_documents = []
    generator.last_llm_result = None
    generator.last_filtered_tickers = []
    generator.last_dropped_tickers = []
    generator._latest_market_snapshots = lambda tickers: []
    generator._latest_monthly_revenues = lambda tickers: []
    generator._financial_metrics = lambda tickers: []
    generator._latest_valuations = lambda tickers: []
    generator._leading_signals = lambda tickers, valuations: {}
    generator._render_markdown = lambda *args, **kwargs: "# 測試報告"

    response = ReportGenerator.generate(
        generator,
        ReportRequest(topic="機器人 產業鏈", tickers=["2308"]),
        documents=[document],
    )

    assert response.markdown == "# 測試報告"
    assert generator.last_filtered_tickers == ["2308"]
    assert generator.last_dropped_tickers == []


def test_company_analysis_and_recommendations_do_not_overstate_market_only_data() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        close=2255.0,
        spread=25.0,
        trading_volume=26823133,
        source="FinMind TaiwanStockPrice",
    )

    company_analysis = generator._render_company_analysis(["2330"], [], [], [snapshot])
    direct_company_analysis = report_company_analysis.render_company_analysis_section(
        generator,
        ["2330"],
        [],
        [],
        [snapshot],
        reading_sort_note=REPORT_READING_SORT_NOTE,
    )
    recommendations = generator._render_investment_recommendations(
        ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
        ["2330"],
        [],
        [],
        [snapshot],
    )

    assert company_analysis == direct_company_analysis
    assert "### 2330 台積電" in company_analysis
    assert "### 個股速覽" in company_analysis
    assert "| 股票 | 產業位置 | 最新可取得收盤價 | 追價風險標籤 | 月營收 | 目前估值位置 | 財務信心 | 證據狀態 |" in company_analysis
    assert "| 2330 台積電 |" in company_analysis
    assert "#### 華爾街式完整分析框架" in company_analysis
    assert "商業模式與收入來源" in company_analysis
    assert "#### 已揭露年度財務檢查" in company_analysis
    assert "#### 競爭護城河" in company_analysis
    assert "#### 估值分析" in company_analysis
    assert "#### 未來成長假設" in company_analysis
    assert "#### 多空辯論" in company_analysis
    assert "#### 是否應該投資" in company_analysis
    assert "淨利趨勢：目前無足夠數據判斷" in company_analysis
    assert "P/E 與同業比較：目前無足夠數據判斷" in company_analysis
    assert "新聞/研究證據：目前無足夠數據判斷" in company_analysis
    assert "觀察 / 資料不足" in recommendations
    assert "缺少新聞、財報或法說證據" in recommendations


def test_company_analysis_overview_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    analysis_source = Path("app/services/report_company_analysis.py").read_text()

    assert "report_company_analysis" in generator_source
    assert "def overview_row(" in analysis_source
    assert "def render_company_analysis_section(" in analysis_source
    assert "def render_company_analysis(" in analysis_source
    assert "### 個股速覽" not in generator_source
    assert "未指定白名單個股" not in generator_source
    assert "市場資料：" not in generator_source
    assert "月營收：" not in generator_source
    assert "風險/機會證據" not in generator_source
    assert report_company_analysis.render_company_analysis([], [], "排序說明") == (
        "### 個股速覽\n"
        "排序說明\n\n"
        "| 股票 | 產業位置 | 最新可取得收盤價 | 追價風險標籤 | 月營收 | 目前估值位置 | 財務信心 | 證據狀態 |\n"
        "|---|---|---|---|---|---|---|---|\n\n"
        "### 個股細節"
    )


def test_company_analysis_detail_block_helpers_format_market_revenue_and_evidence() -> None:
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        close=1000.0,
        spread=25.0,
        trading_volume=12345,
        source="FinMind TaiwanStockPrice",
    )
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 30),
        revenue=410_725_118_000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=25.0,
        source="FinMind TaiwanStockMonthRevenue",
    )
    document = NewsFetcher.from_manual_text(
        title="台積電 AI 需求成長",
        text="台積電 AI 需求成長。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )
    findings = [
        make_finding("2330", "台積電", f"測試風險證據 {index}", RiskType.structural_bottleneck)
        for index in range(4)
    ]

    market_line = report_company_analysis.market_data_line(snapshot)
    revenue_line = report_company_analysis.monthly_revenue_line(revenue)
    finding_lines = report_company_analysis.evidence_lines([document], findings)

    assert "2026-05-22 收盤 1000.0" in market_line
    assert "成交量 12345" in market_line
    assert report_company_analysis.market_data_line(None) == "- 市場資料：目前無足夠數據判斷。"
    assert "2026-04 營收 410,725,118,000" in revenue_line
    assert "年增率 25.00%" in revenue_line
    assert report_company_analysis.monthly_revenue_line(None) == "- 月營收：目前無足夠數據判斷。"
    assert finding_lines[0].startswith("- 風險/機會證據：structural_bottleneck；測試風險證據 0")
    assert finding_lines[-1] == "- 其餘 1 筆證據已收斂於風險摘要與資料來源附錄。"
    assert report_company_analysis.evidence_lines([document], []) == [
        "- 新聞/研究證據：找到 1 筆相關文本，但未形成可歸因風險。"
    ]
    assert report_company_analysis.evidence_lines([], []) == ["- 新聞/研究證據：目前無足夠數據判斷。"]


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


def test_company_analysis_orders_rows_and_details_for_readability() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(topic="AI 產業鏈", tickers=["2382", "2330"])
    snapshots = [
        MarketSnapshot(ticker="2382", trade_date=date(2026, 5, 22), close=300.0),
        MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=1000.0),
    ]

    company_analysis = generator._render_company_analysis(
        ["2382", "2330"],
        [],
        [],
        snapshots,
        request=request,
    )

    assert "排序：先依判斷結果分組" in company_analysis
    assert company_analysis.index("| 2330 台積電 |") < company_analysis.index("| 2382 廣達 |")
    assert company_analysis.index("### 2330 台積電") < company_analysis.index("### 2382 廣達")


def test_complete_market_data_still_requires_company_filings_for_actionable_rating() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    generator._company_filing_missing = lambda ticker, documents: ["缺公司公開文件（年報）"]
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"], beginner_mode=False)
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=1000.0)
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 30),
        revenue=300_000_000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=20.0,
    )
    metrics = [
        FinancialMetric(
            ticker="2330",
            report_date=date(2025, 12, 31),
            statement_type="income_statement",
            metric="營業收入",
            value=1000.0,
            source="FinMind TaiwanStockFinancialStatements",
        )
    ]
    valuation = ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=18.0)
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 AI 需求成長",
            text="台積電 AI 需求成長，先進製程需求強勁。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 擴產",
            text="台積電 CoWoS 擴產帶動 AI 伺服器供應鏈。",
            publisher="測試新聞",
            published_at=date(2026, 5, 21),
        ),
    ]

    snapshot_markdown = generator._render_executive_snapshot(
        request,
        ["2330"],
        documents,
        [],
        [snapshot],
        [revenue],
        metrics,
        [valuation],
    )
    recommendations = generator._render_investment_recommendations(
        request,
        ["2330"],
        documents,
        [],
        [snapshot],
        [revenue],
        metrics,
        [valuation],
    )

    assert "| 2330 台積電 | 觀察 / 資料待補 | 2026-05-22 收盤 1000 | 觀察等待 | 待補 |" in snapshot_markdown
    assert "品質門檻最多允許研究約" in snapshot_markdown
    assert "本次實際配置以投資建議與資金控管為準" in snapshot_markdown
    assert "缺公司公開文件（年報）" in snapshot_markdown
    assert "觀察 / 資料待補" in recommendations
    assert "且資料層完整" not in recommendations


def test_company_analysis_uses_financial_and_valuation_data() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=2255.0)
    metrics = [
        FinancialMetric(
            ticker="2330",
            report_date=date(2022, 12, 31),
            statement_type="income_statement",
            metric="營業收入",
            value=1000,
            source="FinMind TaiwanStockFinancialStatements",
        ),
        FinancialMetric(
            ticker="2330",
            report_date=date(2026, 12, 31),
            statement_type="income_statement",
            metric="營業收入",
            value=1500,
            source="FinMind TaiwanStockFinancialStatements",
        ),
        FinancialMetric(
            ticker="2330",
            report_date=date(2026, 12, 31),
            statement_type="balance_sheet",
            metric="負債總計",
            value=400,
            source="FinMind TaiwanStockBalanceSheet",
        ),
        FinancialMetric(
            ticker="2330",
            report_date=date(2026, 12, 31),
            statement_type="balance_sheet",
            metric="權益總計",
            value=1000,
            source="FinMind TaiwanStockBalanceSheet",
        ),
    ]
    valuations = [
        ValuationMetric(
            ticker="2330",
            trade_date=date(2026, 5, 22),
            pe_ratio=24.5,
            pb_ratio=5.8,
            dividend_yield=1.6,
        ),
        ValuationMetric(
            ticker="2382",
            trade_date=date(2026, 5, 22),
            pe_ratio=12.5,
            pb_ratio=2.8,
            dividend_yield=4.0,
        )
    ]

    company_analysis = generator._render_company_analysis(
        ["2330", "2382"],
        [],
        [],
        [snapshot],
        [],
        metrics,
        valuations,
    )

    assert "2022 年度至 2026 年度營收成長 50.00%" in company_analysis
    assert "2026 年度負債權益比約 0.40 倍" in company_analysis
    assert "資料信心：低；目前估值位置：目前估值偏高。" in company_analysis
    assert "#### 公司基本介紹" in company_analysis
    assert "- 基本定位：2330 台積電，本報告歸類在「晶圓代工」。" in company_analysis
    assert "- 常見名稱/代號：TSMC、Taiwan Semiconductor、台灣積體電路" in company_analysis
    assert "| 2330 台積電 | 晶圓代工 | 2026-05-22 收盤 2255.0 | 等風險下降 | 缺 | 目前估值偏高 | 低 |" in company_analysis
    assert "P/E 24.50、P/B 5.80、殖利率 1.60%" in company_analysis
    assert "P/E 高於同業平均 18.50" in company_analysis
    assert "P/B 高於同業平均 4.30" in company_analysis


def test_company_basic_intro_uses_dynamic_candidate_context() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    analysis_source = Path("app/services/report_company_analysis.py").read_text()
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "2308",
                "name": "台達電",
                "segment": "伺服驅動與控制系統",
                "rationale": "電源、伺服驅動與控制器可支援機器人平台",
                "evidence_keywords": ["伺服驅動", "控制器", "機器人"],
                "status": "evidence_supported",
            }
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)
    document = NewsFetcher.from_manual_text(
        title="台達電 機器人伺服驅動",
        text="台達電 2308 機器人伺服驅動與控制器需求升溫。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    company_analysis = generator._render_company_analysis(
        ["2308"],
        [document],
        [],
        [],
        [],
        [],
        [],
    )

    assert "#### 公司基本介紹" in company_analysis
    assert "基本定位：2308 台達電，本報告歸類在「伺服驅動與控制系統」。電源、伺服驅動與控制器可支援機器人平台。" in company_analysis
    assert "本主題關聯關鍵字：伺服驅動、控制器、機器人" in company_analysis
    assert "另有 1 筆公司相關文本、1 個來源供交叉檢查" in company_analysis
    assert "def basic_intro(" in analysis_source
    assert "本主題關聯關鍵字" not in generator_source


def test_company_analysis_operation_conclusion_matches_investment_decision() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"], investor_profile=InvestorProfile.aggressive)
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=100)
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=1000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=35,
    )
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
    findings = [make_finding("2330", "台積電", "台積電 AI 需求成長", RiskType.opportunity_or_growth)]
    metrics = make_financial_metrics(
        "2330",
        revenues=[100, 90, 80, 70, 60],
        net_incomes=[10, 5, 1, -2, -5],
        liabilities=[250, 260, 270, 280, 300],
        equities=[100, 100, 100, 100, 100],
    )
    valuation = ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=80, pb_ratio=10)

    company_analysis = generator._render_company_analysis(
        ["2330"],
        documents,
        findings,
        [snapshot],
        [revenue],
        metrics,
        [valuation],
        request=request,
    )

    assert "本次操作結論：避開 / 降低曝險" in company_analysis
    assert "此結論沿用投資建議總表" in company_analysis
    assert "最終結論：持有" not in company_analysis


def test_company_analysis_uses_official_filings_to_reduce_generic_data_gaps() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    filing = NewsDocument(
        id="filing-demo",
        title="股東會年報",
        text="2330 台積電\n文件類型：annual_report\nAI 伺服器 CoWoS 先進製程 客戶 認證 產能",
        source=Source(title="股東會年報", publisher="公開資訊觀測站 MOPS", published_at=date(2026, 5, 21)),
    )
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 1),
        revenue=410_725_118_000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=25.0,
    )
    valuation = ValuationMetric(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        pe_ratio=24.5,
        pb_ratio=5.8,
    )

    company_analysis = generator._render_company_analysis(
        ["2330"],
        [filing],
        [],
        [],
        [revenue],
        [],
        [valuation],
    )

    assert "已納入 1 份官方/公司公開文件" in company_analysis
    assert "可用 P/E 24.50 作為相對估值交叉檢查" in company_analysis
    assert "月營收年增 25.00%" in company_analysis
    assert "硬體與供應鏈公司通常不是典型網路效應" in company_analysis


def test_company_comparison_matrix_summarizes_decision_valuation_and_confidence() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    generator._company_filing_missing = lambda ticker, documents: []
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"])
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
    valuations = [
        ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=30, pb_ratio=8),
        ValuationMetric(ticker="2382", trade_date=date(2026, 5, 22), pe_ratio=12, pb_ratio=3),
    ]
    documents = [
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
    ]
    findings = [
        make_finding(
            "2330",
            "台積電",
            "台積電 CoWoS 需求成長",
            RiskType.opportunity_or_growth,
        )
    ]

    matrix = generator._render_company_comparison_matrix(
        request,
        ["2330"],
        documents,
        findings,
        [snapshot],
        [revenue],
        metrics,
        valuations,
    )

    assert "個股比較矩陣" not in matrix
    assert "| 股票 | 判斷 | 最新可取得收盤價 | 追價風險標籤 | 目前情境升值分 | 目前情境降值分 | 目前估值位置 | 財務信心 | 核心提醒 |" in matrix
    assert "| 2330 台積電 | 觀察 / 等風險降低 |" in matrix
    assert "等風險下降" in matrix
    assert "估值偏高" in matrix
    assert "高" in matrix


def test_company_comparison_matrix_logic_lives_outside_generator() -> None:
    generator = object.__new__(ReportGenerator)
    request = ReportRequest(tickers=[])
    generator_source = Path("app/services/report_generator.py").read_text()
    decision_views_mixin_source = Path("app/services/report_generator_decision_views.py").read_text()
    matrix_source = Path("app/services/report_company_matrix.py").read_text()

    assert "report_company_matrix" not in generator_source
    assert "ReportGeneratorDecisionViewsMixin" in generator_source
    assert "report_company_matrix" in decision_views_mixin_source
    assert "def _render_company_comparison_matrix(" in decision_views_mixin_source
    assert "def _company_matrix_reminder(" in decision_views_mixin_source
    assert "def _render_company_comparison_matrix(" not in generator_source
    assert "def render_company_comparison_matrix(" in matrix_source
    assert "def company_matrix_reminder(" in matrix_source
    assert "這張表用來比較正式分析股票" not in generator_source
    assert generator._render_company_comparison_matrix(request, [], [], [], []) == (
        report_company_matrix.render_company_comparison_matrix([], {}, {}, "")
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


def test_representative_sources_dedupes_and_sorts_newest_first() -> None:
    older = NewsFetcher.from_manual_text(
        title="台積電 AI 需求成長",
        text="台積電 AI 需求成長。",
        publisher="測試新聞A",
        published_at=date(2026, 5, 20),
    )
    newer = NewsFetcher.from_manual_text(
        title="台積電 CoWoS 大單",
        text="台積電 CoWoS 大單。",
        publisher="測試新聞B",
        published_at=date(2026, 5, 21),
    )
    duplicate_newer = NewsFetcher.from_manual_text(
        title="台積電 CoWoS 大單",
        text="台積電 CoWoS 大單重複來源。",
        publisher="測試新聞B",
        published_at=date(2026, 5, 21),
    ).model_copy(
        update={
            "id": "duplicate-with-different-url",
            "source": Source(
                title="台積電 CoWoS 大單",
                url="https://example.com/duplicate",
                publisher="測試新聞B",
                published_at=date(2026, 5, 21),
            ),
        }
    )

    sources = ReportGenerator._representative_sources([older, newer, duplicate_newer])
    helper_sources = representative_sources([older, newer, duplicate_newer])

    assert sources.startswith("2026-05-21 測試新聞B《台積電 CoWoS 大單》")
    assert sources.count("台積電 CoWoS 大單") == 1
    assert "2026-05-20 測試新聞A《台積電 AI 需求成長》" in sources
    assert helper_sources == sources


def test_report_source_reference_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    references_source = Path("app/services/report_source_references.py").read_text()

    assert "from app.services.report_source_references import" in generator_source
    assert "def representative_sources(" in references_source
    assert "def ordered_source_documents(" in references_source
    assert "def source_reference_line(" in references_source
    assert "source_credibility_weight_for_document" not in generator_source


def test_early_potential_radar_prioritizes_low_attention_strengthening_signals() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"])
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=100)
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 1),
        revenue=100,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=35,
    )
    documents = [
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
    ]
    signal = LeadingSignal(
        ticker="2330",
        score=7,
        upside_bonus=7,
        downside_penalty=0,
        bullish_factors=["月營收年增 35.0%"],
    )

    radar = generator._render_early_potential_radar(
        request,
        ["2330"],
        documents,
        [],
        [snapshot],
        [revenue],
        {"2330": signal},
    )

    assert "早期線索分" in radar
    assert "報導較少" in radar
    assert "台積電" in radar
    assert "報導較少不是利多" in radar


def test_early_potential_profile_penalizes_crowded_ideas() -> None:
    documents = [
        NewsFetcher.from_manual_text(
            title=f"台積電 AI 新聞 {index}",
            text="台積電 AI 需求成長。",
            publisher=f"媒體{index}",
            published_at=date(2026, 5, 20),
        )
        for index in range(20)
    ]

    profile = ReportGenerator._early_potential_profile(documents, None, None, 30, 0)

    assert profile["attention_label"] == "截至目前大量報導"
    assert profile["early_potential_reason"] == "截至目前題材已被大量報導，較不像尚未被市場發現。"


def test_early_potential_profile_penalizes_high_turnover_names() -> None:
    snapshot = MarketSnapshot(
        ticker="3037",
        trade_date=date(2026, 5, 29),
        close=1055,
        trading_money=22_254_481_820,
        source="FinMind TaiwanStockPrice",
    )

    profile = ReportGenerator._early_potential_profile([], None, None, 30, 0, snapshot)

    assert profile["attention_label"] == "截至目前成交熱度高"
    assert "較不像尚未被市場注意的冷門線索" in profile["early_potential_reason"]


def test_early_potential_radar_uses_candidate_audit_evidence_counts() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "3037",
                "name": "欣興",
                "segment": "PCB",
                "rationale": "AI 伺服器載板",
                "evidence_keywords": ["AI 伺服器", "PCB"],
                "evidence_count": 13,
                "evidence_source_count": 9,
                "evidence_titles": [],
                "status": "evidence_supported",
                "validation_reason": "通過正式分析門檻。",
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)
    request = ReportRequest(topic="AI 產業鏈", tickers=["3037"])
    snapshot = MarketSnapshot(
        ticker="3037",
        trade_date=date(2026, 5, 22),
        close=180.0,
        source="FinMind TaiwanStockPrice",
    )
    revenue = MonthlyRevenue(
        ticker="3037",
        revenue_date=date(2026, 5, 1),
        revenue=100,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=35,
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="欣興 AI 伺服器載板需求",
            text="欣興 AI 伺服器 PCB 載板需求成長。",
            publisher="公司文本",
            published_at=date(2026, 5, 20),
        )
    ]
    signal = LeadingSignal(
        ticker="3037",
        score=7,
        upside_bonus=7,
        downside_penalty=0,
        bullish_factors=["月營收年增 35.0%"],
    )

    radar = generator._render_early_potential_radar(
        request,
        ["3037"],
        documents,
        [],
        [snapshot],
        [revenue],
        {"3037": signal},
    )

    assert "3037 欣興" not in radar
    assert "報導較少 |" not in radar
    assert "公司文本 1 筆 / 1 來源" not in radar


def test_early_potential_radar_excludes_avoid_decisions() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "4540",
                "name": "盟立",
                "segment": "自動化設備",
                "rationale": "機器人自動化",
                "evidence_keywords": ["機器人"],
                "status": "evidence_supported",
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)
    request = ReportRequest(topic="機器人 產業鏈", tickers=["4540"])
    snapshot = MarketSnapshot(
        ticker="4540",
        trade_date=date(2026, 5, 29),
        close=68.6,
        source="FinMind TaiwanStockPrice",
    )
    revenue = MonthlyRevenue(
        ticker="4540",
        revenue_date=date(2026, 5, 1),
        revenue=100,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=35,
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="盟立機器人自動化需求成長",
            text="盟立機器人自動化需求成長。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        )
    ]
    signal = LeadingSignal(
        ticker="4540",
        score=-6,
        upside_bonus=7,
        downside_penalty=25,
        bearish_factors=["20 日股價動能轉弱"],
    )

    radar = generator._render_early_potential_radar(
        request,
        ["4540"],
        documents,
        [],
        [snapshot],
        [revenue],
        {"4540": signal},
    )

    assert "4540 盟立" not in radar
    assert "已排除避開/降低曝險標的" in radar


def test_early_potential_radar_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    early_source = Path("app/services/report_early_potential.py").read_text()
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    document = NewsFetcher.from_manual_text(
        title="台積電 AI 需求",
        text="台積電 AI 需求。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    assert "report_early_potential" in generator_source
    assert "def render_early_potential_radar(" in early_source
    assert "def candidate_audit_evidence_counts(" in early_source
    assert "def publisher_count(" in early_source
    assert "本段專門找" not in generator_source
    assert generator._publisher_count([document]) == report_early_potential.publisher_count([document])
    assert generator._candidate_audit_evidence_counts() == report_early_potential.candidate_audit_evidence_counts(
        generator.whitelist.candidate_audit()
    )


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
        [FinancialMetric(ticker="2330", report_date=date(2026, 3, 31), statement_type="income_statement", metric="營業收入", value=1, source="test") for _ in range(40)],
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


def test_potential_scoring_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    potential_mixin_source = Path("app/services/report_generator_potential.py").read_text()
    potential_source = Path("app/services/report_potential.py").read_text()

    assert "report_potential" not in generator_source
    assert "ReportGeneratorPotentialMixin" in generator_source
    assert "report_potential" in potential_mixin_source
    assert "def _estimate_potential(" in potential_mixin_source
    assert "def _data_quality_grade(" in potential_mixin_source
    assert "def estimate_potential(" in potential_source
    assert "def data_quality_grade(" in potential_source
    assert "PotentialScoringEngine" not in generator_source
    assert "def _estimate_potential(" not in generator_source
    assert "def _data_quality_grade(" not in generator_source


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


def test_decision_context_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    context_source = Path("app/services/report_decision_contexts.py").read_text()

    assert "report_decision_contexts" in generator_source
    assert "def build_decision_contexts(" in context_source
    assert "def ordered_tickers_for_reading(" in context_source
    assert "snapshots = {snapshot.ticker" not in generator_source
    assert "peer_valuation_summary = generator._peer_valuation_summary" in context_source
    assert report_decision_contexts.build_decision_contexts


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


def test_monthly_revenue_check_and_estimate_use_yoy() -> None:
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

    estimate = ReportGenerator._estimate_potential([], [], snapshot, revenue)
    helper_estimate = estimate_potential([], [], snapshot, revenue)
    check = ReportGenerator._render_revenue_check(["2330"], [revenue])

    assert helper_estimate == estimate
    assert estimate["upside_pct"] > 10
    assert "月營收年增率 18.50%" in estimate["upside_reason"]
    assert ("月營收年增率 18.50%", 2) in estimate["upside_factors"]
    assert "月營收用來確認題材是否反映到公司基本面" in check
    assert "年增率 18.50%" in check


def test_estimate_potential_reads_document_body_for_risk_keywords() -> None:
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=100)
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 AI 需求",
            text="法人提醒毛利下滑與庫存風險仍需觀察。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 先進封裝",
            text="AI 需求成長，但產能不足可能延遲出貨。",
            publisher="測試新聞",
            published_at=date(2026, 5, 21),
        ),
    ]

    estimate = ReportGenerator._estimate_potential(documents, [], snapshot)

    assert estimate["downside_pct"] > 5
    assert any("負向字詞" in label for label, _score in estimate["downside_factors"])


def test_financial_red_flag_blocks_actionable_decision() -> None:
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=100)
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=1000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=30,
    )
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
    findings = [make_finding("2330", "台積電", "台積電 AI 需求成長", RiskType.opportunity_or_growth)]
    metrics = make_financial_metrics(
        "2330",
        revenues=[100, 90, 80, 70, 60],
        net_incomes=[10, 8, 4, 1, -5],
        liabilities=[200, 220, 240, 260, 300],
        equities=[100, 100, 100, 100, 100],
    )
    valuation = ValuationMetric(ticker="2330", trade_date=date(2026, 5, 22), pe_ratio=80, pb_ratio=10)

    estimate = ReportGenerator._estimate_potential(
        documents,
        findings,
        snapshot,
        revenue,
        None,
        metrics,
        valuation,
        {"pe_avg": 20, "pb_avg": 2, "count": 4},
    )
    quality = ReportGenerator._data_quality_grade(
        documents,
        findings,
        snapshot,
        revenue,
        metrics,
        valuation,
        True,
        None,
        [],
    )
    decision = ReportGenerator._decision_label(estimate, quality, findings, 12)
    reason = ReportGenerator._decision_reason(
        decision,
        estimate,
        quality,
        findings,
        documents,
        12,
        ReportRequest(topic="AI 產業鏈", tickers=["2330"], investor_profile=InvestorProfile.aggressive),
    )

    assert estimate["financial_red_flag"] is True
    assert decision == "避開 / 降低曝險"
    assert "財務/估值紅旗" in reason


def test_severe_annual_decline_gets_high_financial_risk_score() -> None:
    snapshot = MarketSnapshot(ticker="1303", trade_date=date(2026, 5, 22), close=40)
    revenue = MonthlyRevenue(
        ticker="1303",
        revenue_date=date(2026, 5, 10),
        revenue=10_000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=19.4,
    )
    metrics = []
    for year, sales, profit in [(2022, 100.0, 10.0), (2025, 59.7, 2.84)]:
        metrics.extend(
            [
                FinancialMetric(
                    ticker="1303",
                    report_date=date(year, 12, 31),
                    statement_type="income_statement",
                    metric="營業收入",
                    value=sales,
                    source="test",
                ),
                FinancialMetric(
                    ticker="1303",
                    report_date=date(year, 12, 31),
                    statement_type="income_statement",
                    metric="本期淨利",
                    value=profit,
                    source="test",
                ),
                FinancialMetric(
                    ticker="1303",
                    report_date=date(year, 12, 31),
                    statement_type="balance_sheet",
                    metric="負債總額",
                    value=100.0,
                    source="test",
                ),
                FinancialMetric(
                    ticker="1303",
                    report_date=date(year, 12, 31),
                    statement_type="balance_sheet",
                    metric="權益總額",
                    value=200.0,
                    source="test",
                ),
            ]
        )

    estimate = ReportGenerator._estimate_potential(
        [
            NewsFetcher.from_manual_text(
                title="南亞 工程塑膠需求觀察",
                text="南亞 工程塑膠需求觀察。",
                publisher="測試新聞A",
                published_at=date(2026, 5, 20),
            ),
            NewsFetcher.from_manual_text(
                title="南亞 電子材料受惠題材",
                text="南亞 電子材料受惠題材。",
                publisher="測試新聞B",
                published_at=date(2026, 5, 21),
            ),
        ],
        [],
        snapshot,
        revenue,
        None,
        metrics,
        None,
    )

    assert estimate["financial_assessment"]["risk_score"] >= 7
    assert estimate["downside_pct"] >= 13
    assert "2022-2025 年度營收下滑 40.3%" in estimate["downside_reason"]
    assert "2022-2025 年度淨利下滑 71.6%" in estimate["downside_reason"]


def test_appendix_lists_more_source_references_with_urls() -> None:
    generator = object.__new__(ReportGenerator)
    documents = [
        NewsFetcher.from_manual_text(
            title=f"source-{index:02d}",
            text="測試來源內容",
            publisher="測試來源",
            published_at=date(2026, 1, 1) + timedelta(days=index),
            url=f"https://example.com/{index}",
        )
        for index in range(85)
    ]

    appendix = generator._render_appendix(
        LLMResult(text="", fallback=True),
        documents,
        [],
    )

    assert "2026-03-26 測試來源《source-84》（https://example.com/84）" in appendix
    assert "其餘 5 筆來源已存入資料庫，本報告僅列前 80 筆" in appendix
    assert "source-00" not in appendix


def test_appendix_filters_sources_to_current_tickers_when_possible() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "1303",
                "name": "南亞",
                "segment": "工程塑膠 / 電子材料",
                "status": "evidence_supported",
                "evidence_keywords": ["工程塑膠", "電子材料"],
            }
        ]
    )
    generator = object.__new__(ReportGenerator)
    generator.whitelist = whitelist
    generator.mapper = EntityMapper(whitelist)
    generator._document_match_cache = {}
    right_company = NewsFetcher.from_manual_text(
        title="1303 南亞電子材料需求回升",
        text="南亞工程塑膠與電子材料訂單改善。",
        publisher="測試新聞A",
        published_at=date(2026, 5, 24),
    )
    confusing_company = NewsFetcher.from_manual_text(
        title="南亞科記憶體供給吃緊",
        text="南亞科 DRAM 產能吃緊，記憶體報價上揚。",
        publisher="測試新聞B",
        published_at=date(2026, 5, 25),
    )

    appendix = generator._render_appendix(
        LLMResult(text="", fallback=True),
        [confusing_company, right_company],
        [],
        tickers=["1303"],
    )

    assert "1303 南亞電子材料需求回升" in appendix
    assert "南亞科記憶體供給吃緊" not in appendix


def test_appendix_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    prompt_appendix_mixin_source = Path("app/services/report_generator_prompt_appendix.py").read_text()
    appendix_source = Path("app/services/report_appendix.py").read_text()
    result = LLMResult(text="fallback status", fallback=True)

    assert "report_appendix" not in generator_source
    assert "ReportGeneratorPromptAppendixMixin" in generator_source
    assert "report_appendix" in prompt_appendix_mixin_source
    assert "def _render_appendix(" in prompt_appendix_mixin_source
    assert "def _model_status(" in prompt_appendix_mixin_source
    assert "def _render_appendix(" not in generator_source
    assert "def render_appendix(" in appendix_source
    assert "def appendix_documents_for_tickers(" in appendix_source
    assert "def model_status(" in appendix_source
    assert "模型補充分析未啟用" not in generator_source
    assert "SOURCE_APPENDIX_LIMIT" not in generator_source
    assert ReportGenerator._model_status(result) == report_appendix.model_status(result)


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


def test_candidate_audit_report_keeps_excluded_company_reasons() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "2382",
                "name": "廣達",
                "segment": "系統組裝",
                "rationale": "",
                "evidence_keywords": ["AI 伺服器"],
                "evidence_count": 2,
                "evidence_source_count": 2,
                "evidence_titles": [],
                "evidence_sources": [
                    {
                        "title": "廣達 AI 伺服器訂單",
                        "publisher": "測試新聞",
                        "published_at": "2026-05-24",
                        "url": "https://example.com/quanta",
                    }
                ],
                "evidence_confidence_score": 92,
                "evidence_confidence_label": "高",
                "latest_evidence_date": "2026-05-24",
                "status": "evidence_supported",
                "validation_reason": "通過正式分析門檻：至少 2 篇公司主題證據。",
                "next_action": "納入正式分析。",
            },
            {
                "ticker": "3324",
                "name": "雙鴻",
                "segment": "散熱模組",
                "rationale": "",
                "evidence_keywords": ["液冷"],
                "evidence_count": 1,
                "evidence_source_count": 1,
                "evidence_titles": [],
                "status": "weak_evidence",
                "validation_reason": "弱證據：目前只有 1 篇、1 個來源。",
                "next_action": "補抓公司新聞、法說會、月營收與國際供應鏈資料後再驗證。",
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)

    markdown = generator._render_candidate_audit(["2382"])

    assert "| AI 初始候選 | 2 |" in markdown
    assert "| 正式分析 | 1 |" in markdown
    assert "3324 雙鴻" in markdown
    assert "弱證據觀察" in markdown
    assert "入選支持度只表示候選公司與主題的來源支持度" in markdown
    assert "分析可信度仍需另看風險/機會歸因" in markdown
    assert "| 股票 | 產業位置 | 狀態 | 證據 | 排除 / 升格原因 | 下一步 | 入選支持度 |" in markdown
    assert "補抓公司新聞" in markdown
    assert "候選公司代表來源" in markdown
    assert "廣達 AI 伺服器訂單" in markdown
    assert "測試新聞" in markdown
    assert "高 92，最新 2026-05-24" in markdown


def test_candidate_audit_fallback_uses_low_confidence_reason() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "3324",
                "name": "雙鴻",
                "segment": "散熱模組",
                "rationale": "",
                "evidence_keywords": ["液冷"],
                "evidence_count": 2,
                "evidence_source_count": 2,
                "evidence_titles": [],
                "evidence_confidence_score": 60,
                "evidence_confidence_label": "中",
                "status": "weak_evidence",
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)

    markdown = generator._render_candidate_audit([])

    assert "弱證據：篇數與來源數達標，但入選支持度只有 60 分" in markdown
    assert "補抓有日期、近期且不同發布者" in markdown
    assert "中 60" in markdown


def test_candidate_audit_marks_stale_candidate_sources() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "3059",
                "name": "華晶科",
                "segment": "3D 感測相機",
                "rationale": "",
                "evidence_keywords": ["3D 感測"],
                "evidence_count": 4,
                "evidence_source_count": 2,
                "evidence_titles": [],
                "evidence_confidence_score": 63,
                "evidence_confidence_label": "中",
                "latest_evidence_date": "2025-08-08",
                "status": "weak_evidence",
                "validation_reason": "弱證據：篇數與來源數達標。",
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)

    markdown = generator._render_candidate_audit([])

    assert "最新候選來源為 2025-08-08" in markdown
    assert "超過 180 天新鮮度門檻" in markdown
    assert "最新 2025-08-08（距今約" in markdown
    assert "超過 180 天）" in markdown
    assert "最近 180 天內官方公告" in markdown


def test_candidate_audit_representative_sources_are_newest_first() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "1815",
                "name": "富喬",
                "segment": "玻纖布",
                "evidence_keywords": ["AI"],
                "evidence_count": 4,
                "evidence_source_count": 3,
                "evidence_sources": [
                    {
                        "title": "股東會年報(股東會後修訂本)",
                        "publisher": "公開資訊觀測站 MOPS",
                        "published_at": "2025-08-26",
                        "url": "https://example.com/old1",
                    },
                    {
                        "title": "股東會年報(尚未適用永續揭露準則)",
                        "publisher": "公開資訊觀測站 MOPS",
                        "published_at": "2025-05-23",
                        "url": "https://example.com/old2",
                    },
                    {
                        "title": "玻纖布 AI 需求增",
                        "publisher": "UDN",
                        "published_at": "2026-03-25",
                        "url": "https://example.com/newer",
                    },
                ],
                "evidence_confidence_score": 92,
                "evidence_confidence_label": "高",
                "latest_evidence_date": "2026-03-25",
                "status": "evidence_supported",
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)

    markdown = generator._render_candidate_audit(["1815"])

    company_block = markdown[markdown.find("- 1815 富喬") :]
    assert company_block.find("玻纖布 AI 需求增") < company_block.find("股東會年報(股東會後修訂本)")
    assert "股東會年報(尚未適用永續揭露準則)" not in company_block[:300]


def test_candidate_audit_dedupes_repeated_revalidation_reason() -> None:
    repeated_reason = (
        "上一版通過正式分析門檻；"
        "本次補強重驗證未穩定重建既有正式證據，先保留上一版正式分析；"
        "本次補強重驗證未穩定重建既有正式證據，先保留上一版正式分析"
    )
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "3037",
                "name": "欣興",
                "segment": "PCB",
                "rationale": "",
                "evidence_keywords": ["AI 伺服器"],
                "evidence_count": 13,
                "evidence_source_count": 9,
                "evidence_titles": [],
                "status": "evidence_supported",
                "validation_reason": repeated_reason,
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)

    markdown = generator._render_candidate_audit(["3037"])

    assert markdown.count("本次補強重驗證未穩定重建既有正式證據") == 1


def test_candidate_audit_filters_unrelated_release_note_sources() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "5443",
                "name": "均豪",
                "segment": "半導體自動化",
                "rationale": "機械手臂與自動化設備",
                "evidence_keywords": ["自動化", "機械手臂"],
                "evidence_count": 1,
                "evidence_source_count": 1,
                "evidence_titles": ["May 21, 2026"],
                "evidence_sources": [
                    {
                        "title": "May 21, 2026",
                        "publisher": "Google Cloud Release Notes",
                        "published_at": "2026-05-21",
                        "url": "https://cloud.google.com/release-notes",
                    }
                ],
                "status": "weak_evidence",
                "validation_reason": "弱證據：目前只有 1 篇、1 個來源。",
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)

    markdown = generator._render_candidate_audit([])

    assert "Google Cloud Release Notes" not in markdown
    assert "| 5443 均豪 | 半導體自動化 | 弱證據觀察 | 0 篇 / 0 來源 |" in markdown


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


def test_final_screen_does_not_promote_weak_evidence_revenue_only_score() -> None:
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

    screen = generator._render_final_potential_screen(["2330"], [], [], [snapshot], [revenue])

    assert "目前證據的情境升值分約" in screen
    assert "資料品質不足" in screen
    assert "情境升值潛力約" not in screen


def test_final_screen_separates_high_upside_but_blocked_risk() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "1303",
                "name": "南亞",
                "segment": "塑化材料",
                "status": "evidence_supported",
                "evidence_keywords": ["工程塑膠"],
            }
        ]
    )
    generator.mapper = EntityMapper(generator.whitelist)
    generator._company_filing_missing = lambda ticker, documents: []
    request = ReportRequest(
        topic="機器人 產業鏈",
        tickers=["1303"],
        beginner_mode=False,
        investor_profile=InvestorProfile.aggressive,
    )
    snapshot = MarketSnapshot(ticker="1303", trade_date=date(2026, 5, 22), close=40)
    revenue = MonthlyRevenue(
        ticker="1303",
        revenue_date=date(2026, 5, 10),
        revenue=10_000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=19.4,
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="南亞 工程塑膠需求成長",
            text="南亞 工程塑膠需求成長。",
            publisher="測試新聞A",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="南亞 電子材料受惠",
            text="南亞 電子材料受惠題材。",
            publisher="測試新聞B",
            published_at=date(2026, 5, 21),
        ),
    ]
    metrics = []
    for year, sales, profit in [(2022, 100.0, 10.0), (2025, 59.7, 2.84)]:
        metrics.extend(
            [
                FinancialMetric(
                    ticker="1303",
                    report_date=date(year, 12, 31),
                    statement_type="income_statement",
                    metric="營業收入",
                    value=sales,
                    source="test",
                ),
                FinancialMetric(
                    ticker="1303",
                    report_date=date(year, 12, 31),
                    statement_type="income_statement",
                    metric="本期淨利",
                    value=profit,
                    source="test",
                ),
            ]
        )

    screen = generator._render_final_potential_screen(
        ["1303"],
        documents,
        [],
        [snapshot],
        [revenue],
        metrics,
        [ValuationMetric(ticker="1303", trade_date=date(2026, 5, 22), pb_ratio=1.2)],
        request=request,
    )

    assert "### 升值分高但風險壓過" in screen
    assert "1303 南亞：升值分約" in screen
    assert "最終判斷為「避開 / 降低曝險」" in screen
    assert "### 目前情境升值分較高" not in screen


def test_severe_financial_red_flags_cap_upside_score() -> None:
    documents = [
        NewsFetcher.from_manual_text(
            title=f"南電 ABF 載板 AI 需求受惠 {index}",
            text="南電 ABF 載板 AI 需求受惠，產能與訂單題材升溫。",
            publisher=f"測試新聞{index}",
            published_at=date(2026, 5, 20),
        )
        for index in range(6)
    ]
    snapshot = MarketSnapshot(ticker="8046", trade_date=date(2026, 5, 22), close=800)
    revenue = MonthlyRevenue(
        ticker="8046",
        revenue_date=date(2026, 5, 10),
        revenue=10_000,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=39.4,
    )
    metrics = []
    for year, sales, profit in [(2021, 100.0, 30.0), (2025, 75.6, 10.1)]:
        metrics.extend(
            [
                FinancialMetric(
                    ticker="8046",
                    report_date=date(year, 12, 31),
                    statement_type="income_statement",
                    metric="營業收入",
                    value=sales,
                    source="test",
                ),
                FinancialMetric(
                    ticker="8046",
                    report_date=date(year, 12, 31),
                    statement_type="income_statement",
                    metric="本期淨利",
                    value=profit,
                    source="test",
                ),
            ]
        )

    estimate = ReportGenerator._estimate_potential(
        documents,
        [make_finding("8046", "南電", "ABF 供需吃緊", RiskType.structural_bottleneck)],
        snapshot,
        revenue,
        financial_metrics=metrics,
    )

    assert estimate["upside_pct"] <= 20
    assert "基本面紅旗" in estimate["upside_reason"]
    assert "已將升值分" in estimate["upside_cap_note"]


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


def test_aggressive_profile_observes_high_upside_when_downside_exceeds_gate_only() -> None:
    estimate = {"upside_pct": 45, "downside_pct": 16}
    quality = {"grade": "supported", "missing": []}

    rating = ReportGenerator._decision_label(estimate, quality, [], 12)

    assert rating == "觀察 / 等風險降低"


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


def test_estimate_potential_does_not_call_zero_news_hits_a_positive_reason() -> None:
    snapshot = MarketSnapshot(ticker="2059", trade_date=date(2026, 5, 22), close=100)
    revenue = MonthlyRevenue(
        ticker="2059",
        revenue_date=date(2026, 4, 10),
        revenue=100,
        revenue_year=2026,
        revenue_month=4,
        yoy_pct=79.1,
    )
    document = NewsFetcher.from_manual_text(
        title="川湖 伺服器滑軌出貨",
        text="川湖 伺服器滑軌出貨。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    estimate = ReportGenerator._estimate_potential([document], [], snapshot, revenue)

    assert estimate["upside_pct"] > 10
    assert "新聞/RAG 本身未形成主要升值加分" in estimate["upside_reason"]
    assert "正向關鍵證據 0 項" not in estimate["upside_reason"]


def test_estimate_potential_explains_valuation_risk_without_zero_news_risk() -> None:
    snapshot = MarketSnapshot(ticker="2383", trade_date=date(2026, 5, 22), close=100)
    valuation = ValuationMetric(ticker="2383", trade_date=date(2026, 5, 22), pe_ratio=60, pb_ratio=10)

    estimate = ReportGenerator._estimate_potential(
        [],
        [],
        snapshot,
        None,
        None,
        [],
        valuation,
        {"pe_avg": 20, "pb_avg": 3},
    )

    assert estimate["downside_pct"] > 5
    assert "新聞/RAG 未偵測到主要負向或瓶頸證據" in estimate["downside_reason"]
    assert "負向/瓶頸證據 0 項" not in estimate["downside_reason"]


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


def test_structural_bottleneck_reason_names_specific_evidence() -> None:
    finding = make_finding(
        "2395",
        "研華",
        "產能吃緊造成交期延長",
        RiskType.structural_bottleneck,
    )
    estimate = {"upside_pct": 18, "downside_pct": 4}
    quality = {"grade": "supported", "missing": []}

    rating = ReportGenerator._decision_label(estimate, quality, [finding], 12)
    reason = ReportGenerator._decision_reason(
        rating,
        estimate,
        quality,
        [finding],
        [],
        12,
        ReportRequest(topic="機器人 產業鏈", tickers=["2395"]),
    )

    assert rating == "觀察 / 等風險降低"
    assert "瓶頸/限制證據：產能吃緊造成交期延長" in reason
    assert "存在結構性瓶頸證據" not in reason


def test_decision_reason_logic_lives_outside_generator() -> None:
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"])
    estimate = {"upside_pct": 18, "downside_pct": 4}
    quality = {"grade": "supported", "missing": []}
    generator_source = Path("app/services/report_generator.py").read_text()
    decision_risk_mixin_source = Path("app/services/report_generator_decision_risk.py").read_text()
    narrative_source = Path("app/services/report_decision_narrative.py").read_text()

    assert "report_decision_narrative" not in generator_source
    assert "ReportGeneratorDecisionRiskMixin" in generator_source
    assert "report_decision_narrative" in decision_risk_mixin_source
    assert "def _decision_reason(" in decision_risk_mixin_source
    assert "def _decision_reason(" not in generator_source
    assert "def decision_reason(" in narrative_source
    assert "def structural_bottleneck_reason(" in narrative_source
    assert "缺少可驗證市場資料" not in generator_source
    assert ReportGenerator._decision_reason(
        "可小額分批研究",
        estimate,
        quality,
        [],
        [],
        5,
        request,
    ) == report_decision_narrative.decision_reason(
        "可小額分批研究",
        estimate,
        quality,
        [],
        [],
        5,
        request,
    )


def test_risk_overview_filters_ai_infra_labels_for_robotics_companies() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    decision_risk_mixin_source = Path("app/services/report_generator_decision_risk.py").read_text()
    risk_source = Path("app/services/report_risk_overview.py").read_text()
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "1597",
                "name": "直得",
                "segment": "微型線性滑軌",
                "rationale": "微型線性滑軌可切入精密自動化與機器人",
                "evidence_keywords": ["微型線性滑軌", "機器人", "自動化"],
                "evidence_count": 2,
                "evidence_source_count": 2,
                "status": "evidence_supported",
            }
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)
    finding = RiskFinding(
        risk_type=RiskType.structural_bottleneck,
        topic="HBM, 良率, 先進封裝",
        evidence="直得微型線性滑軌良率仍需觀察。",
        source=Source(title="直得風險", publisher="測試新聞", published_at=date(2026, 5, 22)),
        related_companies=[
            EntityMatch(
                ticker="1597",
                name="直得",
                segment_id="robotics",
                segment_name="微型線性滑軌",
                matched_alias="直得",
            )
        ],
    )

    overview = generator._render_risk_overview([finding], ["1597"])

    assert "良率(1)" in overview
    assert "HBM" not in overview
    assert "先進封裝" not in overview
    assert generator._company_risk_summary([finding]) == report_risk_overview.company_risk_summary(
        [finding],
        whitelist=whitelist,
    )
    assert generator._company_risk_summary([]) == report_risk_overview.company_risk_summary([], whitelist=whitelist)
    assert "report_risk_overview" not in generator_source
    assert "ReportGeneratorDecisionRiskMixin" in generator_source
    assert "report_risk_overview" in decision_risk_mixin_source
    assert "def _render_risk_overview(" in decision_risk_mixin_source
    assert "def _render_risk_overview(" not in generator_source
    assert "def render_risk_overview(" in risk_source
    assert "def company_risk_summary(" in risk_source
    assert "AI_INFRA_RISK_TERMS" in risk_source
    assert "AI_INFRA_RISK_TERMS" not in generator_source
    assert "### 代表性證據" not in generator_source
    assert "未偵測到可歸因的重大風險" not in generator_source
    assert report_risk_overview.sanitize_risk_topic(
        "HBM, 良率, 先進封裝",
        ["1597"],
        whitelist=whitelist,
    ) == "良率"


def test_related_findings_logic_lives_outside_generator_and_dedupes() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    decision_risk_mixin_source = Path("app/services/report_generator_decision_risk.py").read_text()
    risk_source = Path("app/services/report_risk_overview.py").read_text()
    finding = make_finding(
        "2330",
        "台積電",
        "先進製程產能吃緊",
        RiskType.structural_bottleneck,
    )
    duplicate = make_finding(
        "2330",
        "台積電",
        "先進製程產能吃緊",
        RiskType.structural_bottleneck,
    )
    unrelated = make_finding(
        "2382",
        "廣達",
        "AI 伺服器出貨波動",
        RiskType.short_term_volatility,
    )
    findings = [finding, duplicate, unrelated]

    assert "def related_findings(" in risk_source
    assert "def _related_findings(" in decision_risk_mixin_source
    assert "def _related_findings(" not in generator_source
    assert "seen: set[tuple" not in generator_source
    assert ReportGenerator._related_findings("2330", findings) == report_risk_overview.related_findings(
        "2330",
        findings,
    )
    assert ReportGenerator._related_findings("2330", findings) == [finding]
    assert ReportGenerator._related_findings("2382", findings) == [unrelated]


def test_findings_summary_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    decision_risk_mixin_source = Path("app/services/report_generator_decision_risk.py").read_text()
    risk_source = Path("app/services/report_risk_overview.py").read_text()
    findings = [
        make_finding("2330", "台積電", "先進製程產能吃緊", RiskType.structural_bottleneck),
        make_finding("2382", "廣達", "AI 伺服器出貨短期波動", RiskType.short_term_volatility),
        make_finding("3324", "雙鴻", "液冷散熱滲透率提升", RiskType.opportunity_or_growth),
    ]

    assert "def findings_summary(" in risk_source
    assert "def _summary(" in decision_risk_mixin_source
    assert "def _summary(" not in generator_source
    assert "本次檢出" not in generator_source
    assert "目前檢索證據不足" not in generator_source
    assert ReportGenerator._summary([]) == report_risk_overview.findings_summary([])
    assert ReportGenerator._summary(findings) == report_risk_overview.findings_summary(findings)
    assert ReportGenerator._summary(findings) == "本次檢出 1 項結構性瓶頸、1 項短期波動、1 項機會/成長歸因。"


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
