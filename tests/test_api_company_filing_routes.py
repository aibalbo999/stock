from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.company_filing_routes import create_company_filing_router
from app.data_sources.company_filings import CompanyFilingFetcher
from app.services.company_filing_api import CompanyFilingApiService
from app.services.persistence import CompanyFilingRepository


def test_company_filing_router_delegates_manual_ingest_and_list() -> None:
    captured = {}

    class FakeCompanyFilingApi:
        def ingest_manual(self, **kwargs) -> dict:
            captured["manual"] = kwargs
            return {"document_id": "filing-2330", "ticker": kwargs["ticker"]}

        def list_company_filings(self, tickers: str, limit_per_ticker: int) -> list[dict]:
            captured["list"] = {"tickers": tickers, "limit_per_ticker": limit_per_ticker}
            return [{"id": "filing-2330"}]

    client = _client(FakeCompanyFilingApi())

    manual_response = client.post(
        "/company-filings/manual",
        json={
            "ticker": "2330",
            "company_name": "台積電",
            "document_type": "annual_report",
            "title": "台積電年報",
            "text": "台積電年報內容",
        },
    )
    list_response = client.get("/company-filings?tickers=2330&limit_per_ticker=7")

    assert manual_response.status_code == 200
    assert manual_response.json() == {"document_id": "filing-2330", "ticker": "2330"}
    assert captured["manual"]["company_name"] == "台積電"
    assert list_response.status_code == 200
    assert list_response.json() == [{"id": "filing-2330"}]
    assert captured["list"] == {"tickers": "2330", "limit_per_ticker": 7}


def test_company_filing_router_delegates_url_ingest_and_maps_validation_error() -> None:
    captured = {}

    class FakeCompanyFilingApi:
        async def ingest_from_url(self, **kwargs) -> dict:
            captured["url"] = kwargs
            if kwargs["url"].startswith("http://localhost"):
                raise ValueError("localhost is not allowed")
            return {"document_id": "filing-url", "ticker": kwargs["ticker"]}

    client = _client(FakeCompanyFilingApi())

    response = client.post(
        "/company-filings/from-url",
        json={
            "ticker": "2330",
            "company_name": "台積電",
            "document_type": "annual_report",
            "url": "https://mops.twse.com.tw/server-java/t57sb01?co_id=2330",
        },
    )
    rejected = client.post(
        "/company-filings/from-url",
        json={
            "ticker": "2330",
            "company_name": "台積電",
            "document_type": "annual_report",
            "url": "http://localhost/internal",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"document_id": "filing-url", "ticker": "2330"}
    assert captured["url"]["publisher"] is None
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == "localhost is not allowed"


def test_company_filing_router_delegates_fetch() -> None:
    captured = {}

    class FakeCompanyFilingApi:
        async def fetch_company_filings(self, tickers: list[str]) -> dict:
            captured["tickers"] = tickers
            return {"stored_count": 2}

    client = _client(FakeCompanyFilingApi())

    response = client.post("/company-filings/fetch", json={"tickers": ["2330", "2382"]})

    assert response.status_code == 200
    assert response.json() == {"stored_count": 2}
    assert captured == {"tickers": ["2330", "2382"]}


def test_manual_company_filing_endpoint_returns_quality() -> None:
    client, stored = _quality_client()

    response = client.post(
        "/company-filings/manual",
        json={
            "ticker": "2330",
            "company_name": "台積電",
            "document_type": "annual_report",
            "title": "台積電 年報",
            "text": "台積電 年報揭露 AI/HPC 需求與風險因素。",
            "publisher": "公開資訊觀測站",
            "published_at": "2026-05-01",
            "url": "https://mops.twse.com.tw/server-java/t57sb01?co_id=2330",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "2330"
    assert body["document_type"] == "annual_report"
    assert body["source_tier"] == "official_disclosure"
    assert body["quality_score"] >= 70
    assert stored["filing_id"] == body["document_id"]
    assert stored["rag_document_id"].startswith("filing-")


def test_company_filing_from_url_endpoint_returns_quality() -> None:
    class FakeFetcher(CompanyFilingFetcher):
        async def fetch_url_document(self, **kwargs):
            return CompanyFilingFetcher.from_manual_text(
                ticker=kwargs["ticker"],
                company_name=kwargs["company_name"],
                document_type=kwargs["document_type"],
                title="台積電 2026 年報",
                text="台積電 年報揭露 AI/HPC 需求與風險因素。" * 8,
                publisher="公開資訊觀測站",
                published_at=kwargs["published_at"],
                url=kwargs["url"],
            )

    client, stored = _quality_client(FakeFetcher)

    response = client.post(
        "/company-filings/from-url",
        json={
            "ticker": "2330",
            "company_name": "台積電",
            "document_type": "annual_report",
            "publisher": "公開資訊觀測站",
            "published_at": "2026-05-01",
            "url": "https://mops.twse.com.tw/server-java/t57sb01?co_id=2330",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "2330"
    assert body["source_tier"] == "official_disclosure"
    assert body["quality_score"] >= 70
    assert stored["filing_id"] == body["document_id"]
    assert stored["rag_document_id"].startswith("filing-")


def test_company_filing_from_url_rejects_localhost() -> None:
    client, _ = _quality_client()

    response = client.post(
        "/company-filings/from-url",
        json={
            "ticker": "2330",
            "company_name": "台積電",
            "document_type": "annual_report",
            "url": "http://localhost:8000/internal",
        },
    )

    assert response.status_code == 400
    assert "localhost" in response.json()["detail"]


def test_company_filing_from_url_returns_pdf_ocr_guidance() -> None:
    class FakeFetcher:
        async def fetch_url_document(self, **kwargs):
            raise ValueError("PDF 公司文件沒有可抽取文字，可能是掃描圖檔；請先 OCR 成文字後再貼上，或改用官方 HTML/文字版文件。")

    client, _ = _quality_client(FakeFetcher)

    response = client.post(
        "/company-filings/from-url",
        json={
            "ticker": "2330",
            "company_name": "台積電",
            "document_type": "annual_report",
            "url": "https://mops.twse.com.tw/server-java/t57sb01?co_id=2330",
        },
    )

    assert response.status_code == 400
    assert "OCR" in response.json()["detail"]
    assert "文字版文件" in response.json()["detail"]


def _client(company_filing_api) -> TestClient:
    class FakeServices:
        def company_filing_api(self):
            return company_filing_api

    app = FastAPI()
    app.include_router(create_company_filing_router(FakeServices()))
    return TestClient(app)


def _quality_client(fetcher_cls=CompanyFilingFetcher) -> tuple[TestClient, dict]:
    stored = {}
    original_repository = CompanyFilingRepository

    class FakeVectorStore:
        def upsert_documents(self, documents):
            stored["rag_document_id"] = documents[0].id

    class FakeCompanyFilingRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def upsert_document(self, document):
            stored["filing_id"] = document.id

        @staticmethod
        def to_news_document(document):
            return original_repository.to_news_document(document)

    @contextmanager
    def fake_session_scope():
        yield object()

    service = CompanyFilingApiService(
        session_scope_factory=fake_session_scope,
        company_filing_fetcher_cls=fetcher_cls,
        company_filing_repository_cls=FakeCompanyFilingRepository,
        vector_store_cls=FakeVectorStore,
    )
    return _client(service), stored
