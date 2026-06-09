from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CompanyFiling
from app.models.schemas import CompanyFilingDocument, NewsDocument, Source


class CompanyFilingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_document(self, document: CompanyFilingDocument) -> CompanyFiling:
        row = self.session.get(CompanyFiling, document.id)
        values = {
            "ticker": document.ticker,
            "company_name": document.company_name,
            "document_type": document.document_type,
            "title": document.title,
            "text": document.text,
            "publisher": document.source.publisher,
            "url": document.source.url,
            "published_at": document.source.published_at,
            "fetched_at": document.source.fetched_at,
        }
        if row is None:
            row = CompanyFiling(id=document.id, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        return row

    def latest_by_tickers(
        self, tickers: list[str], limit_per_ticker: int = 5
    ) -> list[CompanyFilingDocument]:
        documents: list[CompanyFilingDocument] = []
        for ticker in tickers:
            statement = (
                select(CompanyFiling)
                .where(CompanyFiling.ticker == ticker)
                .order_by(
                    CompanyFiling.published_at.desc().nullslast(), CompanyFiling.created_at.desc()
                )
                .limit(limit_per_ticker)
            )
            documents.extend(self._to_document(row) for row in self.session.scalars(statement))
        return documents

    def search_documents(
        self, query: str, tickers: list[str] | None = None, limit: int = 20
    ) -> list[CompanyFilingDocument]:
        terms = [term for term in query.split() if term]
        statement = select(CompanyFiling).order_by(
            CompanyFiling.published_at.desc().nullslast(),
            CompanyFiling.created_at.desc(),
        )
        if tickers:
            statement = statement.where(CompanyFiling.ticker.in_(tickers))
        rows = list(self.session.scalars(statement.limit(limit * 4)))
        if terms:
            rows = [
                row
                for row in rows
                if any(
                    term in row.title or term in row.text or term == row.ticker for term in terms
                )
            ]
        return [self._to_document(row) for row in rows[:limit]]

    def stats_by_ticker(self, ticker: str) -> dict:
        rows = list(
            self.session.scalars(select(CompanyFiling).where(CompanyFiling.ticker == ticker))
        )
        latest = max((row.published_at for row in rows if row.published_at), default=None)
        return {
            "rows": len(rows),
            "document_types": sorted({row.document_type for row in rows}),
            "publishers": len({row.publisher or row.url or row.title for row in rows}),
            "latest_date": latest.isoformat() if latest else None,
        }

    @staticmethod
    def _to_document(row: CompanyFiling) -> CompanyFilingDocument:
        return CompanyFilingDocument(
            id=row.id,
            ticker=row.ticker,
            company_name=row.company_name,
            document_type=row.document_type,
            title=row.title,
            text=row.text,
            source=Source(
                title=row.title,
                url=row.url,
                publisher=row.publisher,
                published_at=row.published_at,
                fetched_at=row.fetched_at,
            ),
        )

    @staticmethod
    def to_news_document(document: CompanyFilingDocument) -> NewsDocument:
        label = f"公司公開文件/{document.document_type}"
        company = f"{document.ticker} {document.company_name or ''}".strip()
        text = (
            f"股票代號：{document.ticker}\n"
            f"公司名稱：{document.company_name or ''}\n"
            f"文件類型：{document.document_type}\n"
            f"{company}\n"
            f"{document.text}"
        )
        return NewsDocument(
            id=f"filing-{document.id}",
            title=document.title,
            text=text,
            source=Source(
                title=document.title,
                url=document.source.url,
                publisher=document.source.publisher or label,
                published_at=document.source.published_at,
                fetched_at=document.source.fetched_at,
            ),
            entity_tickers=[document.ticker],
            entity_names=[document.company_name] if document.company_name else [],
        )


__all__ = ["CompanyFilingRepository"]
