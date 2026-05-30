import asyncio
from datetime import date
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.data_sources.company_filings import (
    CompanyFilingFetcher,
    PDF_IMPORT_NO_TEXT_MESSAGE,
    extract_html_redirect_url,
    extract_pdf_text,
    filing_quality_score,
    filing_source_tier,
    infer_document_type,
    is_relevant_company_filing_result,
    normalize_search_result_url,
    normalize_tpex_company_profile,
    parse_mops_annual_report_rows,
    parse_mops_roc_datetime,
    validate_fetched_company_filing_document,
    validate_public_document_url,
)
from app.db.models import Base
from app.data_sources.news import NewsFetcher
from app.services.persistence import CompanyFilingRepository


def test_infer_company_filing_document_type() -> None:
    assert infer_document_type("台積電 2025 年報") == "annual_report"
    assert infer_document_type("Quanta investor presentation") == "investor_presentation"
    assert infer_document_type("公開說明書 募集資金用途") == "prospectus"


def test_company_filing_discovery_filters_generic_results() -> None:
    relevant = NewsFetcher.from_manual_text(
        title="2330 台積電 法說會重點",
        text="台積電 investor presentation 說明 AI/HPC 需求。",
    )
    generic = NewsFetcher.from_manual_text(
        title="台股財報公布時間整理",
        text="說明市場整體財報時間，沒有個別公司公開文件。",
    )

    assert is_relevant_company_filing_result(relevant, "2330", "台積電") is True
    assert is_relevant_company_filing_result(generic, "2330", "台積電") is False


def test_company_filing_quality_prefers_official_sources() -> None:
    official = NewsFetcher.from_manual_text(
        title="2330 台積電 年報",
        text="台積電 年報揭露 AI/HPC 需求與風險因素。",
        publisher="公開資訊觀測站",
        published_at=date(2026, 5, 1),
        url="https://mops.twse.com.tw/server-java/t57sb01?co_id=2330",
    )
    third_party = NewsFetcher.from_manual_text(
        title="2330 台積電 法說會懶人包",
        text="台積電 法說會摘要。",
        publisher="第三方部落格",
        published_at=date(2026, 5, 1),
        url="https://example.com/tsmc-summary",
    )

    assert filing_source_tier(official) == "official_disclosure"
    assert filing_quality_score(official, "2330", "台積電") >= 70
    assert filing_source_tier(third_party) == "third_party"
    assert filing_quality_score(third_party, "2330", "台積電") < 70


def test_company_filing_search_plan_targets_official_sources() -> None:
    plan = CompanyFilingFetcher.official_search_plan("2330", "台積電")

    assert any("site:mops.twse.com.tw" in query for query in plan["queries"])
    assert any("filetype:pdf" in query for query in plan["queries"])
    assert any(portal["name"] == "公開資訊觀測站" for portal in plan["official_portals"])
    assert len(plan["google_news_urls"]) == len(plan["queries"])


def test_company_filing_search_plan_can_target_document_type() -> None:
    plan = CompanyFilingFetcher.official_search_plan(
        "2330",
        "台積電",
        document_types=["annual_report"],
    )

    assert plan["document_types"] == ["annual_report"]
    assert all("年報" in query or "annual report" in query for query in plan["queries"])
    assert not any("法人說明會" in query for query in plan["queries"])


def test_search_result_url_normalizes_duckduckgo_redirect() -> None:
    url = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Finvestor.tsmc.com%2Fannual-report.pdf"

    assert normalize_search_result_url(url) == "https://investor.tsmc.com/annual-report.pdf"


def test_html_redirect_url_extracts_meta_and_location_href() -> None:
    assert (
        extract_html_redirect_url(
            '<meta http-equiv="refresh" content="0.1;url=page/en/index.html">',
            "https://www.qsitw.com/",
        )
        == "https://www.qsitw.com/page/en/index.html"
    )
    assert (
        extract_html_redirect_url(
            'location.href = "https://www.tuc.com.tw/index";',
            "https://www.tuc.com.tw/",
        )
        == "https://www.tuc.com.tw/index"
    )


def test_tpex_profile_is_normalized_for_official_website_discovery() -> None:
    profile = normalize_tpex_company_profile(
        {
            "SecuritiesCompanyCode": "6188",
            "CompanyName": "廣明光電股份有限公司",
            "CompanyAbbreviation": "廣明",
            "WebAddress": "www.qsitw.com",
            "EmailAddress": "ir@example.com",
        }
    )

    assert profile["公司代號"] == "6188"
    assert profile["公司簡稱"] == "廣明"
    assert profile["網址"] == "www.qsitw.com"


def test_company_profile_falls_back_to_tpex_cache() -> None:
    CompanyFilingFetcher._twse_profile_cache = []
    CompanyFilingFetcher._tpex_profile_cache = [
        {
            "SecuritiesCompanyCode": "6274",
            "CompanyName": "台燿科技股份有限公司",
            "CompanyAbbreviation": "台燿",
            "WebAddress": "www.tuc.com.tw",
        }
    ]
    try:
        profile = asyncio.run(CompanyFilingFetcher.twse_company_profile("6274"))
    finally:
        CompanyFilingFetcher._twse_profile_cache = None
        CompanyFilingFetcher._tpex_profile_cache = None

    assert profile["公司簡稱"] == "台燿"
    assert profile["網址"] == "www.tuc.com.tw"


def test_parse_mops_annual_report_rows_keeps_chinese_annual_report() -> None:
    html = """
    <table>
      <tr><td>2330</td><td>113 年</td><td>股東會相關資料</td><td></td><td>常會</td><td>股東會年報(尚未適用永續揭露準則)</td><td></td><td>2024_2330_F04.pdf</td><td>100</td><td>114/05/16 17:43:11</td></tr>
      <tr><td>2330</td><td>113 年</td><td>股東會相關資料</td><td></td><td>常會</td><td>英文版-股東會年報</td><td></td><td>2024_2330_FE4.pdf</td><td>100</td><td>114/05/16 17:43:11</td></tr>
      <tr><td>2330</td><td>113 年</td><td>股東會相關資料</td><td></td><td>常會</td><td>年報前十大股東相互間關係表</td><td></td><td>2024_2330_F17.pdf</td><td>100</td><td>114/05/16 17:43:11</td></tr>
    </table>
    """

    rows = parse_mops_annual_report_rows(html)

    assert rows == [
        {
            "ticker": "2330",
            "data_year": "113 年",
            "description": "股東會年報(尚未適用永續揭露準則)",
            "filename": "2024_2330_F04.pdf",
            "uploaded_at": "114/05/16 17:43:11",
        }
    ]
    assert parse_mops_roc_datetime("114/05/16 17:43:11") == date(2025, 5, 16)


def test_company_filing_web_search_fetches_candidate_documents(monkeypatch) -> None:
    async def fake_search(query_text: str, limit: int = 5):
        return [
            {
                "title": "台積電 2026 年報 PDF",
                "url": "https://investor.tsmc.com/annual-report.pdf",
                "snippet": "2330 台積電 年報 annual report",
                "publisher": "investor.tsmc.com",
            }
        ]

    async def fake_fetch_url_document(
        self,
        url,
        ticker,
        company_name="",
        document_type="company_disclosure",
        publisher=None,
        published_at=None,
    ):
        return CompanyFilingFetcher.from_manual_text(
            ticker=ticker,
            company_name=company_name,
            document_type=document_type,
            title="台積電 2026 年報",
            text="台積電 年報揭露 AI/HPC 需求與風險因素。" * 8,
            publisher=publisher or "investor.tsmc.com",
            published_at=date(2026, 5, 1),
            url=url,
        )

    monkeypatch.setattr(CompanyFilingFetcher, "_duckduckgo_search", staticmethod(fake_search))
    monkeypatch.setattr(CompanyFilingFetcher, "fetch_url_document", fake_fetch_url_document)

    import asyncio

    documents, errors = asyncio.run(
        CompanyFilingFetcher().fetch_web_search_documents(
            "2330",
            "台積電",
            document_types=["annual_report"],
        )
    )

    assert errors == []
    assert documents[0].document_type == "annual_report"
    assert documents[0].source.url == "https://investor.tsmc.com/annual-report.pdf"


def test_company_filing_repository_roundtrip() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        document = CompanyFilingFetcher.from_manual_text(
            ticker="2330",
            company_name="台積電",
            document_type="annual_report",
            title="台積電 年報",
            text="年報揭露 AI/HPC 需求、資本支出與風險因素。",
            publisher="台積電 IR",
            published_at=date(2026, 5, 1),
            url="https://example.com/2330-annual-report.pdf",
        )
        repository = CompanyFilingRepository(session)
        repository.upsert_document(document)
        session.commit()

        stored = repository.latest_by_tickers(["2330"])
        stats = repository.stats_by_ticker("2330")
        news_document = CompanyFilingRepository.to_news_document(stored[0])

    assert stored[0].ticker == "2330"
    assert stats["rows"] == 1
    assert stats["document_types"] == ["annual_report"]
    assert news_document.id.startswith("filing-")
    assert "文件類型：annual_report" in news_document.text


def test_company_filing_fetch_url_document_uses_page_text(monkeypatch) -> None:
    async def fake_fetch_url_as_document(self, url, publisher=None):
        return NewsFetcher.from_manual_text(
            title="台積電 2026 年報",
            text="台積電 2026 年報揭露 AI/HPC 需求與風險因素。" * 8,
            publisher=publisher or "公開資訊觀測站",
            published_at=date(2026, 5, 1),
            url=url,
        )

    monkeypatch.setattr(CompanyFilingFetcher, "_fetch_url_as_document", fake_fetch_url_as_document)

    import asyncio

    document = asyncio.run(
        CompanyFilingFetcher().fetch_url_document(
            "https://mops.twse.com.tw/server-java/t57sb01?co_id=2330",
            ticker="2330",
            company_name="台積電",
            document_type="annual_report",
        )
    )

    assert document.ticker == "2330"
    assert document.document_type == "annual_report"
    assert document.title == "台積電 2026 年報"


def test_company_filing_pdf_text_extraction(monkeypatch) -> None:
    import pypdf

    class FakePage:
        def __init__(self, text: str) -> None:
            self.text = text

        def extract_text(self) -> str:
            return self.text

    monkeypatch.setattr(
        pypdf,
        "PdfReader",
        lambda _content: SimpleNamespace(
            pages=[
                FakePage("台積電 2026 年報"),
                FakePage("AI/HPC 需求與風險因素"),
            ]
        ),
    )

    assert "台積電 2026 年報" in extract_pdf_text(b"%PDF fake")


def test_company_filing_pdf_without_text_has_actionable_error(monkeypatch) -> None:
    import pypdf

    class BlankPage:
        def extract_text(self) -> str:
            return ""

    monkeypatch.setattr(
        pypdf,
        "PdfReader",
        lambda _content: SimpleNamespace(pages=[BlankPage()]),
    )

    try:
        extract_pdf_text(b"%PDF fake")
    except ValueError as exc:
        assert str(exc) == PDF_IMPORT_NO_TEXT_MESSAGE
        assert "OCR" in str(exc)
        assert "文字版文件" in str(exc)
    else:
        raise AssertionError("PDF without extractable text should provide OCR guidance")


def test_company_filing_url_validation_blocks_local_targets() -> None:
    validate_public_document_url("https://mops.twse.com.tw/server-java/t57sb01?co_id=2330")

    for url in [
        "file:///etc/passwd",
        "http://localhost:8000/internal",
        "http://127.0.0.1/internal",
        "http://192.168.1.10/report",
        "http://10.0.0.8/report",
        "http://example.local/report",
    ]:
        try:
            validate_public_document_url(url)
        except ValueError:
            continue
        raise AssertionError(f"unsafe URL should be rejected: {url}")


def test_fetched_company_filing_content_validation() -> None:
    valid = NewsFetcher.from_manual_text(
        title="台積電 2026 年報",
        text="台積電 2026 年報揭露 AI/HPC 需求、資本支出與風險因素。" * 8,
    )
    validate_fetched_company_filing_document(valid, "2330", "台積電", "annual_report")

    cases = [
        NewsFetcher.from_manual_text(title="短頁", text="台積電 年報"),
        NewsFetcher.from_manual_text(title="登入頁", text="請登入後查看文件內容。" * 20),
        NewsFetcher.from_manual_text(title="台積電 新聞", text="台積電 今日股價上漲，市場關注短線表現。" * 8),
    ]
    for document in cases:
        try:
            validate_fetched_company_filing_document(document, "2330", "台積電", "annual_report")
        except ValueError:
            continue
        raise AssertionError(f"invalid fetched document should be rejected: {document.title}")
