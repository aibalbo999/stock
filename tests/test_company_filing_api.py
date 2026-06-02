from __future__ import annotations

from contextlib import contextmanager
from datetime import date

from app.data_sources.company_filings import CompanyFilingFetcher
from app.services.company_filing_api import CompanyFilingApiService
from app.services.persistence import CompanyFilingRepository


def test_company_filing_api_service_persists_manual_document_to_rag_and_db() -> None:
    stored = {}

    class FakeVectorStore:
        def upsert_documents(self, documents):
            stored["rag_document_id"] = documents[0].id

    class FakeRepository:
        def __init__(self, session: object) -> None:
            stored["session"] = session

        def upsert_document(self, document):
            stored["document_id"] = document.id

        @staticmethod
        def to_news_document(document):
            return CompanyFilingRepository.to_news_document(document)

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = CompanyFilingApiService(
        session_scope_factory=fake_session_scope,
        company_filing_repository_cls=FakeRepository,
        vector_store_cls=FakeVectorStore,
    )

    result = service.ingest_manual(
        ticker="2330",
        company_name="台積電",
        document_type="annual_report",
        title="台積電 2026 年報",
        text="台積電 年報揭露 AI/HPC 需求與風險因素。" * 8,
        publisher="公開資訊觀測站",
        published_at=date(2026, 5, 1),
        url="https://mops.twse.com.tw/server-java/t57sb01?co_id=2330",
    )

    assert result["ticker"] == "2330"
    assert result["document_type"] == "annual_report"
    assert result["source_tier"] == "official_disclosure"
    assert result["quality_score"] >= 70
    assert stored["document_id"] == result["document_id"]
    assert stored["rag_document_id"].startswith("filing-")
    assert stored["session"] == "session"


def test_company_filing_api_service_lists_allowed_documents_with_quality() -> None:
    captured = {}
    document = CompanyFilingFetcher.from_manual_text(
        ticker="2330",
        company_name="台積電",
        document_type="annual_report",
        title="台積電 2026 年報",
        text="台積電 年報揭露 AI/HPC 需求與風險因素。" * 8,
        publisher="台積電 IR",
        published_at=date(2026, 5, 1),
        url="https://investor.tsmc.com/annual-report.pdf",
    )

    class FakeWhitelist:
        def allowed_tickers(self):
            return {"2330", "2382"}

    class FakeMapper:
        whitelist = FakeWhitelist()

        def filter_allowed_tickers(self, tickers):
            captured["requested_tickers"] = tickers
            return [ticker for ticker in tickers if ticker == "2330"]

    class FakeRepository:
        def __init__(self, session: object) -> None:
            captured["session"] = session

        def latest_by_tickers(self, allowed, limit_per_ticker):
            captured["allowed"] = allowed
            captured["limit_per_ticker"] = limit_per_ticker
            return [document]

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = CompanyFilingApiService(
        session_scope_factory=fake_session_scope,
        company_filing_repository_cls=FakeRepository,
        entity_mapper_cls=FakeMapper,
    )

    items = service.list_company_filings("2330,9999", limit_per_ticker=99)

    assert captured["requested_tickers"] == ["2330", "9999"]
    assert captured["allowed"] == ["2330"]
    assert captured["limit_per_ticker"] == 20
    assert items == [
        {
            "id": document.id,
            "ticker": "2330",
            "company_name": "台積電",
            "document_type": "annual_report",
            "title": "台積電 2026 年報",
            "publisher": "台積電 IR",
            "source_tier": "company_ir",
            "quality_score": 85,
            "published_at": "2026-05-01",
            "url": "https://investor.tsmc.com/annual-report.pdf",
        }
    ]
