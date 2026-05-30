from datetime import date

from app.data_sources.news import NewsFetcher
from app.services.entity_mapping import EntityMapper


def test_mapper_only_matches_whitelisted_companies() -> None:
    mapper = EntityMapper()

    matches = mapper.match_text("台積電 CoWoS 產能滿載，廣達 AI 伺服器拉貨；某某科技也受惠。")

    assert {(match.ticker, match.name) for match in matches} == {("2330", "台積電"), ("2382", "廣達")}


def test_filter_allowed_tickers_removes_non_whitelist() -> None:
    mapper = EntityMapper()

    assert mapper.filter_allowed_tickers(["2330", "9999", "3324"]) == ["2330", "3324"]


def test_release_notes_do_not_match_company_by_ticket_number_only() -> None:
    mapper = EntityMapper()
    document = NewsFetcher.from_manual_text(
        title="May 09, 2026",
        text="Issue 3037 updates cloud logging automation.",
        publisher="Google Cloud Release Notes",
        published_at=date(2026, 5, 9),
    )

    assert mapper.match_document(document) == []


def test_release_notes_can_match_when_named_company_is_present() -> None:
    mapper = EntityMapper()
    document = NewsFetcher.from_manual_text(
        title="May 09, 2026",
        text="台積電 2330 CoWoS 供應鏈資料整理。",
        publisher="Google Cloud Release Notes",
        published_at=date(2026, 5, 9),
    )

    matches = mapper.match_document(document)

    assert [(match.ticker, match.name) for match in matches] == [("2330", "台積電")]


def test_company_filing_matches_only_owner_company() -> None:
    mapper = EntityMapper()
    document = NewsFetcher.from_manual_text(
        title="股東會年報",
        text="股票代號：2330\n公司名稱：台積電\n文件類型：annual_report\n廣達與欣興為供應鏈合作對象。",
        publisher="公開資訊觀測站 MOPS",
        published_at=date(2026, 5, 19),
    ).model_copy(update={"id": "filing-test"})

    matches = mapper.match_document(document)

    assert [(match.ticker, match.name) for match in matches] == [("2330", "台積電")]
