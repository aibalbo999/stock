from __future__ import annotations

from datetime import date, datetime
from hashlib import sha1
from ipaddress import ip_address
from io import BytesIO
import re
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.data_sources.news import NewsFetcher
from app.models.schemas import CompanyFilingDocument, NewsDocument, Source


DOCUMENT_QUERY_TEMPLATES = (
    "{ticker} {name} 年報 法說會 公開說明書 filetype:pdf",
    "{ticker} {name} investor presentation annual report filetype:pdf",
    "{ticker} {name} 公開資訊觀測站 年報 site:mops.twse.com.tw",
    "{ticker} {name} 股東會年報 site:doc.twse.com.tw",
    "{ticker} {name} 法人說明會 site:mops.twse.com.tw",
    "{ticker} {name} 法說會 簡報 site:doc.twse.com.tw",
    "{ticker} {name} investor relations presentation",
    "{ticker} {name} IR annual report investor relations",
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
    "doc.twse.com.tw",
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
MIN_FETCHED_DOCUMENT_CHARS = 120
MAX_FETCHED_DOCUMENT_CHARS = 500_000
MAX_FETCHED_DOCUMENT_BYTES = 20_000_000
OFFICIAL_WEBSITE_FETCH_TIMEOUT_SECONDS = 8
PDF_IMPORT_MISSING_PYPDF_MESSAGE = "PDF 匯入需要安裝 pypdf，請先完成系統相依套件安裝後再重試。"
PDF_IMPORT_PARSE_ERROR_MESSAGE = "PDF 公司文件無法解析，可能是檔案加密、損毀或格式不支援；請改用官方 HTML 頁面，或人工貼上文字版內容。"
PDF_IMPORT_NO_TEXT_MESSAGE = "PDF 公司文件沒有可抽取文字，可能是掃描圖檔；請先 OCR 成文字後再貼上，或改用官方 HTML/文字版文件。"
REQUIRED_CORE_DOCUMENT_TYPES = ("annual_report",)
RECOMMENDED_DOCUMENT_TYPES = ("investor_presentation",)


class CompanyFilingFetcher:
    _twse_profile_cache: list[dict] | None = None
    _tpex_profile_cache: list[dict] | None = None

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
        document = await self._fetch_url_as_document(url, publisher=publisher)
        validate_fetched_company_filing_document(document, ticker, company_name, document_type)
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

    async def _fetch_url_as_document(self, url: str, publisher: str | None = None) -> NewsDocument:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
        content_length = int(response.headers.get("content-length") or 0)
        if content_length > MAX_FETCHED_DOCUMENT_BYTES or len(response.content) > MAX_FETCHED_DOCUMENT_BYTES:
            raise ValueError("company filing content is too large to import")
        content_type = response.headers.get("content-type", "").lower()
        if is_pdf_response(url, content_type):
            return self._pdf_response_to_document(url, response.content, publisher)
        soup = BeautifulSoup(response.text, "html.parser")
        title = NewsFetcher._title(soup) or url
        text = NewsFetcher._article_text(soup)
        return NewsDocument(
            id=sha1(url.encode("utf-8")).hexdigest(),
            title=title,
            text=text,
            source=Source(
                title=title,
                url=url,
                publisher=publisher,
                published_at=NewsFetcher._published_date(soup),
                fetched_at=datetime.utcnow(),
            ),
        )

    @staticmethod
    def _pdf_response_to_document(
        url: str,
        content: bytes,
        publisher: str | None = None,
    ) -> NewsDocument:
        text = extract_pdf_text(content)
        title = pdf_title_from_url(url)
        return NewsDocument(
            id=sha1(url.encode("utf-8")).hexdigest(),
            title=title,
            text=text,
            source=Source(
                title=title,
                url=url,
                publisher=publisher,
                fetched_at=datetime.utcnow(),
            ),
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

    async def fetch_web_search_documents(
        self,
        ticker: str,
        company_name: str = "",
        limit_per_query: int = 5,
        document_types: list[str] | tuple[str, ...] | None = None,
    ) -> tuple[list[CompanyFilingDocument], list[dict]]:
        documents: list[CompanyFilingDocument] = []
        errors = []
        seen_urls: set[str] = set()
        for query_text in self.official_search_queries(ticker, company_name, document_types=document_types):
            try:
                results = await self._duckduckgo_search(query_text, limit_per_query)
            except Exception as exc:
                errors.append({"source": query_text, "error": str(exc)})
                continue
            for result in results:
                url = result.get("url") or ""
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                preview = NewsDocument(
                    id=sha1(url.encode("utf-8")).hexdigest(),
                    title=result.get("title") or url,
                    text=result.get("snippet") or "",
                    source=Source(title=result.get("title") or url, url=url, publisher=result.get("publisher")),
                )
                if not is_relevant_company_filing_result(preview, ticker, company_name):
                    continue
                try:
                    document_type = infer_document_type(f"{preview.title}\n{preview.text}\n{url}")
                    document = await self.fetch_url_document(
                        url,
                        ticker=ticker,
                        company_name=company_name,
                        document_type=document_type,
                        publisher=preview.source.publisher or "web company filing discovery",
                    )
                except Exception as exc:
                    errors.append({"source": url, "error": str(exc)})
                    continue
                documents.append(document)
        return documents, errors

    async def fetch_mops_annual_report_documents(
        self,
        ticker: str,
        company_name: str = "",
        years: int = 3,
    ) -> tuple[list[CompanyFilingDocument], list[dict]]:
        documents: list[CompanyFilingDocument] = []
        errors = []
        current_roc_year = date.today().year - 1911
        for roc_year in range(current_roc_year, current_roc_year - years, -1):
            query_url = (
                "https://doc.twse.com.tw/server-java/t57sb01"
                f"?step=1&colorchg=1&co_id={ticker}&year={roc_year}&mtype=F&isnew=false"
            )
            try:
                html = await self._fetch_url_text(query_url, encoding="big5")
                rows = parse_mops_annual_report_rows(html)
            except Exception as exc:
                errors.append({"source": query_url, "error": str(exc)})
                continue
            for row in rows:
                filename = row.get("filename") or ""
                if not filename:
                    continue
                try:
                    pdf_url, content = await self._download_mops_pdf(ticker, filename, "F")
                    text = extract_pdf_text(content)
                    title = row.get("description") or filename
                    published_at = parse_mops_roc_datetime(row.get("uploaded_at") or "")
                    document = self.from_manual_text(
                        ticker=ticker,
                        company_name=company_name,
                        document_type="annual_report",
                        title=title,
                        text=text,
                        publisher="公開資訊觀測站 MOPS",
                        published_at=published_at,
                        url=pdf_url,
                    )
                    validate_fetched_company_filing_document(document, ticker, company_name, "annual_report")
                except Exception as exc:
                    errors.append({"source": filename, "error": str(exc)})
                    continue
                documents.append(document)
            if documents:
                break
        return documents, errors

    @staticmethod
    async def _download_mops_pdf(ticker: str, filename: str, kind: str) -> tuple[str, bytes]:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.post(
                "https://doc.twse.com.tw/server-java/t57sb01",
                data={
                    "step": "9",
                    "kind": kind,
                    "co_id": ticker,
                    "filename": filename,
                    "colorchg": "1",
                },
            )
            response.raise_for_status()
            response.encoding = "big5"
            soup = BeautifulSoup(response.text, "html.parser")
            link = soup.find("a", href=True)
            if not link:
                raise ValueError("MOPS did not return a PDF download link")
            pdf_url = urljoin("https://doc.twse.com.tw", link["href"])
            pdf_response = await client.get(pdf_url)
            pdf_response.raise_for_status()
        if len(pdf_response.content) > MAX_FETCHED_DOCUMENT_BYTES:
            raise ValueError("company filing content is too large to import")
        return pdf_url, pdf_response.content

    async def fetch_official_website_documents(
        self,
        ticker: str,
        company_name: str = "",
        limit: int = 12,
        document_types: list[str] | tuple[str, ...] | None = None,
    ) -> tuple[list[CompanyFilingDocument], list[dict]]:
        profile = await self.twse_company_profile(ticker)
        profile_name = (profile or {}).get("公司簡稱") or (profile or {}).get("公司名稱") or ""
        website = normalize_company_website((profile or {}).get("網址") or "")
        company_name = company_name or profile_name
        if not website:
            return [], [{"source": "TWSE company profile", "error": "company website not found"}]

        urls_to_scan = official_website_seed_urls(website)
        candidate_links: list[dict] = []
        errors = []
        for page_url in urls_to_scan:
            try:
                page_html, final_page_url = await self._fetch_url_text_with_final_url(
                    page_url,
                    timeout=OFFICIAL_WEBSITE_FETCH_TIMEOUT_SECONDS,
                )
                soup = BeautifulSoup(page_html, "html.parser")
                page = NewsDocument(
                    id=sha1(final_page_url.encode("utf-8")).hexdigest(),
                    title=NewsFetcher._title(soup) or final_page_url,
                    text=NewsFetcher._article_text(soup),
                    source=Source(
                        title=NewsFetcher._title(soup) or final_page_url,
                        url=final_page_url,
                        publisher="TWSE company profile website",
                        published_at=NewsFetcher._published_date(soup),
                        fetched_at=datetime.utcnow(),
                    ),
                )
            except Exception as exc:
                errors.append({"source": page_url, "error": str(exc)})
                continue
            candidate_links.extend(extract_company_filing_links(page_html, final_page_url))
            if is_document_text_relevant(page, ticker, company_name, document_types):
                candidate_links.append(
                    {
                        "url": page.source.url or page_url,
                        "title": page.title,
                        "publisher": page.source.publisher,
                    }
                )
            if len(candidate_links) >= limit:
                break

        documents: list[CompanyFilingDocument] = []
        seen_urls: set[str] = set()
        for link in candidate_links:
            url = link.get("url") or ""
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            preview_text = f"{link.get('title') or ''}\n{url}"
            document_type = infer_document_type(preview_text)
            if document_types and document_type not in set(document_types):
                continue
            try:
                document = await self.fetch_url_document(
                    url,
                    ticker=ticker,
                    company_name=company_name,
                    document_type=document_type,
                    publisher=link.get("publisher") or "official company website",
                )
            except Exception as exc:
                errors.append({"source": url, "error": str(exc)})
                continue
            documents.append(document)
            if len(documents) >= limit:
                break
        return documents, errors

    @staticmethod
    async def _fetch_url_text(
        url: str,
        encoding: str | None = None,
        timeout: int = 20,
    ) -> str:
        text, _ = await CompanyFilingFetcher._fetch_url_text_with_final_url(
            url,
            encoding=encoding,
            timeout=timeout,
        )
        return text

    @staticmethod
    async def _fetch_url_text_with_final_url(
        url: str,
        encoding: str | None = None,
        timeout: int = 20,
        max_html_redirects: int = 2,
    ) -> tuple[str, str]:
        current_url = url
        visited = set()
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            for _ in range(max_html_redirects + 1):
                response = await client.get(current_url)
                response.raise_for_status()
                content_length = int(response.headers.get("content-length") or 0)
                if content_length > MAX_FETCHED_DOCUMENT_BYTES or len(response.content) > MAX_FETCHED_DOCUMENT_BYTES:
                    raise ValueError("company filing content is too large to import")
                if encoding:
                    response.encoding = encoding
                final_url = str(response.url)
                text = response.text
                redirect_url = extract_html_redirect_url(text, final_url)
                if not redirect_url or redirect_url in visited:
                    return text, final_url
                visited.add(final_url)
                current_url = redirect_url
        return text, final_url

    @classmethod
    async def twse_company_profile(cls, ticker: str) -> dict:
        if cls._twse_profile_cache is None:
            url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
            cls._twse_profile_cache = response.json()
        twse_row = next((row for row in cls._twse_profile_cache if str(row.get("公司代號") or "") == ticker), None)
        if twse_row:
            return twse_row
        if cls._tpex_profile_cache is None:
            url = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
            cls._tpex_profile_cache = response.json()
        tpex_row = next(
            (
                row
                for row in cls._tpex_profile_cache
                if str(row.get("SecuritiesCompanyCode") or "") == ticker
            ),
            None,
        )
        return normalize_tpex_company_profile(tpex_row) if tpex_row else {}

    @staticmethod
    async def _duckduckgo_search(query_text: str, limit: int = 5) -> list[dict]:
        url = f"https://duckduckgo.com/html/?q={quote_plus(query_text)}"
        headers = {"User-Agent": "Mozilla/5.0 stock-research-bot/1.0"}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        results = []
        for result in soup.select(".result"):
            link = result.select_one("a.result__a")
            if not link:
                continue
            href = normalize_search_result_url(link.get("href") or "")
            if not href:
                continue
            snippet_node = result.select_one(".result__snippet")
            parsed = urlparse(href)
            results.append(
                {
                    "title": link.get_text(" ", strip=True),
                    "url": href,
                    "snippet": snippet_node.get_text(" ", strip=True) if snippet_node else "",
                    "publisher": parsed.netloc,
                }
            )
            if len(results) >= limit:
                break
        return results


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


def is_pdf_response(url: str, content_type: str) -> bool:
    return "application/pdf" in content_type or urlparse(url).path.lower().endswith(".pdf")


def parse_mops_annual_report_rows(html: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    rows = []
    for table_row in soup.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in table_row.find_all("td")]
        if len(cells) < 10:
            continue
        description = cells[5]
        filename = cells[7]
        if "股東會年報" not in description or "英文版" in description or "前十大股東" in description:
            continue
        rows.append(
            {
                "ticker": cells[0],
                "data_year": cells[1],
                "description": description,
                "filename": filename,
                "uploaded_at": cells[9],
            }
        )
    return rows


def parse_mops_roc_datetime(value: str) -> date | None:
    value = (value or "").strip()
    if not value or "/" not in value:
        return None
    date_part = value.split()[0]
    parts = date_part.split("/")
    if len(parts) != 3:
        return None
    try:
        year = int(parts[0]) + 1911
        return date(year, int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def normalize_search_result_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(target)
    if url.startswith("//"):
        return "https:" + url
    return url


def normalize_company_website(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


def normalize_tpex_company_profile(row: dict | None) -> dict:
    if not row:
        return {}
    return {
        "公司代號": row.get("SecuritiesCompanyCode") or "",
        "公司名稱": row.get("CompanyName") or "",
        "公司簡稱": row.get("CompanyAbbreviation") or "",
        "網址": row.get("WebAddress") or "",
        "電子郵件信箱": row.get("EmailAddress") or "",
    }


def extract_html_redirect_url(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    meta_refresh = soup.find("meta", attrs={"http-equiv": lambda value: value and value.lower() == "refresh"})
    if meta_refresh:
        content = meta_refresh.get("content") or ""
        match = re.search(r"url\s*=\s*['\"]?([^;'\"\s]+)", content, flags=re.IGNORECASE)
        if match:
            return urljoin(base_url, match.group(1))
    match = re.search(
        r"(?:window\.)?location(?:\.href)?\s*=\s*['\"]([^'\"]+)['\"]",
        html or "",
        flags=re.IGNORECASE,
    )
    if match:
        return urljoin(base_url, match.group(1))
    return ""


def official_website_seed_urls(website: str) -> list[str]:
    parsed = urlparse(website)
    root = f"{parsed.scheme}://{parsed.netloc}"
    paths = [
        "",
        "/investor",
        "/investors",
        "/ir",
        "/investor-relations",
        "/investor/financial-reports",
        "/investor/financials",
        "/investor/shareholder-services",
        "/investor-service",
        "/annual-reports",
        "/annual-report",
        "/zh-TW/investor",
        "/zh-TW/investor-relations",
        "/zh-TW/ir",
        "/zh-Hant/investor",
        "/zh-Hant/investor-relations",
        "/chinese/investor",
        "/chinese/ir",
        "/chinese/annual-reports",
    ]
    urls = [website, *[root + path for path in paths if root + path != website]]
    return list(dict.fromkeys(urls))


def extract_company_filing_links(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    links = []
    for anchor in soup.find_all("a"):
        href = anchor.get("href") or ""
        text = anchor.get_text(" ", strip=True)
        target = urljoin(base_url, href)
        haystack = f"{text}\n{target}".lower()
        if not any(term.lower() in haystack for term in DISCLOSURE_TERMS):
            continue
        if not target.startswith(("http://", "https://")):
            continue
        links.append({"url": target, "title": text or target, "publisher": urlparse(target).netloc})
    return links


def is_document_text_relevant(
    document: NewsDocument,
    ticker: str,
    company_name: str,
    document_types: list[str] | tuple[str, ...] | None,
) -> bool:
    text = f"{document.title}\n{document.text}\n{document.source.url or ''}"
    if document_types and infer_document_type(text) not in set(document_types):
        return False
    return is_relevant_company_filing_result(document, ticker, company_name)


def pdf_title_from_url(url: str) -> str:
    name = urlparse(url).path.rsplit("/", 1)[-1]
    return name or url


def extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader
        from pypdf.errors import DependencyError
    except ImportError as exc:
        raise ValueError(PDF_IMPORT_MISSING_PYPDF_MESSAGE) from exc
    try:
        reader = PdfReader(BytesIO(content))
        if getattr(reader, "is_encrypted", False):
            reader.decrypt("")
        pages = [page.extract_text() or "" for page in reader.pages]
    except DependencyError as exc:
        raise ValueError("PDF 公司文件使用加密格式，請安裝 cryptography 後再重試解析。") from exc
    except Exception as exc:
        raise ValueError(PDF_IMPORT_PARSE_ERROR_MESSAGE) from exc
    text = "\n".join(page.strip() for page in pages if page.strip())
    if not text.strip():
        raise ValueError(PDF_IMPORT_NO_TEXT_MESSAGE)
    return text


def validate_fetched_company_filing_document(
    document: NewsDocument,
    ticker: str,
    company_name: str = "",
    document_type: str = "company_disclosure",
) -> None:
    text = f"{document.title}\n{document.text}".strip()
    if len(text) < MIN_FETCHED_DOCUMENT_CHARS:
        raise ValueError("company filing content is too short to audit")
    if len(text) > MAX_FETCHED_DOCUMENT_CHARS:
        raise ValueError("company filing content is too large to import")

    lowered = text.lower()
    company_terms = [ticker.lower()]
    if company_name:
        company_terms.append(company_name.lower())
    if not any(term and term in lowered for term in company_terms):
        raise ValueError("company filing content does not mention the target company")

    if document_type != "company_disclosure":
        keywords = DOCUMENT_TYPE_KEYWORDS.get(document_type, ())
        if keywords and not any(keyword.lower() in lowered for keyword in keywords):
            raise ValueError("company filing content does not match the selected document type")


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
                "{ticker} {name} 股東會年報 site:doc.twse.com.tw",
                "{ticker} {name} IR 年報",
            ]
        )
    if "investor_presentation" in wanted:
        templates.extend(
            [
                "{ticker} {name} 法人說明會 filetype:pdf",
                "{ticker} {name} investor presentation filetype:pdf",
                "{ticker} {name} 法人說明會 site:mops.twse.com.tw",
                "{ticker} {name} 法說會 簡報 site:doc.twse.com.tw",
                "{ticker} {name} IR presentation",
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
