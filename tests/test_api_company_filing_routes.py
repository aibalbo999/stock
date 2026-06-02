from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.company_filing_routes import create_company_filing_router


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


def _client(company_filing_api) -> TestClient:
    class FakeServices:
        def company_filing_api(self):
            return company_filing_api

    app = FastAPI()
    app.include_router(create_company_filing_router(FakeServices()))
    return TestClient(app)
