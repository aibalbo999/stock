from types import SimpleNamespace
import sys

from app.core.config import get_settings
from app.data_sources.company_filings import (
    PDF_IMPORT_NO_TEXT_MESSAGE,
    extract_pdf_text,
)


def test_company_filing_pdf_text_extraction(monkeypatch) -> None:
    import pypdf

    class FakePage:
        def __init__(self, text: str) -> None:
            self.text = text

        def extract_text(self) -> str:
            return self.text

    monkeypatch.setattr(
        pypdf,
        "PdfReader",
        lambda _content: SimpleNamespace(
            pages=[
                FakePage("台積電 2026 年報"),
                FakePage("AI/HPC 需求與風險因素"),
            ]
        ),
    )

    assert "台積電 2026 年報" in extract_pdf_text(b"%PDF fake")


def test_company_filing_pdf_parser_extracts_tables_with_pdfplumber(monkeypatch) -> None:
    class FakePdfPage:
        def extract_text(self) -> str:
            return "台積電 2026 年報"

        def extract_tables(self):
            return [[["年度", "營收"], ["2026", "AI/HPC 需求成長"]]]

    class FakePdf:
        pages = [FakePdfPage()]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

    fake_pdfplumber = SimpleNamespace(open=lambda _content: FakePdf())
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)
    monkeypatch.setenv("COMPANY_FILING_PDF_PARSER", "pdfplumber")
    monkeypatch.setenv("COMPANY_FILING_PDF_EXTRACT_TABLES", "true")
    get_settings.cache_clear()
    try:
        text = extract_pdf_text(b"%PDF fake")
    finally:
        get_settings.cache_clear()

    assert "台積電 2026 年報" in text
    assert "[PDF 解析資訊] parser=pdfplumber; mode=configured; extract_tables=true" in text
    assert "[PDF 表格抽取 p.1 #1]" in text
    assert "表格尺寸：2 列 x 2 欄" in text
    assert "年度 | 營收" in text
    assert "2026 | AI/HPC 需求成長" in text


def test_company_filing_pdf_parser_extracts_unstructured_tables_with_provenance(
    monkeypatch,
) -> None:
    calls = {}

    class FakeTableElement:
        category = "Table"
        metadata = SimpleNamespace(
            page_number=3,
            text_as_html=(
                "<table>"
                "<tr><th>年度</th><th>營收</th></tr>"
                "<tr><td>2026</td><td>AI/HPC 成長</td></tr>"
                "</table>"
            ),
        )

        def __str__(self) -> str:
            return "fallback table text"

    def fake_partition_pdf(**kwargs):
        calls["kwargs"] = kwargs
        return [FakeTableElement()]

    monkeypatch.setitem(
        sys.modules,
        "unstructured.partition.pdf",
        SimpleNamespace(partition_pdf=fake_partition_pdf),
    )
    monkeypatch.setenv("COMPANY_FILING_PDF_PARSER", "unstructured")
    monkeypatch.setenv("COMPANY_FILING_PDF_EXTRACT_TABLES", "true")
    get_settings.cache_clear()
    try:
        text = extract_pdf_text(b"%PDF fake")
    finally:
        get_settings.cache_clear()

    assert calls["kwargs"]["infer_table_structure"] is True
    assert "[PDF 解析資訊] parser=unstructured; mode=configured; extract_tables=true" in text
    assert "[PDF 表格抽取 p.3 #1]" in text
    assert "年度 | 營收" in text
    assert "2026 | AI/HPC 成長" in text


def test_company_filing_pdf_parser_unstructured_respects_table_toggle(monkeypatch) -> None:
    calls = {}

    class FakeTableElement:
        category = "Table"
        metadata = SimpleNamespace(
            page_number=1,
            text_as_html="<table><tr><td>年度</td><td>營收</td></tr></table>",
        )

        def __str__(self) -> str:
            return "年度 營收 2026 成長"

    def fake_partition_pdf(**kwargs):
        calls["kwargs"] = kwargs
        return [FakeTableElement()]

    monkeypatch.setitem(
        sys.modules,
        "unstructured.partition.pdf",
        SimpleNamespace(partition_pdf=fake_partition_pdf),
    )
    monkeypatch.setenv("COMPANY_FILING_PDF_PARSER", "unstructured")
    monkeypatch.setenv("COMPANY_FILING_PDF_EXTRACT_TABLES", "false")
    get_settings.cache_clear()
    try:
        text = extract_pdf_text(b"%PDF fake")
    finally:
        get_settings.cache_clear()

    assert calls["kwargs"]["infer_table_structure"] is False
    assert "[PDF 解析資訊] parser=unstructured; mode=configured; extract_tables=false" in text
    assert "[PDF 表格抽取" not in text
    assert "年度 營收 2026 成長" in text


def test_company_filing_pdf_parser_extracts_text_with_pymupdf(monkeypatch) -> None:
    class FakePage:
        def __init__(self, text: str) -> None:
            self.text = text

        def get_text(self, mode: str) -> str:
            assert mode == "text"
            return self.text

    class FakeDocument:
        def __init__(self) -> None:
            self.closed = False
            self.pages = [
                FakePage("台積電 2026 法說會"),
                FakePage("AI 伺服器與 CoWoS 需求"),
            ]

        def __iter__(self):
            return iter(self.pages)

        def close(self) -> None:
            self.closed = True

    captured = {}

    def fake_open(**kwargs):
        captured["kwargs"] = kwargs
        captured["document"] = FakeDocument()
        return captured["document"]

    monkeypatch.setitem(sys.modules, "fitz", SimpleNamespace(open=fake_open))
    monkeypatch.setenv("COMPANY_FILING_PDF_PARSER", "pymupdf")
    get_settings.cache_clear()
    try:
        text = extract_pdf_text(b"%PDF fake")
    finally:
        get_settings.cache_clear()
        sys.modules.pop("fitz", None)

    assert captured["kwargs"] == {"stream": b"%PDF fake", "filetype": "pdf"}
    assert captured["document"].closed is True
    assert "[PDF 解析資訊] parser=pymupdf; mode=configured; extract_tables=true" in text
    assert "台積電 2026 法說會" in text
    assert "AI 伺服器與 CoWoS 需求" in text


def test_company_filing_pdf_without_text_has_actionable_error(monkeypatch) -> None:
    import pypdf

    class BlankPage:
        def extract_text(self) -> str:
            return ""

    monkeypatch.setattr(
        pypdf,
        "PdfReader",
        lambda _content: SimpleNamespace(pages=[BlankPage()]),
    )

    try:
        extract_pdf_text(b"%PDF fake")
    except ValueError as exc:
        assert PDF_IMPORT_NO_TEXT_MESSAGE in str(exc)
        assert "Visual RAG 後援失敗" in str(exc)
        assert "OCR" in str(exc)
        assert "文字版文件" in str(exc)
    else:
        raise AssertionError("PDF without extractable text should provide OCR guidance")


def test_company_filing_pdf_visual_rag_failure_preserves_fallback_reason(monkeypatch) -> None:
    def fake_extract_pypdf(_content: bytes) -> str:
        raise ValueError(PDF_IMPORT_NO_TEXT_MESSAGE)

    def fake_visual_extract(_content: bytes, *, reason: str):
        assert reason == PDF_IMPORT_NO_TEXT_MESSAGE
        raise ValueError("Visual RAG vision LLM API key 或本地 gateway 尚未配置。")

    monkeypatch.setenv("COMPANY_FILING_PDF_PARSER", "pypdf")
    monkeypatch.setenv("COMPANY_FILING_VISUAL_RAG_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_VISUAL_RAG_MODE", "fallback")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.data_sources.company_filing_parsers._extract_pdf_text_with_pypdf",
        fake_extract_pypdf,
    )
    monkeypatch.setattr("app.services.visual_rag.extract_visual_pdf_text", fake_visual_extract)
    try:
        extract_pdf_text(b"%PDF fake")
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("failed Visual RAG fallback should preserve diagnostics")
    finally:
        get_settings.cache_clear()

    assert PDF_IMPORT_NO_TEXT_MESSAGE in message
    assert "Visual RAG 後援失敗" in message
    assert "vision LLM API key" in message


def test_company_filing_pdf_without_text_can_use_visual_rag_fallback(monkeypatch) -> None:
    captured = {}

    def fake_extract_pypdf(_content: bytes) -> str:
        raise ValueError(PDF_IMPORT_NO_TEXT_MESSAGE)

    def fake_visual_extract(content: bytes, *, reason: str):
        captured["content"] = content
        captured["reason"] = reason
        return "[Visual RAG 解析資訊] mode=fallback\n營收 | 毛利率\n100 | 42%"

    monkeypatch.setenv("COMPANY_FILING_PDF_PARSER", "pypdf")
    monkeypatch.setenv("COMPANY_FILING_VISUAL_RAG_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_VISUAL_RAG_MODE", "fallback")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.data_sources.company_filing_parsers._extract_pdf_text_with_pypdf",
        fake_extract_pypdf,
    )
    monkeypatch.setattr("app.services.visual_rag.extract_visual_pdf_text", fake_visual_extract)
    try:
        text = extract_pdf_text(b"%PDF fake")
    finally:
        get_settings.cache_clear()

    assert captured["content"] == b"%PDF fake"
    assert captured["reason"] == PDF_IMPORT_NO_TEXT_MESSAGE
    assert "Visual RAG" in text
    assert "營收 | 毛利率" in text
