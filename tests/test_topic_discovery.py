from datetime import date

from app.data_sources.news import NewsFetcher
from app.services.topic_discovery import TopicDiscoveryService
from app.services.whitelist import SupplyChainWhitelist


def test_parse_topic_discovery_plan() -> None:
    raw = """
    {
      "subtopics": [
        {
          "name": "CoWoS",
          "rationale": "AI GPU supply chain bottleneck",
          "search_queries": ["台積電 CoWoS AI"]
        }
      ],
      "candidate_companies": [
        {
          "ticker": "2330",
          "name": "台積電",
          "segment": "晶圓代工",
          "rationale": "CoWoS and foundry exposure",
          "evidence_keywords": ["CoWoS", "先進封裝"]
        }
      ]
    }
    """

    plan = TopicDiscoveryService.parse_plan(raw)

    assert plan.subtopics[0].name == "CoWoS"
    assert plan.candidate_companies[0].ticker == "2330"


def test_google_news_urls_deduplicate_queries() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {"name": "a", "rationale": "", "search_queries": ["台積電 CoWoS", "台積電 CoWoS"]}
          ],
          "candidate_companies": [
            {
              "ticker": "2330",
              "name": "台積電",
              "segment": "晶圓代工",
              "rationale": "CoWoS",
              "evidence_keywords": ["CoWoS"]
            }
          ]
        }
        """
    )

    urls = TopicDiscoveryService().google_news_urls(plan, include_international=False)

    assert len(urls) == 2
    assert "news.google.com/rss/search" in urls[0]
    assert "hl=zh-TW" in urls[0]
    assert any("2330" in url for url in urls)


def test_google_news_urls_can_add_international_context_queries() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {"name": "AI server", "rationale": "", "search_queries": ["AI 伺服器"]}
          ],
          "candidate_companies": []
        }
        """
    )

    urls = TopicDiscoveryService().google_news_urls(plan, include_international=True, max_urls=4)

    assert len(urls) == 4
    assert any("global+market" in url for url in urls)


def test_supplemental_google_news_urls_focuses_on_unsupported_candidates() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {"name": "AI server", "rationale": "需求追蹤", "search_queries": ["AI 伺服器"]}
          ],
          "candidate_companies": [
            {
              "ticker": "2330",
              "name": "台積電",
              "segment": "晶圓代工",
              "rationale": "CoWoS",
              "evidence_keywords": ["CoWoS"]
            },
            {
              "ticker": "2382",
              "name": "廣達",
              "segment": "AI 伺服器",
              "rationale": "出貨",
              "evidence_keywords": ["GB200"]
            }
          ]
        }
        """
    )
    service = TopicDiscoveryService()
    validated = service.validate_candidates(
        plan,
        [
            NewsFetcher.from_manual_text(
                title="台積電 CoWoS",
                text="台積電 CoWoS 產能。",
                publisher="test-a",
                published_at=date(2026, 5, 24),
            ),
            NewsFetcher.from_manual_text(
                title="台積電 CoWoS 供應鏈",
                text="台積電 CoWoS 產能持續擴張。",
                publisher="test-b",
                published_at=date(2026, 5, 24),
            )
        ],
    )

    urls = service.supplemental_google_news_urls(
        plan,
        validated,
        include_international=True,
        max_urls=5,
    )

    assert urls
    assert any("2382" in url or "%E5%BB%A3%E9%81%94" in url for url in urls)
    assert not any("2330+%E5%8F%B0%E7%A9%8D%E9%9B%BB" in url for url in urls)


def test_validate_candidates_marks_evidence_supported() -> None:
    service = TopicDiscoveryService()
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [],
          "candidate_companies": [
            {
              "ticker": "2330",
              "name": "台積電",
              "segment": "晶圓代工",
              "rationale": "CoWoS",
              "evidence_keywords": ["CoWoS"]
            }
          ]
        }
        """
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 產能擴張",
            text="台積電 CoWoS 產能擴張支撐 AI 需求。",
            publisher="test-a",
            published_at=date(2026, 5, 24),
        ),
        NewsFetcher.from_manual_text(
            title="台積電先進封裝擴產",
            text="台積電 CoWoS 與先進封裝需求升溫。",
            publisher="test-b",
            published_at=date(2026, 5, 24),
        ),
    ]

    candidates = service.validate_candidates(plan, documents)

    assert candidates[0].status == "evidence_supported"
    assert candidates[0].evidence_count == 2
    assert candidates[0].evidence_source_count == 2


def test_validate_candidates_marks_single_source_as_weak_evidence() -> None:
    service = TopicDiscoveryService()
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [],
          "candidate_companies": [
            {
              "ticker": "2330",
              "name": "台積電",
              "segment": "晶圓代工",
              "rationale": "CoWoS",
              "evidence_keywords": ["CoWoS"]
            }
          ]
        }
        """
    )
    document = NewsFetcher.from_manual_text(
        title="台積電 CoWoS 產能擴張",
        text="台積電 CoWoS 產能擴張支撐 AI 需求。",
        publisher="test",
        published_at=date(2026, 5, 24),
    )

    candidates = service.validate_candidates(plan, [document])

    assert candidates[0].status == "weak_evidence"
    assert candidates[0].evidence_count == 1
    assert candidates[0].evidence_source_count == 1


def test_validate_candidates_requires_company_entity_evidence() -> None:
    service = TopicDiscoveryService()
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [],
          "candidate_companies": [
            {
              "ticker": "6669",
              "name": "緯穎",
              "segment": "AI 伺服器",
              "rationale": "資料中心伺服器",
              "evidence_keywords": ["資料中心", "AI 伺服器"]
            }
          ]
        }
        """
    )
    document = NewsFetcher.from_manual_text(
        title="AI 伺服器需求成長",
        text="資料中心帶動 AI 伺服器需求，但未提及特定公司。",
        publisher="test",
        published_at=date(2026, 5, 24),
    )

    candidates = service.validate_candidates(plan, [document])

    assert candidates[0].status == "needs_evidence"
    assert candidates[0].evidence_count == 0


def test_validate_candidates_requires_topic_context_evidence() -> None:
    service = TopicDiscoveryService()
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [],
          "candidate_companies": [
            {
              "ticker": "2330",
              "name": "台積電",
              "segment": "晶圓代工",
              "rationale": "CoWoS",
              "evidence_keywords": ["CoWoS", "先進封裝"]
            }
          ]
        }
        """
    )
    document = NewsFetcher.from_manual_text(
        title="台積電董事會通過例行議案",
        text="台積電今日公告董事會決議，未提及本次分析主題。",
        publisher="test",
        published_at=date(2026, 5, 24),
    )

    candidates = service.validate_candidates(plan, [document])

    assert candidates[0].status == "needs_evidence"
    assert candidates[0].evidence_count == 0


def test_validate_candidates_accepts_static_whitelist_aliases() -> None:
    service = TopicDiscoveryService()
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [],
          "candidate_companies": [
            {
              "ticker": "2382",
              "name": "廣達",
              "segment": "AI 伺服器",
              "rationale": "AI server",
              "evidence_keywords": ["AI 伺服器"]
            }
          ]
        }
        """
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="廣達電腦 AI 伺服器需求成長",
            text="廣達電腦受惠 AI 伺服器需求。",
            publisher="test-a",
            published_at=date(2026, 5, 24),
        ),
        NewsFetcher.from_manual_text(
            title="廣達 AI 伺服器訂單",
            text="廣達 AI 伺服器訂單維持高檔。",
            publisher="test-b",
            published_at=date(2026, 5, 24),
        ),
    ]

    candidates = service.validate_candidates(plan, documents)

    assert candidates[0].status == "evidence_supported"


def test_dynamic_whitelist_uses_only_evidence_supported_candidates() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "6669",
                "name": "緯穎",
                "segment": "AI 伺服器",
                "rationale": "",
                "evidence_keywords": [],
                "evidence_count": 2,
                "evidence_titles": [],
                "status": "evidence_supported",
            },
            {
                "ticker": "9999",
                "name": "測試公司",
                "segment": "AI 伺服器",
                "rationale": "",
                "evidence_keywords": [],
                "evidence_count": 0,
                "evidence_titles": [],
                "status": "needs_evidence",
            },
        ]
    )

    assert whitelist.allowed_tickers() == {"6669"}
    assert "6669 緯穎" in whitelist.as_prompt_context()


def test_dynamic_whitelist_keeps_evidence_keywords_without_promoting_unverified_companies() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "6669",
                "name": "緯穎",
                "segment": "AI 伺服器",
                "rationale": "",
                "evidence_keywords": ["AI 伺服器", "資料中心"],
                "evidence_count": 2,
                "evidence_titles": [],
                "status": "evidence_supported",
            },
            {
                "ticker": "9999",
                "name": "測試公司",
                "segment": "AI 伺服器",
                "rationale": "",
                "evidence_keywords": ["AI 伺服器"],
                "evidence_count": 0,
                "evidence_titles": [],
                "status": "needs_evidence",
            },
        ]
    )

    companies = whitelist.companies()

    assert len(companies) == 1
    assert companies[0].evidence_keywords == ["AI 伺服器", "資料中心"]
    assert "證據關鍵字：AI 伺服器、資料中心" in whitelist.as_prompt_context()
