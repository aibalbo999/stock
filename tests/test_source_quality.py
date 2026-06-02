from datetime import date

from app.models.schemas import NewsDocument, Source
from app.services.source_quality import (
    filter_formal_evidence_documents,
    is_formal_evidence_document,
    remove_low_quality_investor_forum_lines,
    source_credibility_tier_for_document,
    summarize_source_credibility,
)


def test_filter_formal_evidence_documents_excludes_forum_marker_in_text() -> None:
    formal = NewsDocument(
        id="formal",
        title="台達電月營收創同期高",
        text="公司公告月營收與資料中心電源業務成長。",
        source=Source(title="台達電月營收創同期高", publisher="公開資訊觀測站", published_at=date(2026, 5, 10)),
    )
    forum_text = NewsDocument(
        id="forum-text",
        title="富喬投資討論",
        text="散戶閒聊：追買低檔群創也不要去追高高檔的富喬住套房。",
        source=Source(title="富喬投資討論", publisher="CMoney", published_at=date(2026, 5, 11)),
    )

    filtered = filter_formal_evidence_documents([formal, forum_text])

    assert [document.id for document in filtered] == ["formal"]


def test_filter_formal_evidence_documents_excludes_cmoney_forum_url_and_chatty_quote() -> None:
    formal = NewsDocument(
        id="formal",
        title="東元智慧製造接單動能",
        text="東元公告智慧製造與機電整合訂單進度。",
        source=Source(title="東元智慧製造接單動能", publisher="經濟日報", published_at=date(2026, 5, 10)),
    )
    forum = NewsDocument(
        id="forum-url",
        title="1504 東元 一堆看新聞做股票不是真的分析走勢",
        text="網友抱怨：一堆看新聞做股票，不是真的去分析走勢。",
        source=Source(
            title="1504 東元 討論串",
            publisher="CMoney",
            published_at=date(2026, 5, 11),
            url="https://www.cmoney.tw/forum/stock/1504",
        ),
    )

    filtered = filter_formal_evidence_documents([formal, forum])

    assert [document.id for document in filtered] == ["formal"]


def test_filter_formal_evidence_documents_excludes_investment_blogs() -> None:
    formal = NewsDocument(
        id="formal",
        title="富喬月營收創高",
        text="1815 富喬月營收與高階玻纖布需求成長。",
        source=Source(title="富喬月營收創高", publisher="經濟日報", published_at=date(2026, 5, 11)),
    )
    blog = NewsDocument(
        id="blog",
        title="富喬還能追嗎",
        text="投資網誌評論。",
        source=Source(title="富喬還能追嗎", publisher="CMoney投資網誌", published_at=date(2026, 5, 12)),
    )

    filtered = filter_formal_evidence_documents([formal, blog])

    assert [document.id for document in filtered] == ["formal"]
    assert is_formal_evidence_document(formal) is True
    assert is_formal_evidence_document(blog) is False


def test_remove_low_quality_forum_lines_uses_url_markers() -> None:
    text = "\n".join(
        [
            "- 2026-05-10 經濟日報《東元智慧製造接單》",
            "- 2026-05-11 CMoney《東元討論串》（https://www.cmoney.tw/forum/stock/1504）",
        ]
    )

    cleaned = remove_low_quality_investor_forum_lines(text)

    assert "經濟日報" in cleaned
    assert "cmoney.tw/forum" not in cleaned


def test_remove_low_quality_forum_lines_also_removes_investment_blogs() -> None:
    text = "\n".join(
        [
            "- 2026-05-10 經濟日報《富喬月營收創高》",
            "- 2026-05-11 CMoney投資網誌《富喬還能追嗎》",
        ]
    )

    cleaned = remove_low_quality_investor_forum_lines(text)

    assert "經濟日報" in cleaned
    assert "CMoney投資網誌" not in cleaned


def test_remove_low_quality_forum_fragments_preserves_report_table_row() -> None:
    text = (
        "| 1504 東元 | 15 |  | 2026-05-26 | "
        "2026-05-26 CMoney《1504 東元 - 一堆看新聞做股票-股市爆料同學會》；"
        "2026-05-25 富聯網《東元受邀參加法人說明會》 |"
    )

    cleaned = remove_low_quality_investor_forum_lines(text)

    assert "| 1504 東元 |" in cleaned
    assert "股市爆料同學會" not in cleaned
    assert "2026-05-25 富聯網" in cleaned
    assert "| 2026-05-25 |" in cleaned


def test_source_credibility_distinguishes_official_news_and_investment_blogs() -> None:
    official = NewsDocument(
        id="official",
        title="股東會年報",
        text="公開資訊觀測站年報。",
        source=Source(title="股東會年報", publisher="公開資訊觀測站 MOPS", published_at=date(2026, 5, 10)),
    )
    news = NewsDocument(
        id="news",
        title="台達電月營收創同期高",
        text="台達電月營收年增。",
        source=Source(title="台達電月營收創同期高", publisher="經濟日報", published_at=date(2026, 5, 11)),
    )
    blog = NewsDocument(
        id="blog",
        title="台達電還能追嗎",
        text="投資網誌評論。",
        source=Source(title="台達電還能追嗎", publisher="CMoney投資網誌", published_at=date(2026, 5, 12)),
    )

    summary = summarize_source_credibility([official, news, blog])

    assert source_credibility_tier_for_document(official) == "official"
    assert source_credibility_tier_for_document(news) == "established_news"
    assert source_credibility_tier_for_document(blog) == "investment_blog"
    assert summary["high_credibility_count"] == 2
    assert summary["low_credibility_count"] == 1
