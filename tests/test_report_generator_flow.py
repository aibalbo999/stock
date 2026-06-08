from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.data_sources.news import NewsFetcher
from app.models.schemas import ReportRequest
from app.services import (
    report_execution,
    report_generation_flow,
    report_markdown_sections,
    report_market_snapshots,
)
from app.services.entity_mapping import EntityMapper
from app.services.llm_client import LLMResult
from app.services.report_generator import (
    ReportExecutionError,
    ReportGenerator,
    report_execution_summary,
)
from app.services.whitelist import SupplyChainWhitelist


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
