from __future__ import annotations

from datetime import date, datetime
from hashlib import sha1
from urllib.parse import quote_plus

from app.data_sources.news import NewsFetcher
from app.models.schemas import CompanyFilingDocument, NewsDocument, Source


DOCUMENT_QUERY_TEMPLATES = (
    "{ticker} {name} 年報 法說會 公開說明書",
    "{ticker} {name} investor presentation annual report",
    "{ticker} {name} 公開資訊觀測站 年報",
)

DOCUMENT_TYPE_KEYWORDS = {
    "annual_report": ("年報", "annual report", "股東會年報"),
    "investor_presentation": ("法說", "法人說明", "investor presentation", "earnings presentation"),
    "prospectus": ("公開說明書", "prospectus", "募集", "增資"),
    "material_information": ("重大訊息", "material information", "mops"),
}
DISCLOSURE_TERMS = tuple(
    keyword
    for keywords in DOCUMENT_TYPE_KEYWORDS.values()
    for keyword in keywords
)


class CompanyFilingFetcher:
    def __init__(self) -> None:
        self.news_fetcher = NewsFetcher()

    @staticmethod
    def google_news_urls(ticker: str, name: str = "", limit: int = 3) -> list[str]:
        urls = []
        for template in DOCUMENT_QUERY_TEMPLATES[:limit]:
            query = quote_plus(template.format(ticker=ticker, name=name).strip())
            urls.append(f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
        return urls

    @staticmethod
    def from_news_document(
        document: NewsDocument,
        ticker: str,
        company_name: str = "",
        document_type: str | None = None,
    ) -> CompanyFilingDocument:
        inferred_type = document_type or infer_document_type(f"{document.title}\n{document.text}")
        digest = sha1(f"{ticker}:{inferred_type}:{document.source.url or document.id}".encode("utf-8")).hexdigest()
        return CompanyFilingDocument(
            id=digest,
            ticker=ticker,
            company_name=company_name or None,
            document_type=inferred_type,
            title=document.title,
            text=document.text,
            source=document.source,
        )

    @staticmethod
    def from_manual_text(
        ticker: str,
        title: str,
        text: str,
        company_name: str = "",
        document_type: str = "company_disclosure",
        publisher: str = "manual company filing",
        published_at: date | None = None,
        url: str | None = None,
    ) -> CompanyFilingDocument:
        digest = sha1(f"{ticker}:{document_type}:{url or title}:{text[:80]}".encode("utf-8")).hexdigest()
        return CompanyFilingDocument(
            id=digest,
            ticker=ticker,
            company_name=company_name or None,
            document_type=document_type,
            title=title,
            text=text,
            source=Source(
                title=title,
                url=url,
                publisher=publisher,
                published_at=published_at,
                fetched_at=datetime.utcnow(),
            ),
        )

    async def fetch_discovery_documents(
        self,
        ticker: str,
        company_name: str = "",
        limit_per_query: int = 3,
    ) -> tuple[list[CompanyFilingDocument], list[dict]]:
        documents: list[CompanyFilingDocument] = []
        errors = []
        for url in self.google_news_urls(ticker, company_name):
            try:
                feed_documents = await self.news_fetcher.fetch_feed(
                    url,
                    publisher="Google News company filings",
                    limit=limit_per_query,
                )
            except Exception as exc:
                errors.append({"source": url, "error": str(exc)})
                continue
            for document in feed_documents:
                if not is_relevant_company_filing_result(document, ticker, company_name):
                    continue
                documents.append(self.from_news_document(document, ticker, company_name))
        return documents, errors


def infer_document_type(text: str) -> str:
    lowered = text.lower()
    for document_type, keywords in DOCUMENT_TYPE_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            return document_type
    return "company_disclosure"


def is_relevant_company_filing_result(document: NewsDocument, ticker: str, company_name: str = "") -> bool:
    text = f"{document.title}\n{document.text}".lower()
    company_terms = [ticker.lower()]
    if company_name:
        company_terms.append(company_name.lower())
    has_company = any(term and term in text for term in company_terms)
    has_disclosure = any(term.lower() in text for term in DISCLOSURE_TERMS)
    return has_company and has_disclosure
