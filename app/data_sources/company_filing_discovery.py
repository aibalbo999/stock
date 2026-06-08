from __future__ import annotations

from datetime import date
from ipaddress import ip_address
import re
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from app.models.schemas import CompanyFilingDocument, NewsDocument


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
BLOCKED_OR_PLACEHOLDER_PAGE_PATTERNS = (
    "access denied",
    "captcha",
    "cloudflare",
    "enable javascript",
    "forbidden",
    "javascript is disabled",
    "request blocked",
    "too many requests",
    "請先登入",
    "請啟用 javascript",
    "登入後查看",
    "機器人驗證",
    "驗證碼",
)
REQUIRED_CORE_DOCUMENT_TYPES = ("annual_report",)
RECOMMENDED_DOCUMENT_TYPES = ("investor_presentation",)


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
    if looks_like_blocked_or_placeholder_filing_page(lowered):
        raise ValueError("company filing content looks like a blocked, login, or placeholder page")
    company_terms = [ticker.lower()]
    if company_name:
        company_terms.append(company_name.lower())
    if not any(term and term in lowered for term in company_terms):
        raise ValueError("company filing content does not mention the target company")

    if document_type != "company_disclosure":
        keywords = DOCUMENT_TYPE_KEYWORDS.get(document_type, ())
        if keywords and not any(keyword.lower() in lowered for keyword in keywords):
            raise ValueError("company filing content does not match the selected document type")


def looks_like_blocked_or_placeholder_filing_page(text: str) -> bool:
    lowered = (text or "").lower()
    return any(pattern in lowered for pattern in BLOCKED_OR_PLACEHOLDER_PAGE_PATTERNS)


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
