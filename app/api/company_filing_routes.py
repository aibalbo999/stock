from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import api_services_provider
from app.api.schemas import CompanyFilingUrlIngest, ManualCompanyFilingIngest, MarketRefreshRequest


def create_company_filing_router(api_services: Any | None = None) -> APIRouter:
    router = APIRouter()
    services_dependency = api_services_provider(api_services)

    @router.post("/company-filings/manual")
    def ingest_company_filing_manual(
        payload: ManualCompanyFilingIngest,
        services: Any = Depends(services_dependency),
    ) -> dict:
        return services.company_filing_api().ingest_manual(
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
    async def ingest_company_filing_from_url(
        payload: CompanyFilingUrlIngest,
        services: Any = Depends(services_dependency),
    ) -> dict:
        try:
            return await services.company_filing_api().ingest_from_url(
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
    async def fetch_company_filings(
        payload: MarketRefreshRequest,
        services: Any = Depends(services_dependency),
    ) -> dict:
        return await services.company_filing_api().fetch_company_filings(payload.tickers)

    @router.get("/company-filings")
    def list_company_filings(
        tickers: str = "",
        limit_per_ticker: int = 5,
        services: Any = Depends(services_dependency),
    ) -> list[dict]:
        return services.company_filing_api().list_company_filings(tickers, limit_per_ticker)

    return router
