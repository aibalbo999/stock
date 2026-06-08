from datetime import date
from pathlib import Path

from app.data_sources.news import NewsFetcher
from app.services.report_generator import ReportGenerator
from app.services.report_prompt_builder import build_report_prompt, format_evidence_digest, format_llm_evidence


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
