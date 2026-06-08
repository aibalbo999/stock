from __future__ import annotations

from contextlib import contextmanager
from datetime import date

from app.data_sources.company_filings import CompanyFilingFetcher
from app.models.schemas import NewsDocument, Source
from app.services.candidate_revalidation import (
    CandidateRevalidationService,
    apply_company_filing_gate_to_candidate_payload,
    candidate_revalidation_queries,
    collect_revalidation_documents,
    mark_unavailable_candidates_after_revalidation,
    preserve_previous_supported_candidates,
)
from app.services.persistence import CompanyFilingRepository
from app.services.topic_discovery import TopicDiscoveryPlan


def test_company_filing_gate_downgrades_supported_candidates_without_official_documents() -> None:
    gated = apply_company_filing_gate_to_candidate_payload(
        [
            {
                "ticker": "2330",
                "name": "台積電",
                "segment": "晶圓代工",
                "status": "evidence_supported",
                "evidence_confidence_score": 95,
                "evidence_confidence_label": "高",
                "validation_reason": "通過正式分析門檻",
                "promotion_eligible": True,
            },
            {
                "ticker": "2308",
                "name": "台達電",
                "segment": "電源",
                "status": "evidence_supported",
                "evidence_confidence_score": 92,
                "evidence_confidence_label": "高",
                "validation_reason": "通過正式分析門檻",
                "promotion_eligible": True,
            },
        ],
        sufficient_tickers_provider=lambda tickers: {"2330"},
    )

    assert gated[0]["status"] == "evidence_supported"
    assert gated[1]["status"] == "weak_evidence"
    assert gated[1]["promotion_eligible"] is False
    assert "系統尚未取得或解析到可用官方年報/法說文字" in gated[1]["validation_reason"]
    assert "不代表公司沒有公開年報" in gated[1]["validation_reason"]


def test_preserve_previous_supported_candidates_avoids_sampling_demotions() -> None:
    preserved = preserve_previous_supported_candidates(
        [
            {
                "ticker": "3037",
                "name": "欣興",
                "status": "weak_evidence",
                "validation_reason": "本次樣本只有單一來源",
            },
            {"ticker": "2421", "name": "建準", "status": "evidence_supported"},
        ],
        [
            {
                "ticker": "3037",
                "name": "欣興",
                "status": "evidence_supported",
                "validation_reason": "上一版通過正式分析門檻",
            }
        ],
    )

    by_ticker = {candidate["ticker"]: candidate for candidate in preserved}
    assert by_ticker["3037"]["status"] == "evidence_supported"
    assert "保留上一版正式分析" in by_ticker["3037"]["validation_reason"]
    assert by_ticker["3037"]["validation_reason"].count("本次補強重驗證未穩定重建既有正式證據") == 1
    assert by_ticker["2421"]["status"] == "evidence_supported"

    preserved_again = preserve_previous_supported_candidates(
        [{"ticker": "3037", "name": "欣興", "status": "weak_evidence"}],
        [by_ticker["3037"]],
    )

    assert preserved_again[0]["validation_reason"].count("本次補強重驗證未穩定重建既有正式證據") == 1


def test_preserve_previous_supported_candidates_does_not_keep_stale_evidence() -> None:
    preserved = preserve_previous_supported_candidates(
        [
            {
                "ticker": "3059",
                "name": "華晶科",
                "status": "weak_evidence",
                "validation_reason": "本次只找到偏舊資料",
            }
        ],
        [
            {
                "ticker": "3059",
                "name": "華晶科",
                "status": "evidence_supported",
                "latest_evidence_date": "2025-08-08",
                "validation_reason": "上一版通過正式分析門檻",
            }
        ],
    )

    assert preserved[0]["status"] == "weak_evidence"
    assert "保留上一版正式分析" not in preserved[0]["validation_reason"]


def test_mark_unavailable_candidates_after_large_revalidation() -> None:
    candidates = mark_unavailable_candidates_after_revalidation(
        [
            {
                "ticker": "6235",
                "name": "華孚",
                "status": "needs_evidence",
                "evidence_count": 0,
                "promotion_eligible": False,
            },
            {
                "ticker": "2359",
                "name": "所羅門",
                "status": "weak_evidence",
                "evidence_count": 1,
                "evidence_source_count": 1,
                "promotion_eligible": False,
            },
        ],
        document_count=500,
    )

    assert candidates[0]["status"] == "evidence_unavailable"
    assert "已自動補查 500 份" in candidates[0]["validation_reason"]
    assert candidates[0]["promotion_eligible"] is False
    assert candidates[1]["status"] == "evidence_limited"
    assert "補查完成但未升格" in candidates[1]["validation_reason"]


def test_revalidate_candidate_whitelist_prioritizes_company_filings_before_news_limit() -> None:
    plan = {
        "subtopics": [],
        "candidate_companies": [
            {
                "ticker": "6235",
                "name": "華孚",
                "segment": "鎂鋁合金機構件",
                "rationale": "輕量化金屬機構件可用於機器人",
                "evidence_keywords": ["鎂鋁合金", "機構件", "機器人"],
            }
        ],
    }
    unrelated_documents = [
        NewsDocument(
            id=f"n-{index}",
            title=f"一般產業新聞 {index}",
            text="AI 產業鏈與資料中心新聞，討論雲端伺服器與記憶體需求。",
            source=Source(title="news", publisher="News", published_at=date(2026, 5, 1)),
        )
        for index in range(20)
    ]
    filing_document = CompanyFilingFetcher.from_manual_text(
        ticker="6235",
        company_name="華孚",
        document_type="annual_report",
        title="華孚 股東會年報",
        text="6235 華孚 年報揭露鎂鋁合金機構件、輕量化、自動化與機器人應用。" * 8,
        publisher="公開資訊觀測站 MOPS",
        published_at=date(2026, 4, 30),
        url="https://doc.twse.com.tw/pdf/6235.pdf",
    )
    original_company_filing_repository = CompanyFilingRepository

    class FakeNewsRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def search_documents(self, query: str, limit: int = 20):
            return unrelated_documents[:limit]

        def latest_documents(self, limit: int = 20):
            return unrelated_documents[:limit]

    class FakeCompanyFilingRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def latest_by_tickers(self, tickers, limit_per_ticker=4):
            return [filing_document] if "6235" in tickers else []

        @staticmethod
        def to_news_document(document):
            return original_company_filing_repository.to_news_document(document)

    @contextmanager
    def fake_session_scope():
        yield object()

    service = CandidateRevalidationService(
        session_scope_factory=fake_session_scope,
        news_repository_cls=FakeNewsRepository,
        company_filing_repository_cls=FakeCompanyFilingRepository,
    )

    result = service.revalidate_candidate_whitelist(
        {"discovery": {"plan": plan}, "request": {"topic": "機器人 產業鏈"}},
        plan["candidate_companies"],
        limit=5,
    )

    candidate = result["candidate_whitelist"][0]
    assert result["company_filing_document_count"] == 1
    assert candidate["evidence_count"] == 1
    assert candidate["status"] == "weak_evidence"
    assert "資料不足排除" not in candidate["validation_reason"]


def test_candidate_revalidation_queries_are_company_specific() -> None:
    plan = TopicDiscoveryPlan.model_validate(
        {
            "subtopics": [
                {
                    "name": "液冷散熱",
                    "required_evidence": ["水冷訂單", "機櫃功耗"],
                }
            ],
            "candidate_companies": [
                {
                    "ticker": "3324",
                    "name": "雙鴻",
                    "segment": "散熱模組",
                    "rationale": "",
                    "evidence_keywords": ["液冷", "AI 伺服器"],
                }
            ],
        }
    )

    queries = candidate_revalidation_queries(plan, "AI 產業鏈")

    assert any("3324" in query and "雙鴻" in query and "AI 產業鏈" in query for query in queries)
    assert any("液冷散熱" in query and "水冷訂單" in query for query in queries)


def test_collect_revalidation_documents_dedupes_and_includes_latest_documents() -> None:
    document = NewsDocument(
        id="doc-1",
        title="雙鴻 液冷散熱",
        text="雙鴻 AI 伺服器液冷散熱。",
        source=Source(title="雙鴻 液冷散熱"),
    )

    class FakeRepository:
        def __init__(self) -> None:
            self.queries = []

        def search_documents(self, query: str, limit: int = 20) -> list[NewsDocument]:
            self.queries.append(query)
            return [document, document]

        def latest_documents(self, limit: int = 20) -> list[NewsDocument]:
            return [
                NewsDocument(
                    id="doc-2",
                    title="建準 散熱風扇",
                    text="建準 機器人與 AI 散熱。",
                    source=Source(title="建準 散熱風扇"),
                )
            ]

    repository = FakeRepository()

    documents = collect_revalidation_documents(repository, ["3324 雙鴻", "散熱模組"], 10)

    assert repository.queries == ["3324 雙鴻", "散熱模組"]
    assert [document.title for document in documents] == ["雙鴻 液冷散熱", "建準 散熱風扇"]
