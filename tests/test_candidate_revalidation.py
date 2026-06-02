from datetime import date

from app.models.schemas import NewsDocument, Source
from app.services.candidate_revalidation import (
    apply_company_filing_gate_to_candidate_payload,
    collect_revalidation_documents,
    preserve_previous_supported_candidates,
    sanitize_candidate_low_quality_sources,
)


def test_candidate_revalidation_gate_requires_sufficient_company_filings() -> None:
    candidates = [
        {
            "ticker": "2330",
            "name": "台積電",
            "status": "evidence_supported",
            "evidence_confidence_score": 100,
            "validation_reason": "通過多來源證據",
        },
        {
            "ticker": "2308",
            "name": "台達電",
            "status": "evidence_supported",
            "evidence_confidence_score": 95,
            "validation_reason": "通過多來源證據",
        },
    ]

    gated = apply_company_filing_gate_to_candidate_payload(
        candidates,
        sufficient_tickers_provider=lambda tickers: {"2330"},
    )

    assert gated[0]["status"] == "evidence_supported"
    assert gated[1]["status"] == "weak_evidence"
    assert gated[1]["evidence_confidence_label"] == "中"
    assert "資料管線缺口" in gated[1]["validation_reason"]


def test_candidate_revalidation_gate_allows_strong_memory_candidates_to_skip_filing_gate() -> None:
    candidates = [
        {
            "ticker": "2408",
            "name": "南亞科",
            "segment": "DRAM 記憶體",
            "status": "evidence_supported",
            "promotion_eligible": True,
            "evidence_count": 5,
            "evidence_source_count": 4,
            "evidence_confidence_score": 90,
            "validation_reason": "通過多來源證據",
        }
    ]

    gated = apply_company_filing_gate_to_candidate_payload(
        candidates,
        sufficient_tickers_provider=lambda tickers: set(),
    )

    assert gated[0]["status"] == "evidence_supported"
    assert gated[0]["promotion_eligible"] is True


def test_candidate_revalidation_document_collection_dedupes_latest_documents() -> None:
    shared = NewsDocument(
        id="doc-1",
        title="3324 雙鴻 液冷散熱",
        text="雙鴻 液冷散熱 AI 伺服器。",
        source=Source(title="doc", publisher="news", published_at=date(2026, 5, 1)),
    )
    latest = NewsDocument(
        id="doc-2",
        title="3017 奇鋐 CDU",
        text="奇鋐 CDU 水冷。",
        source=Source(title="doc", publisher="news", published_at=date(2026, 5, 2)),
    )

    class FakeRepository:
        def search_documents(self, query: str, limit: int = 20):
            return [shared]

        def latest_documents(self, limit: int = 20):
            return [shared, latest]

    documents = collect_revalidation_documents(FakeRepository(), ["散熱"], 10)

    assert [document.id for document in documents] == ["doc-1", "doc-2"]


def test_candidate_revalidation_document_collection_excludes_forum_sources() -> None:
    formal = NewsDocument(
        id="formal",
        title="1504 東元智慧製造接單",
        text="東元智慧製造接單與機電整合需求升溫。",
        source=Source(title="formal", publisher="經濟日報", published_at=date(2026, 5, 2)),
    )
    forum = NewsDocument(
        id="forum",
        title="1504 東元 一堆看新聞做股票不是真的分析走勢",
        text="網友抱怨：一堆看新聞做股票。",
        source=Source(
            title="forum",
            publisher="CMoney",
            published_at=date(2026, 5, 2),
            url="https://www.cmoney.tw/forum/stock/1504",
        ),
    )

    class FakeRepository:
        def search_documents(self, query: str, limit: int = 20):
            return [forum, formal]

        def latest_documents(self, limit: int = 20):
            return [forum]

    documents = collect_revalidation_documents(FakeRepository(), ["東元"], 10)

    assert [document.id for document in documents] == ["formal"]


def test_candidate_revalidation_downgrades_supported_candidate_after_forum_sources_removed() -> None:
    sanitized = sanitize_candidate_low_quality_sources(
        [
            {
                "ticker": "1504",
                "name": "東元",
                "status": "evidence_supported",
                "promotion_eligible": True,
                "evidence_count": 2,
                "evidence_source_count": 2,
                "evidence_confidence_score": 100,
                "evidence_confidence_label": "高",
                "validation_reason": "通過多來源證據",
                "evidence_titles": [
                    "東元智慧製造接單",
                    "1504 東元 一堆看新聞做股票不是真的分析走勢",
                ],
                "evidence_sources": [
                    {
                        "title": "東元智慧製造接單",
                        "publisher": "經濟日報",
                        "published_at": "2026-05-02",
                    },
                    {
                        "title": "1504 東元 一堆看新聞做股票不是真的分析走勢",
                        "publisher": "CMoney",
                        "published_at": "2026-05-02",
                        "url": "https://www.cmoney.tw/forum/stock/1504",
                    },
                ],
            }
        ]
    )

    assert sanitized[0]["status"] == "weak_evidence"
    assert sanitized[0]["promotion_eligible"] is False
    assert sanitized[0]["evidence_confidence_label"] == "中"
    assert sanitized[0]["evidence_confidence_score"] == 74
    assert sanitized[0]["evidence_count"] == 1
    assert sanitized[0]["evidence_source_count"] == 1
    assert sanitized[0]["evidence_sources"][0]["publisher"] == "經濟日報"
    assert "不得進入配置" in sanitized[0]["validation_reason"]


def test_candidate_revalidation_removes_non_formal_titles_even_when_sources_are_clean() -> None:
    sanitized = sanitize_candidate_low_quality_sources(
        [
            {
                "ticker": "3324",
                "name": "雙鴻",
                "status": "evidence_supported",
                "promotion_eligible": True,
                "evidence_count": 3,
                "evidence_source_count": 2,
                "evidence_confidence_score": 100,
                "evidence_confidence_label": "高",
                "validation_reason": "通過多來源證據",
                "evidence_titles": [
                    "雙鴻 AI 水冷需求推動 - 經濟日報",
                    "【即時新聞】雙鴻元月營收創新高 - CMoney投資網誌",
                ],
                "evidence_sources": [
                    {
                        "title": "雙鴻 AI 水冷需求推動 - 經濟日報",
                        "publisher": "經濟日報",
                        "published_at": "2026-05-02",
                    },
                    {
                        "title": "雙鴻法人說明會",
                        "publisher": "公開資訊觀測站 MOPS",
                        "published_at": "2026-05-03",
                    },
                ],
            }
        ]
    )

    assert sanitized[0]["status"] == "evidence_supported"
    assert sanitized[0]["evidence_titles"] == ["雙鴻 AI 水冷需求推動 - 經濟日報"]
    assert "CMoney投資網誌" not in str(sanitized[0])
    assert "不列入信心與配置評估" in sanitized[0]["validation_reason"]


def test_candidate_revalidation_preserves_recent_previous_supported_candidate() -> None:
    preserved = preserve_previous_supported_candidates(
        [{"ticker": "3037", "name": "欣興", "status": "weak_evidence"}],
        [
            {
                "ticker": "3037",
                "name": "欣興",
                "status": "evidence_supported",
                "latest_evidence_date": "2026-05-20",
                "validation_reason": "上一版通過正式分析門檻",
            }
        ],
    )

    assert preserved[0]["status"] == "evidence_supported"
    assert "保留上一版正式分析" in preserved[0]["validation_reason"]
