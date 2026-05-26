from datetime import date
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.data_sources.company_filings import (
    CompanyFilingFetcher,
    extract_pdf_text,
    filing_quality_score,
    filing_source_tier,
    infer_document_type,
    is_relevant_company_filing_result,
    validate_fetched_company_filing_document,
    validate_public_document_url,
)
from app.db.models import Base
from app.data_sources.news import NewsFetcher
from app.services.persistence import CompanyFilingRepository


def test_infer_company_filing_document_type() -> None:
    assert infer_document_type("台積電 2025 年報") == "annual_report"
    assert infer_document_type("Quanta investor presentation") == "investor_presentation"
    assert infer_document_type("公開說明書 募集資金用途") == "prospectus"


def test_company_filing_discovery_filters_generic_results() -> None:
    relevant = NewsFetcher.from_manual_text(
        title="2330 台積電 法說會重點",
        text="台積電 investor presentation 說明 AI/HPC 需求。",
    )
    generic = NewsFetcher.from_manual_text(
        title="台股財報公布時間整理",
        text="說明市場整體財報時間，沒有個別公司公開文件。",
    )

    assert is_relevant_company_filing_result(relevant, "2330", "台積電") is True
    assert is_relevant_company_filing_result(generic, "2330", "台積電") is False


def test_company_filing_quality_prefers_official_sources() -> None:
    official = NewsFetcher.from_manual_text(
        title="2330 台積電 年報",
        text="台積電 年報揭露 AI/HPC 需求與風險因素。",
        publisher="公開資訊觀測站",
        published_at=date(2026, 5, 1),
        url="https://mops.twse.com.tw/server-java/t57sb01?co_id=2330",
    )
    third_party = NewsFetcher.from_manual_text(
        title="2330 台積電 法說會懶人包",
        text="台積電 法說會摘要。",
        publisher="第三方部落格",
        published_at=date(2026, 5, 1),
        url="https://example.com/tsmc-summary",
    )

    assert filing_source_tier(official) == "official_disclosure"
    assert filing_quality_score(official, "2330", "台積電") >= 70
    assert filing_source_tier(third_party) == "third_party"
    assert filing_quality_score(third_party, "2330", "台積電") < 70


def test_company_filing_search_plan_targets_official_sources() -> None:
    plan = CompanyFilingFetcher.official_search_plan("2330", "台積電")

    assert any("site:mops.twse.com.tw" in query for query in plan["queries"])
    assert any("filetype:pdf" in query for query in plan["queries"])
    assert any(portal["name"] == "公開資訊觀測站" for portal in plan["official_portals"])
    assert len(plan["google_news_urls"]) == len(plan["queries"])


def test_company_filing_search_plan_can_target_document_type() -> None:
    plan = CompanyFilingFetcher.official_search_plan(
        "2330",
        "台積電",
        document_types=["annual_report"],
    )

    assert plan["document_types"] == ["annual_report"]
    assert all("年報" in query or "annual report" in query for query in plan["queries"])
    assert not any("法人說明會" in query for query in plan["queries"])


def test_company_filing_repository_roundtrip() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        document = CompanyFilingFetcher.from_manual_text(
            ticker="2330",
            company_name="台積電",
            document_type="annual_report",
            title="台積電 年報",
            text="年報揭露 AI/HPC 需求、資本支出與風險因素。",
            publisher="台積電 IR",
            published_at=date(2026, 5, 1),
            url="https://example.com/2330-annual-report.pdf",
        )
        repository = CompanyFilingRepository(session)
        repository.upsert_document(document)
        session.commit()

        stored = repository.latest_by_tickers(["2330"])
        stats = repository.stats_by_ticker("2330")
        news_document = CompanyFilingRepository.to_news_document(stored[0])

    assert stored[0].ticker == "2330"
    assert stats["rows"] == 1
    assert stats["document_types"] == ["annual_report"]
    assert news_document.id.startswith("filing-")
    assert "文件類型：annual_report" in news_document.text


def test_company_filing_fetch_url_document_uses_page_text(monkeypatch) -> None:
    async def fake_fetch_url_as_document(self, url, publisher=None):
        return NewsFetcher.from_manual_text(
            title="台積電 2026 年報",
            text="台積電 2026 年報揭露 AI/HPC 需求與風險因素。" * 8,
            publisher=publisher or "公開資訊觀測站",
            published_at=date(2026, 5, 1),
            url=url,
        )

    monkeypatch.setattr(CompanyFilingFetcher, "_fetch_url_as_document", fake_fetch_url_as_document)

    import asyncio

    document = asyncio.run(
        CompanyFilingFetcher().fetch_url_document(
            "https://mops.twse.com.tw/server-java/t57sb01?co_id=2330",
            ticker="2330",
            company_name="台積電",
            document_type="annual_report",
        )
    )

    assert document.ticker == "2330"
    assert document.document_type == "annual_report"
    assert document.title == "台積電 2026 年報"


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


def test_company_filing_url_validation_blocks_local_targets() -> None:
    validate_public_document_url("https://mops.twse.com.tw/server-java/t57sb01?co_id=2330")

    for url in [
        "file:///etc/passwd",
        "http://localhost:8000/internal",
        "http://127.0.0.1/internal",
        "http://192.168.1.10/report",
        "http://10.0.0.8/report",
        "http://example.local/report",
    ]:
        try:
            validate_public_document_url(url)
        except ValueError:
            continue
        raise AssertionError(f"unsafe URL should be rejected: {url}")


def test_fetched_company_filing_content_validation() -> None:
    valid = NewsFetcher.from_manual_text(
        title="台積電 2026 年報",
        text="台積電 2026 年報揭露 AI/HPC 需求、資本支出與風險因素。" * 8,
    )
    validate_fetched_company_filing_document(valid, "2330", "台積電", "annual_report")

    cases = [
        NewsFetcher.from_manual_text(title="短頁", text="台積電 年報"),
        NewsFetcher.from_manual_text(title="登入頁", text="請登入後查看文件內容。" * 20),
        NewsFetcher.from_manual_text(title="台積電 新聞", text="台積電 今日股價上漲，市場關注短線表現。" * 8),
    ]
    for document in cases:
        try:
            validate_fetched_company_filing_document(document, "2330", "台積電", "annual_report")
        except ValueError:
            continue
        raise AssertionError(f"invalid fetched document should be rejected: {document.title}")
