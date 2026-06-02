from datetime import date

from app.data_sources.news import NewsFetcher
from app.services.company_filing_cache import RedisCompanyFilingCache


class FakeRedis:
    def __init__(self) -> None:
        self.values = {}
        self.ttls = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.values[key] = value
        self.ttls[key] = ttl


def test_company_filing_cache_roundtrip_news_document() -> None:
    client = FakeRedis()
    cache = RedisCompanyFilingCache(
        enabled=True,
        ttl_seconds=123,
        client_factory=lambda _url: client,
    )
    document = NewsFetcher.from_manual_text(
        title="台積電 2026 年報",
        text="台積電 年報揭露 AI/HPC 需求與風險因素。" * 8,
        publisher="台積電 IR",
        published_at=date(2026, 5, 1),
        url="https://investor.tsmc.com/annual-report.pdf",
    )

    cache.set_url_document(
        "https://investor.tsmc.com/annual-report.pdf",
        document,
        parser="pdfplumber",
        extract_tables=True,
        html_extract_tables=True,
    )
    cached = cache.get_url_document(
        "https://investor.tsmc.com/annual-report.pdf",
        parser="pdfplumber",
        extract_tables=True,
        html_extract_tables=True,
    )

    assert cached is not None
    assert cached.title == document.title
    assert cached.source.published_at == date(2026, 5, 1)
    assert list(client.ttls.values()) == [123]


def test_company_filing_cache_key_changes_with_parser_options() -> None:
    client = FakeRedis()
    cache = RedisCompanyFilingCache(client_factory=lambda _url: client)
    document = NewsFetcher.from_manual_text(
        title="台積電 2026 年報",
        text="台積電 年報揭露 AI/HPC 需求與風險因素。" * 8,
        url="https://investor.tsmc.com/annual-report.pdf",
    )

    cache.set_url_document(
        "https://investor.tsmc.com/annual-report.pdf",
        document,
        parser="pypdf",
        extract_tables=False,
        html_extract_tables=False,
    )

    assert (
        cache.get_url_document(
            "https://investor.tsmc.com/annual-report.pdf",
            parser="pdfplumber",
            extract_tables=True,
            html_extract_tables=False,
        )
        is None
    )
    assert (
        cache.get_url_document(
            "https://investor.tsmc.com/annual-report.pdf",
            parser="pypdf",
            extract_tables=False,
            html_extract_tables=True,
        )
        is None
    )


def test_company_filing_cache_status_describes_scope() -> None:
    cache = RedisCompanyFilingCache(enabled=True, ttl_seconds=456, client_factory=lambda _url: FakeRedis())

    assert cache.status() == {
        "enabled": True,
        "available": True,
        "backend": "redis",
        "ttl_seconds": 456,
        "key_namespace": "stock-ai:company-filing:url-document:v1",
        "key_scope": ["url", "parser", "extract_tables", "html_extract_tables"],
    }
