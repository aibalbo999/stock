from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app.data_sources.news import NewsFetcher
from app.models.schemas import ReportRequest
from app.services import report_document_matching
from app.services.entity_mapping import EntityMapper
from app.services.report_generator import ReportGenerator
from app.services.whitelist import SupplyChainWhitelist


def test_document_matches_prefer_persisted_entity_metadata_over_text_guessing() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "3017",
                "name": "奇鋐",
                "segment": "散熱模組",
                "status": "evidence_supported",
            }
        ]
    )
    document = NewsFetcher.from_manual_text(
        title="液冷散熱需求升溫",
        text="AI 伺服器液冷散熱需求升溫。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    ).model_copy(update={"entity_tickers": ["3017"], "entity_names": ["奇鋐"]})
    generator = object.__new__(ReportGenerator)
    generator.whitelist = whitelist
    generator.mapper = SimpleNamespace(
        match_document=lambda doc: (_ for _ in ()).throw(AssertionError("metadata should be used"))
    )
    generator._document_match_cache = {}

    matches = ReportGenerator._document_matches(generator, document)

    assert [(match.ticker, match.name, match.matched_alias) for match in matches] == [
        ("3017", "奇鋐", "metadata")
    ]


def test_document_matching_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    document_mixin_source = Path("app/services/report_generator_document.py").read_text()
    matching_source = Path("app/services/report_document_matching.py").read_text()
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "3017",
                "name": "奇鋐",
                "segment": "散熱模組",
                "status": "evidence_supported",
            }
        ]
    )
    document = NewsFetcher.from_manual_text(
        title="奇鋐液冷散熱",
        text="奇鋐液冷散熱需求升溫。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    ).model_copy(update={"entity_tickers": ["3017"], "entity_names": ["奇鋐"]})
    generator = object.__new__(ReportGenerator)
    generator.whitelist = whitelist

    assert "ReportGeneratorDocumentMixin" in generator_source
    assert "report_document_matching" not in generator_source
    assert "from app.services import" in document_mixin_source
    assert "report_document_matching" in document_mixin_source
    assert "def _document_matches(" in document_mixin_source
    assert "def document_matches(" in matching_source
    assert "def document_metadata_matches(" in matching_source
    assert 'matched_alias="metadata"' not in generator_source
    assert generator._document_metadata_matches(document) == report_document_matching.document_metadata_matches(
        document,
        whitelist,
    )


def test_evidence_ranking_expands_topic_with_company_aliases() -> None:
    generator = object.__new__(ReportGenerator)
    generator.whitelist = SupplyChainWhitelist()
    generator.mapper = EntityMapper(generator.whitelist)
    generator.risk_analyzer = None
    request = ReportRequest(topic="AI 產業鏈", tickers=["2382"])
    related = NewsFetcher.from_manual_text(
        title="廣達 AI 伺服器出貨成長",
        text="廣達電腦 AI 伺服器出貨成長，法人看好後續需求。",
        publisher="測試新聞",
        published_at=date(2026, 5, 24),
    )
    unrelated = NewsFetcher.from_manual_text(
        title="大盤震盪整理",
        text="市場觀望氣氛濃厚。",
        publisher="測試新聞",
        published_at=date(2026, 5, 24),
    )

    documents = generator._rank_evidence_documents(request, [unrelated, related])

    assert documents == [related]


def test_evidence_ranking_uses_dynamic_evidence_keywords_without_entity_match() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "6669",
                "name": "緯穎",
                "segment": "AI 伺服器",
                "rationale": "",
                "evidence_keywords": ["資料中心"],
                "evidence_count": 1,
                "evidence_titles": [],
                "status": "evidence_supported",
            }
        ]
    )
    generator = object.__new__(ReportGenerator)
    generator.whitelist = whitelist
    generator.mapper = EntityMapper(whitelist)
    request = ReportRequest(topic="AI 產業鏈", tickers=["6669"])
    keyword_only = NewsFetcher.from_manual_text(
        title="資料中心需求成長",
        text="資料中心需求帶動 AI 基礎建設。",
        publisher="測試新聞",
        published_at=date(2026, 5, 24),
    )

    documents = generator._rank_evidence_documents(request, [keyword_only])

    assert documents == [keyword_only]
    assert generator._related_documents("6669", documents) == []


def test_evidence_ranking_excludes_sources_with_unrelated_entity_metadata() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "2308",
                "name": "台達電",
                "segment": "電源與散熱",
                "status": "evidence_supported",
                "evidence_keywords": ["電源", "資料中心"],
            },
            {
                "ticker": "2301",
                "name": "光寶科",
                "segment": "電源管理",
                "status": "evidence_supported",
                "evidence_keywords": ["電源", "資料中心"],
            },
        ]
    )
    generator = object.__new__(ReportGenerator)
    generator.whitelist = whitelist
    generator.mapper = EntityMapper(whitelist)
    request = ReportRequest(topic="AI 電源", tickers=["2308"])
    wrong_company = NewsFetcher.from_manual_text(
        title="光寶科 AI 電源出貨升溫",
        text="光寶科 AI 伺服器電源需求增加，台達電同業也受市場關注。",
        publisher="測試新聞A",
        published_at=date(2026, 5, 25),
    ).model_copy(update={"entity_tickers": ["2301"], "entity_names": ["光寶科"]})
    right_company = NewsFetcher.from_manual_text(
        title="台達電 AI 電源出貨升溫",
        text="台達電 AI 伺服器電源與資料中心需求增加。",
        publisher="測試新聞B",
        published_at=date(2026, 5, 24),
    ).model_copy(update={"entity_tickers": ["2308"], "entity_names": ["台達電"]})

    documents = generator._rank_evidence_documents(request, [wrong_company, right_company])

    assert documents == [right_company]


def test_formal_sources_exclude_investor_forum_posts_and_blogs() -> None:
    forum = NewsFetcher.from_manual_text(
        title="1815 富喬- 追買低檔群創也不要去追高高檔的富喬住套房-股市爆料同學會 - CMoney",
        text="富喬 AI 玻纖布 需求 成長，但這是散戶閒聊。",
        publisher="CMoney",
        published_at=date(2026, 5, 12),
    )
    blog = NewsFetcher.from_manual_text(
        title="富喬 4月營收創歷史新高 受高階薄布需求帶動",
        text="1815 富喬 4月營收創歷史新高，受 AI 高階薄布需求帶動。",
        publisher="CMoney投資網誌",
        published_at=date(2026, 5, 8),
    )
    formal = NewsFetcher.from_manual_text(
        title="富喬月營收創高 高階玻纖布需求升溫",
        text="1815 富喬月營收創高，高階玻纖布需求升溫。",
        publisher="經濟日報",
        published_at=date(2026, 5, 9),
    )

    sources = ReportGenerator._representative_sources([forum, blog, formal], limit=3)
    evidence = ReportGenerator._format_llm_evidence([forum, blog, formal])

    assert "股市爆料同學會" not in sources
    assert "股市爆料同學會" not in evidence
    assert "CMoney投資網誌" not in sources
    assert "CMoney投資網誌" not in evidence
    assert "富喬月營收創高" in sources
    assert "富喬月營收創高" in evidence


def test_rank_evidence_excludes_unmapped_wrong_company_when_requested_ticker_is_set() -> None:
    requested_document = NewsFetcher.from_manual_text(
        title="台達電 AI 電源需求成長",
        text="2308 台達電 AI 伺服器電源需求成長。",
        publisher="測試財經新聞",
        published_at=date(2026, 5, 20),
    )
    wrong_company_document = NewsFetcher.from_manual_text(
        title="光寶科 AI 電源出貨升溫",
        text="光寶科 AI 伺服器電源需求增加。",
        publisher="測試財經新聞",
        published_at=date(2026, 5, 21),
    )
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "2308",
                "name": "台達電",
                "segment": "電源與散熱",
                "status": "evidence_supported",
                "evidence_keywords": ["電源"],
            },
            {
                "ticker": "2301",
                "name": "光寶科",
                "segment": "電源與散熱",
                "status": "evidence_supported",
                "evidence_keywords": ["電源"],
            },
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)

    ranked = generator._rank_evidence_documents(
        ReportRequest(topic="AI 電源", tickers=["2308"]),
        [wrong_company_document, requested_document],
    )

    assert requested_document in ranked
    assert wrong_company_document not in ranked
