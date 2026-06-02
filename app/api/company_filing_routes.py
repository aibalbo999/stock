from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.schemas import CompanyFilingUrlIngest, ManualCompanyFilingIngest, MarketRefreshRequest


def create_company_filing_router(api_services: Any) -> APIRouter:
    router = APIRouter()

    @router.post("/company-filings/manual")
    def ingest_company_filing_manual(payload: ManualCompanyFilingIngest) -> dict:
        return api_services.company_filing_api().ingest_manual(
            ticker=payload.ticker,
            company_name=payload.company_name,
            document_type=payload.document_type,
            title=payload.title,
            text=payload.text,
            publisher=payload.publisher,
            published_at=payload.published_at,
            url=payload.url,
        )

    @router.post("/company-filings/from-url")
    async def ingest_company_filing_from_url(payload: CompanyFilingUrlIngest) -> dict:
        try:
            return await api_services.company_filing_api().ingest_from_url(
                url=payload.url,
                ticker=payload.ticker,
                company_name=payload.company_name,
                document_type=payload.document_type,
                publisher=payload.publisher,
                published_at=payload.published_at,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/company-filings/fetch")
    async def fetch_company_filings(payload: MarketRefreshRequest) -> dict:
        return await api_services.company_filing_api().fetch_company_filings(payload.tickers)

    @router.get("/company-filings")
    def list_company_filings(tickers: str = "", limit_per_ticker: int = 5) -> list[dict]:
        return api_services.company_filing_api().list_company_filings(tickers, limit_per_ticker)

    return router
