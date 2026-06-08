from datetime import date

from app.data_sources.news import NewsFetcher
from app.services.topic_discovery import TopicDiscoveryService


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

    metadata = TopicDiscoveryService().google_news_urls(
        plan,
        include_international=False,
        include_metadata=True,
    )
    queries = [item["query"] for item in metadata]

    assert len(queries) == len(set(queries))
    assert queries.count("台積電 CoWoS") == 1
    assert "news.google.com/rss/search" in metadata[0]["url"]
    assert "hl=zh-TW" in metadata[0]["url"]
    assert any("2330" in query for query in queries)


def test_google_news_urls_round_robin_candidate_queries() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [],
          "candidate_companies": [
            {"ticker": "2330", "name": "台積電", "segment": "先進封裝", "rationale": "CoWoS", "evidence_keywords": ["CoWoS"]},
            {"ticker": "2382", "name": "廣達", "segment": "AI 伺服器", "rationale": "出貨", "evidence_keywords": ["GB200"]},
            {"ticker": "3231", "name": "緯創", "segment": "AI 伺服器", "rationale": "訂單", "evidence_keywords": ["CSP"]}
          ]
        }
        """
    )

    metadata = TopicDiscoveryService().google_news_urls(
        plan,
        include_international=False,
        max_urls=9,
        include_metadata=True,
    )
    first_round_queries = [item["query"] for item in metadata[:3]]
    source_intents = [item["source_intent"] for item in metadata]

    assert ["2330", "2382", "3231"] == [query.split()[0] for query in first_round_queries]
    assert source_intents[:3] == ["industry_news", "industry_news", "industry_news"]
    assert "company_disclosure" in source_intents
    assert "financial_metrics" in source_intents


def test_google_news_urls_include_research_task_terms() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "液冷散熱",
              "rationale": "AI 機櫃功耗上升",
              "objective": "查核散熱技術轉換是否延遲出貨",
              "required_evidence": ["水冷訂單", "機櫃功耗"],
              "risk_focus": ["技術轉換", "交期延遲"],
              "search_queries": ["AI 伺服器 液冷"]
            }
          ],
          "candidate_companies": []
        }
        """
    )

    urls = TopicDiscoveryService().google_news_urls(plan, include_international=False, max_urls=2)

    assert any("%E6%B6%B2%E5%86%B7%E6%95%A3%E7%86%B1" in url for url in urls)
    assert any("%E6%B0%B4%E5%86%B7%E8%A8%82%E5%96%AE" in url for url in urls)


def test_google_news_urls_cover_each_subtopic_before_extra_queries() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "AI 伺服器需求",
              "required_evidence": ["CSP 資本支出"],
              "risk_focus": ["需求下修"],
              "search_queries": ["AI 伺服器 出貨", "cloud capex AI server"]
            },
            {
              "name": "液冷散熱與電源",
              "required_evidence": ["液冷訂單"],
              "risk_focus": ["功耗瓶頸"],
              "search_queries": ["液冷散熱 電源 AI 伺服器", "liquid cooling power AI server"]
            },
            {
              "name": "地緣政治與電力",
              "required_evidence": ["電網供給"],
              "risk_focus": ["出口管制"],
              "search_queries": ["AI data center power grid", "export control AI chip"]
            }
          ],
          "candidate_companies": []
        }
        """
    )

    metadata = TopicDiscoveryService().google_news_urls(
        plan,
        include_international=False,
        max_urls=6,
        include_metadata=True,
    )
    queries = [item["query"] for item in metadata]

    assert any("AI 伺服器需求" in query for query in queries)
    assert any("液冷散熱與電源" in query for query in queries)
    assert any("地緣政治與電力" in query for query in queries)


def test_coverage_gap_queries_add_missing_research_dimensions() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "需求成長",
              "rationale": "雲端資本支出",
              "objective": "確認需求成長",
              "required_evidence": ["訂單"],
              "risk_focus": ["需求下修"],
              "search_queries": ["AI 伺服器 訂單"]
            }
          ],
          "candidate_companies": [
            {
              "ticker": "2382",
              "name": "廣達",
              "segment": "AI 伺服器",
              "rationale": "出貨",
              "evidence_keywords": ["AI 伺服器"]
            }
          ]
        }
        """
    )
    quality = TopicDiscoveryService.evaluate_plan_quality(plan)

    queries = TopicDiscoveryService.coverage_gap_queries("AI 產業鏈", quality)

    assert "AI 產業鏈 供給 產能 良率 瓶頸" in queries
    assert "AI 產業鏈 營收 毛利 獲利" in queries
    assert "AI 產業鏈 股價 估值 本益比" in queries


def test_query_quality_gap_queries_add_aligned_and_international_searches() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "液冷散熱",
              "rationale": "AI 機櫃功耗上升",
              "objective": "確認液冷訂單是否支撐散熱成長",
              "required_evidence": ["水冷訂單", "營收"],
              "risk_focus": ["技術轉換延遲"],
              "search_queries": ["AI"]
            }
          ],
          "candidate_companies": []
        }
        """
    )
    quality = TopicDiscoveryService.evaluate_plan_quality(plan)

    queries = TopicDiscoveryService.query_quality_gap_queries("AI 產業鏈", plan, quality)

    assert "AI 產業鏈 液冷散熱 水冷訂單 營收 技術轉換延遲" in queries
    assert "AI 產業鏈 液冷散熱 水冷訂單 營收 技術轉換延遲 global market" in queries


def test_google_news_urls_include_coverage_gap_queries() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "需求成長",
              "rationale": "訂單",
              "objective": "確認需求",
              "required_evidence": ["訂單"],
              "risk_focus": ["需求下修"],
              "search_queries": ["AI 伺服器 訂單"]
            }
          ],
          "candidate_companies": []
        }
        """
    )

    urls = TopicDiscoveryService().google_news_urls(
        plan,
        include_international=False,
        max_urls=8,
        topic="AI 產業鏈",
    )

    assert any("%E8%82%A1%E5%83%B9" in url and "%E4%BC%B0%E5%80%BC" in url for url in urls)


def test_google_news_urls_include_query_quality_gap_metadata() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "液冷散熱",
              "rationale": "AI 機櫃功耗上升",
              "objective": "確認液冷訂單是否支撐散熱成長",
              "required_evidence": ["水冷訂單"],
              "risk_focus": ["技術轉換延遲"],
              "search_queries": ["AI"]
            }
          ],
          "candidate_companies": []
        }
        """
    )

    metadata = TopicDiscoveryService().google_news_urls(
        plan,
        include_international=False,
        max_urls=10,
        topic="AI 產業鏈",
        include_metadata=True,
    )

    assert any(item["source_type"] == "query_quality_gap" for item in metadata)
    assert any(item["evidence_type"] == "查詢品質補強" for item in metadata)


def test_google_news_urls_can_return_query_metadata() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "需求成長",
              "rationale": "訂單",
              "objective": "確認需求",
              "required_evidence": ["訂單"],
              "risk_focus": ["需求下修"],
              "search_queries": ["AI 伺服器 訂單"]
            }
          ],
          "candidate_companies": []
        }
        """
    )

    metadata = TopicDiscoveryService().google_news_urls(
        plan,
        include_international=False,
        max_urls=4,
        topic="AI 產業鏈",
        include_metadata=True,
    )

    assert all("url" in item and "query" in item and "source_type" in item for item in metadata)
    assert any(item["source_type"] == "research_task" for item in metadata)
    assert any(item["source_type"] == "coverage_gap" for item in metadata)
    assert all(
        "hypothesis" in item and "evidence_type" in item and "language" in item for item in metadata
    )
    assert all("source_intent" in item for item in metadata)
    assert metadata[0]["hypothesis"] == "確認需求"
    assert metadata[0]["evidence_type"] in {"需求/成長", "風險/瓶頸"}
    assert metadata[0]["source_intent"] in {"industry_news", "company_disclosure"}


def test_google_news_query_metadata_labels_language_and_hypothesis() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "CSP 資本支出",
              "objective": "驗證雲端資本支出是否支撐 AI 伺服器需求",
              "required_evidence": ["capex", "訂單"],
              "risk_focus": ["需求下修"],
              "search_queries": ["North American cloud AI server capex"]
            }
          ],
          "candidate_companies": [
            {
              "ticker": "2382",
              "name": "廣達",
              "segment": "AI 伺服器代工",
              "rationale": "ODM exposure",
              "evidence_keywords": ["AI server", "CSP"]
            }
          ]
        }
        """
    )

    metadata = TopicDiscoveryService().google_news_urls(
        plan,
        include_international=False,
        max_urls=4,
        include_metadata=True,
    )

    assert metadata[0]["hypothesis"] == "驗證雲端資本支出是否支撐 AI 伺服器需求"
    assert metadata[0]["language"] == "mixed"
    assert any(item["evidence_type"] == "候選公司證據" for item in metadata)


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
            ),
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


def test_supplemental_google_news_query_metadata_round_robin_weak_candidates() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [],
          "candidate_companies": [
            {"ticker": "2330", "name": "台積電", "segment": "先進封裝", "rationale": "CoWoS", "evidence_keywords": ["CoWoS"]},
            {"ticker": "2382", "name": "廣達", "segment": "AI 伺服器", "rationale": "出貨", "evidence_keywords": ["GB200"]},
            {"ticker": "3231", "name": "緯創", "segment": "AI 伺服器", "rationale": "訂單", "evidence_keywords": ["CSP"]}
          ]
        }
        """
    )

    metadata = TopicDiscoveryService().supplemental_google_news_query_metadata(
        plan,
        validated_candidates=[],
        include_international=False,
        max_urls=6,
    )
    first_round_queries = [item["query"] for item in metadata[:3]]

    assert ["2330", "2382", "3231"] == [query.split()[0] for query in first_round_queries]
    assert any("法說會 年報 月營收" in item["query"] for item in metadata)
    assert all(item["source_type"] == "supplemental" for item in metadata)


def test_supplemental_google_news_urls_include_subtopic_evidence_and_risk_terms() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "電力供給",
              "rationale": "資料中心耗電提升",
              "objective": "確認缺電是否限制投資",
              "required_evidence": ["電網負荷", "資料中心"],
              "risk_focus": ["缺電", "電價"],
              "search_queries": ["AI 資料中心 缺電"]
            }
          ],
          "candidate_companies": []
        }
        """
    )

    urls = TopicDiscoveryService().supplemental_google_news_urls(
        plan,
        [],
        include_international=False,
        max_urls=3,
    )

    assert any("%E9%9B%BB%E7%B6%B2%E8%B2%A0%E8%8D%B7" in url for url in urls)
    assert any("%E7%BC%BA%E9%9B%BB" in url for url in urls)


def test_supplemental_google_news_urls_can_focus_missing_subtopics() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "液冷散熱",
              "rationale": "功耗提升",
              "objective": "確認液冷訂單",
              "required_evidence": ["液冷訂單"],
              "risk_focus": ["認證延遲"],
              "search_queries": ["AI 伺服器 液冷"]
            },
            {
              "name": "出口管制",
              "rationale": "政策風險",
              "objective": "確認禁令",
              "required_evidence": ["出口管制"],
              "risk_focus": ["禁令"],
              "search_queries": ["export control AI chips"]
            }
          ],
          "candidate_companies": []
        }
        """
    )

    metadata = TopicDiscoveryService().supplemental_google_news_query_metadata(
        plan,
        [],
        include_international=False,
        max_urls=5,
        missing_subtopics=["出口管制"],
    )

    assert metadata
    assert all(
        "出口管制" in item["query"] or "export control" in item["query"] for item in metadata
    )
    assert not any("液冷散熱" in item["query"] for item in metadata)
