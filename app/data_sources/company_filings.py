from __future__ import annotations

from datetime import date, datetime
from hashlib import sha1
from ipaddress import ip_address
from urllib.parse import quote_plus, urlparse

from app.data_sources.news import NewsFetcher
from app.models.schemas import CompanyFilingDocument, NewsDocument, Source


DOCUMENT_QUERY_TEMPLATES = (
    "{ticker} {name} 年報 法說會 公開說明書 filetype:pdf",
    "{ticker} {name} investor presentation annual report filetype:pdf",
    "{ticker} {name} 公開資訊觀測站 年報 site:mops.twse.com.tw",
    "{ticker} {name} 法人說明會 site:mops.twse.com.tw",
    "{ticker} {name} investor relations presentation",
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
OFFICIAL_SOURCE_DOMAINS = (
    "mops.twse.com.tw",
    "mopsov.twse.com.tw",
    "twse.com.tw",
    "tpex.org.tw",
)
IR_SOURCE_HINTS = (
    "ir.",
    "/ir",
    "investor",
    "investors",
    "investor-relations",
    "investor_relations",
)
HIGH_QUALITY_FILING_SCORE = 70
REQUIRED_CORE_DOCUMENT_TYPES = ("annual_report",)
RECOMMENDED_DOCUMENT_TYPES = ("investor_presentation",)


class CompanyFilingFetcher:
    def __init__(self) -> None:
        self.news_fetcher = NewsFetcher()

    @staticmethod
    def official_search_queries(
        ticker: str,
        name: str = "",
        limit: int | None = None,
        document_types: list[str] | tuple[str, ...] | None = None,
    ) -> list[str]:
        templates = document_query_templates(document_types)
        templates = templates if limit is None else templates[:limit]
        return [template.format(ticker=ticker, name=name).strip() for template in templates]

    @classmethod
    def google_news_urls(
        cls,
        ticker: str,
        name: str = "",
        limit: int | None = None,
        document_types: list[str] | tuple[str, ...] | None = None,
    ) -> list[str]:
        urls = []
        for query_text in cls.official_search_queries(ticker, name, limit, document_types):
            query = quote_plus(query_text)
            urls.append(f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
        return urls

    @classmethod
    def official_search_plan(
        cls,
        ticker: str,
        name: str = "",
        document_types: list[str] | tuple[str, ...] | None = None,
    ) -> dict:
        queries = cls.official_search_queries(ticker, name, document_types=document_types)
        return {
            "ticker": ticker,
            "company_name": name,
            "document_types": list(document_types or []),
            "queries": queries,
            "google_news_urls": cls.google_news_urls(ticker, name, document_types=document_types),
            "official_portals": [
                {
                    "name": "公開資訊觀測站",
                    "url": "https://mops.twse.com.tw/mops/web/index",
                    "purpose": "年報、公開說明書、法人說明會與重大訊息原始揭露。",
                },
                {
                    "name": "臺灣證券交易所",
                    "url": "https://www.twse.com.tw/",
                    "purpose": "上市公司基本資料、重大訊息與市場公告交叉核對。",
                },
                {
                    "name": "櫃買中心",
                    "url": "https://www.tpex.org.tw/",
                    "purpose": "上櫃公司公告、財報與重大訊息交叉核對。",
                },
            ],
        }

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

    async def fetch_url_document(
        self,
        url: str,
        ticker: str,
        company_name: str = "",
        document_type: str = "company_disclosure",
        publisher: str | None = None,
        published_at: date | None = None,
    ) -> CompanyFilingDocument:
        validate_public_document_url(url)
        document = await self.news_fetcher.fetch_url(url, publisher=publisher)
        return self.from_manual_text(
            ticker=ticker,
            company_name=company_name,
            document_type=document_type,
            title=document.title,
            text=document.text,
            publisher=document.source.publisher or publisher or "company filing url",
            published_at=published_at or document.source.published_at,
            url=document.source.url or url,
        )

    async def fetch_discovery_documents(
        self,
        ticker: str,
        company_name: str = "",
        limit_per_query: int = 3,
        document_types: list[str] | tuple[str, ...] | None = None,
    ) -> tuple[list[CompanyFilingDocument], list[dict]]:
        documents: list[CompanyFilingDocument] = []
        errors = []
        for url in self.google_news_urls(ticker, company_name, document_types=document_types):
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


def filing_source_tier(document: CompanyFilingDocument | NewsDocument) -> str:
    url = (document.source.url or "").lower()
    publisher = (document.source.publisher or "").lower()
    if any(domain in url or domain in publisher for domain in OFFICIAL_SOURCE_DOMAINS):
        return "official_disclosure"
    if any(hint in url or hint in publisher for hint in IR_SOURCE_HINTS):
        return "company_ir"
    return "third_party"


def validate_public_document_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("company filing URL must use http or https")
    if not parsed.hostname:
        raise ValueError("company filing URL must include a hostname")
    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "127.0.0.1", "::1"} or hostname.endswith(".local"):
        raise ValueError("company filing URL cannot target localhost or local domains")
    try:
        address = ip_address(hostname)
    except ValueError:
        return
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise ValueError("company filing URL cannot target private or reserved IP addresses")


def filing_quality_score(document: CompanyFilingDocument | NewsDocument, ticker: str = "", company_name: str = "") -> int:
    text = f"{document.title}\n{getattr(document, 'text', '')}".lower()
    url = (document.source.url or "").lower()
    score = 0
    tier = filing_source_tier(document)
    if tier == "official_disclosure":
        score += 55
    elif tier == "company_ir":
        score += 45
    else:
        score += 15
    if ticker and ticker.lower() in text:
        score += 10
    if company_name and company_name.lower() in text:
        score += 10
    if any(term.lower() in text for term in DISCLOSURE_TERMS):
        score += 15
    if ".pdf" in url or "filetype:pdf" in url:
        score += 10
    if document.source.published_at:
        score += 5
    return min(score, 100)


def is_high_quality_company_filing(document: CompanyFilingDocument | NewsDocument, ticker: str = "", company_name: str = "") -> bool:
    return filing_quality_score(document, ticker, company_name) >= HIGH_QUALITY_FILING_SCORE


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
    if not has_company or not has_disclosure:
        return False
    return filing_quality_score(document, ticker, company_name) >= 40


def document_query_templates(document_types: list[str] | tuple[str, ...] | None = None) -> tuple[str, ...]:
    if not document_types:
        return DOCUMENT_QUERY_TEMPLATES
    templates = []
    wanted = set(document_types)
    if "annual_report" in wanted:
        templates.extend(
            [
                "{ticker} {name} 年報 filetype:pdf",
                "{ticker} {name} annual report filetype:pdf",
                "{ticker} {name} 公開資訊觀測站 年報 site:mops.twse.com.tw",
            ]
        )
    if "investor_presentation" in wanted:
        templates.extend(
            [
                "{ticker} {name} 法人說明會 filetype:pdf",
                "{ticker} {name} investor presentation filetype:pdf",
                "{ticker} {name} 法人說明會 site:mops.twse.com.tw",
            ]
        )
    if "prospectus" in wanted:
        templates.extend(
            [
                "{ticker} {name} 公開說明書 filetype:pdf",
                "{ticker} {name} prospectus filetype:pdf",
                "{ticker} {name} 公開說明書 site:mops.twse.com.tw",
            ]
        )
    if "material_information" in wanted:
        templates.extend(
            [
                "{ticker} {name} 重大訊息 site:mops.twse.com.tw",
                "{ticker} {name} material information",
            ]
        )
    return tuple(dict.fromkeys(templates)) or DOCUMENT_QUERY_TEMPLATES
