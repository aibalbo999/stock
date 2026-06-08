from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from app.data_sources.news import NewsFetcher
from app.models.schemas import Source
from app.services import report_appendix
from app.services.entity_mapping import EntityMapper
from app.services.llm_client import LLMResult
from app.services.report_generator import ReportGenerator
from app.services.report_source_references import representative_sources
from app.services.whitelist import SupplyChainWhitelist


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
