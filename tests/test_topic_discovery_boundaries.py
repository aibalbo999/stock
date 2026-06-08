from datetime import date
from pathlib import Path

from app.data_sources.news import NewsFetcher
from app.services import (
    topic_discovery_candidate_queries,
    topic_discovery_candidates,
    topic_discovery_enrichment,
    topic_discovery_fallbacks,
    topic_discovery_gap_queries,
    topic_discovery_models,
    topic_discovery_news_queries,
    topic_discovery_prompts,
    topic_discovery_quality,
    topic_discovery_queries,
    topic_discovery_supplemental_queries,
)
from app.services.candidate_confidence import HIGH_CONFIDENCE_THRESHOLD
from app.services.topic_discovery import (
    CandidateCompany,
    DiscoveryPlanQuality,
    DiscoverySubtopic,
    TopicDiscoveryPlan,
    TopicDiscoveryService,
)


def test_topic_discovery_models_live_outside_service_module() -> None:
    service_source = Path("app/services/topic_discovery.py").read_text()
    models_source = Path("app/services/topic_discovery_models.py").read_text()

    assert TopicDiscoveryPlan is topic_discovery_models.TopicDiscoveryPlan
    assert DiscoveryPlanQuality is topic_discovery_models.DiscoveryPlanQuality
    assert "class TopicDiscoveryPlan(" not in service_source
    assert "class TopicDiscoveryPlan(" in models_source
    assert "class ValidatedCandidate(" in models_source


def test_topic_discovery_prompts_live_outside_service_module() -> None:
    service_source = Path("app/services/topic_discovery.py").read_text()
    prompts_source = Path("app/services/topic_discovery_prompts.py").read_text()
    plan = TopicDiscoveryPlan()
    quality = DiscoveryPlanQuality(
        status="insufficient",
        score=0,
        missing=["候選不足"],
        coverage={},
        subtopic_count=0,
        candidate_count=0,
        recommendation="補候選",
    )

    assert TopicDiscoveryService._prompt("AI 產業鏈") == topic_discovery_prompts.topic_discovery_prompt(
        "AI 產業鏈"
    )
    assert TopicDiscoveryService._repair_prompt(
        "AI 產業鏈", plan, quality
    ) == topic_discovery_prompts.topic_discovery_repair_prompt("AI 產業鏈", plan, quality)
    assert "自動拆解研究子題" not in service_source
    assert "自動拆解研究子題" in prompts_source
    assert "目前品質狀態" in prompts_source


def test_topic_discovery_queries_live_outside_service_module() -> None:
    service_source = Path("app/services/topic_discovery.py").read_text()
    queries_source = Path("app/services/topic_discovery_queries.py").read_text()
    service = TopicDiscoveryService()
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "液冷散熱",
              "objective": "確認液冷訂單是否支撐散熱成長",
              "required_evidence": ["水冷訂單"],
              "risk_focus": ["認證延遲"],
              "search_queries": ["AI 伺服器 液冷"]
            }
          ],
          "candidate_companies": [
            {
              "ticker": "3017",
              "name": "奇鋐",
              "segment": "散熱模組",
              "rationale": "液冷散熱升級",
              "evidence_keywords": ["液冷", "CDU"]
            }
          ]
        }
        """
    )

    assert service.google_news_urls(
        plan,
        include_international=True,
        max_urls=6,
        topic="AI 產業鏈",
        include_metadata=True,
    ) == topic_discovery_queries.google_news_urls(
        plan,
        include_international=True,
        max_urls=6,
        topic="AI 產業鏈",
        include_metadata=True,
        evaluate_plan_quality=service.evaluate_plan_quality,
        infer_source_intents=service.infer_source_intents,
    )
    assert "NVIDIA AI server supply chain Taiwan ODM" not in service_source
    assert "NVIDIA AI server supply chain Taiwan ODM" in queries_source
    assert "def google_news_urls(" in queries_source


def test_topic_discovery_news_query_builders_live_outside_query_planner() -> None:
    queries_source = Path("app/services/topic_discovery_queries.py").read_text()
    news_queries_source = Path("app/services/topic_discovery_news_queries.py").read_text()
    queries = ["AI 伺服器 液冷", "AI 伺服器 液冷", "North American cloud AI capex"]
    item = topic_discovery_queries.query_item(
        "AI 伺服器 液冷",
        "subtopic",
        "確認液冷需求",
        "需求/成長",
        "industry_news",
    )

    assert topic_discovery_queries.query_item(
        "AI 伺服器 液冷",
        "subtopic",
        "確認液冷需求",
        "需求/成長",
        "industry_news",
    ) == topic_discovery_news_queries.query_item(
        "AI 伺服器 液冷",
        "subtopic",
        "確認液冷需求",
        "需求/成長",
        "industry_news",
    )
    assert topic_discovery_queries.query_language("AI 伺服器 liquid cooling") == "mixed"
    assert topic_discovery_queries.dedupe_query_metadata([item, item], max_urls=1) == (
        topic_discovery_news_queries.dedupe_query_metadata([item, item], max_urls=1)
    )
    assert topic_discovery_queries.google_news_metadata_from_queries(
        queries,
        source_type="supplemental",
        hypothesis="補強資料來源。",
        evidence_type="補抓資料源",
    ) == topic_discovery_news_queries.google_news_metadata_from_queries(
        queries,
        source_type="supplemental",
        hypothesis="補強資料來源。",
        evidence_type="補抓資料源",
    )
    assert TopicDiscoveryService._google_news_urls_from_queries(
        queries,
        max_urls=2,
    ) == topic_discovery_news_queries.google_news_urls_from_queries(queries, max_urls=2)
    assert "quote_plus" not in queries_source
    assert "news.google.com/rss/search" not in queries_source
    assert "news.google.com/rss/search" in news_queries_source
    assert "def google_news_metadata_from_queries(" in news_queries_source


def test_topic_discovery_candidate_queries_live_outside_query_planner() -> None:
    queries_source = Path("app/services/topic_discovery_queries.py").read_text()
    candidate_queries_source = Path("app/services/topic_discovery_candidate_queries.py").read_text()
    candidate = CandidateCompany(
        ticker="2382",
        name="廣達",
        segment="AI 伺服器代工",
        rationale="AI server 出貨",
        evidence_keywords=["AI 伺服器", "CSP", "GB200"],
    )
    candidate_items = topic_discovery_candidate_queries.candidate_query_items(
        candidate,
        include_international=True,
    )

    assert TopicDiscoveryService._candidate_query_items(
        candidate,
        include_international=True,
    ) == candidate_items
    assert topic_discovery_queries.supplemental_candidate_query_items(
        candidate,
        include_international=False,
    ) == topic_discovery_candidate_queries.supplemental_candidate_query_items(
        candidate,
        include_international=False,
    )
    assert topic_discovery_queries.round_robin_query_groups(
        [candidate_items[:2], candidate_items[2:4]]
    ) == topic_discovery_candidate_queries.round_robin_query_groups(
        [candidate_items[:2], candidate_items[2:4]]
    )
    assert "法說會 年報 月營收" not in queries_source
    assert "法說會 年報 月營收" in candidate_queries_source
    assert "def candidate_query_items(" in candidate_queries_source
    assert "SUPPLEMENTAL_HYPOTHESIS" in candidate_queries_source


def test_topic_discovery_supplemental_subtopic_queries_live_outside_query_planner() -> None:
    queries_source = Path("app/services/topic_discovery_queries.py").read_text()
    supplemental_source = Path("app/services/topic_discovery_supplemental_queries.py").read_text()
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "液冷散熱",
              "rationale": "功耗提升",
              "required_evidence": ["液冷訂單"],
              "risk_focus": ["認證延遲"],
              "search_queries": ["AI 伺服器 液冷"]
            },
            {
              "name": "出口管制",
              "rationale": "政策風險",
              "required_evidence": ["出口管制"],
              "risk_focus": ["禁令", "地緣政治"],
              "search_queries": ["export control AI chips"]
            }
          ],
          "candidate_companies": []
        }
        """
    )

    metadata = topic_discovery_supplemental_queries.supplemental_subtopic_query_metadata(
        plan,
        missing_subtopics=["出口管制"],
    )

    assert topic_discovery_queries.supplemental_subtopic_query_metadata(
        plan,
        missing_subtopics=["出口管制"],
    ) == metadata
    assert TopicDiscoveryService().supplemental_google_news_query_metadata(
        plan,
        validated_candidates=[],
        include_international=False,
        missing_subtopics=["出口管制"],
    ) == metadata
    assert metadata
    assert all("出口管制" in item["query"] or "export control" in item["query"] for item in metadata)
    assert "target_names" not in queries_source
    assert "subtopic.search_queries[:2]" not in queries_source
    assert "target_names" in supplemental_source
    assert "風險 瓶頸" in supplemental_source
    assert "def supplemental_subtopic_query_metadata(" in supplemental_source


def test_topic_discovery_gap_queries_live_outside_query_planner() -> None:
    queries_source = Path("app/services/topic_discovery_queries.py").read_text()
    gap_source = Path("app/services/topic_discovery_gap_queries.py").read_text()
    plan = TopicDiscoveryPlan(
        subtopics=[
            DiscoverySubtopic(
                name="液冷散熱",
                required_evidence=["液冷訂單", "出貨"],
                risk_focus=["認證延遲"],
                search_queries=["AI"],
            )
        ]
    )
    quality = DiscoveryPlanQuality(
        status="insufficient",
        score=30,
        missing=["補需求與材料"],
        coverage={"需求/成長": False, "供給/產能": True, "上游材料": False},
        subtopic_count=1,
        candidate_count=0,
        recommendation="補 query",
        query_quality={
            "subtopics": {
                "液冷散熱": {
                    "generic_queries": ["AI"],
                    "unaligned_queries": [],
                    "has_international_query": False,
                }
            }
        },
    )

    assert TopicDiscoveryService.coverage_gap_queries(
        "AI 產業鏈", quality
    ) == topic_discovery_gap_queries.coverage_gap_queries("AI 產業鏈", quality)
    assert topic_discovery_queries.query_quality_gap_queries(
        "AI 產業鏈", plan, quality
    ) == topic_discovery_gap_queries.query_quality_gap_queries("AI 產業鏈", plan, quality)
    assert "市場規模 展望" not in queries_source
    assert "query_quality = quality.query_quality" not in queries_source
    assert "市場規模 展望" in gap_source
    assert "query_quality = quality.query_quality" in gap_source
    assert "def query_quality_gap_queries(" in gap_source


def test_topic_discovery_quality_lives_outside_service_module() -> None:
    service_source = Path("app/services/topic_discovery.py").read_text()
    quality_source = Path("app/services/topic_discovery_quality.py").read_text()
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "AI 伺服器需求",
              "objective": "確認 AI 伺服器訂單與出貨是否成長",
              "required_evidence": ["訂單", "出貨"],
              "risk_focus": ["需求下修"],
              "search_queries": ["AI 伺服器 訂單 出貨", "AI server orders shipment Taiwan"]
            },
            {
              "name": "CoWoS 與 HBM 供給",
              "objective": "確認先進封裝與記憶體供給是否形成瓶頸",
              "required_evidence": ["CoWoS 產能", "HBM 供給"],
              "risk_focus": ["供給瓶頸"],
              "search_queries": ["CoWoS HBM 產能", "CoWoS HBM capacity bottleneck"]
            },
            {
              "name": "液冷散熱",
              "objective": "確認液冷散熱規格升級是否帶動營收",
              "required_evidence": ["液冷訂單", "營收"],
              "risk_focus": ["認證延遲"],
              "search_queries": ["液冷散熱 訂單 營收", "liquid cooling revenue Taiwan"]
            },
            {
              "name": "估值股價",
              "objective": "比較估值與本益比是否過高",
              "required_evidence": ["股價", "本益比"],
              "risk_focus": ["估值過高"],
              "search_queries": ["台股 AI 本益比 估值", "Taiwan AI valuation PE"]
            }
          ],
          "candidate_companies": [
            {
              "ticker": "2382",
              "name": "廣達",
              "segment": "AI 伺服器代工",
              "rationale": "AI server 出貨",
              "evidence_keywords": ["AI server", "出貨"]
            }
          ]
        }
        """
    )

    assert TopicDiscoveryService.evaluate_plan_quality(plan) == topic_discovery_quality.evaluate_plan_quality(plan)
    assert TopicDiscoveryService._plan_query_quality(plan) == topic_discovery_quality.plan_query_quality(plan)
    assert "容易漏掉伺服器、散熱、PCB、電源與設備環節" not in service_source
    assert "容易漏掉伺服器、散熱、PCB、電源與設備環節" in quality_source
    assert "def plan_query_quality(" in quality_source


def test_topic_discovery_candidate_validation_lives_outside_service_module() -> None:
    service_source = Path("app/services/topic_discovery.py").read_text()
    candidates_source = Path("app/services/topic_discovery_candidates.py").read_text()
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

    assert service.validate_candidates(plan, documents) == topic_discovery_candidates.validate_candidates(
        plan,
        documents,
    )
    assert TopicDiscoveryService._candidate_status(
        2,
        2,
        confidence_score=HIGH_CONFIDENCE_THRESHOLD,
    ) == topic_discovery_candidates.candidate_status(
        2,
        2,
        confidence_score=HIGH_CONFIDENCE_THRESHOLD,
    )
    assert "通過候選入選門檻" not in service_source
    assert "通過候選入選門檻" in candidates_source
    assert "def validate_candidates(" in candidates_source


def test_topic_discovery_enrichment_lives_outside_service_module() -> None:
    service_source = Path("app/services/topic_discovery.py").read_text()
    enrichment_source = Path("app/services/topic_discovery_enrichment.py").read_text()
    plan = TopicDiscoveryPlan(
        subtopics=[
            DiscoverySubtopic(
                name="AI 伺服器需求",
                objective="確認 AI 伺服器訂單與出貨是否成長",
                required_evidence=["訂單", "出貨"],
                risk_focus=["需求下修"],
                search_queries=["AI 伺服器 訂單 出貨", "AI server orders shipment Taiwan"],
            )
        ],
        candidate_companies=[
            CandidateCompany(
                ticker="2382",
                name="廣達",
                segment="AI 伺服器代工",
                rationale="AI server 出貨",
                evidence_keywords=["AI server", "出貨"],
            )
        ],
    )

    assert TopicDiscoveryService.enrich_plan(
        plan,
        topic="AI 產業鏈",
    ) == topic_discovery_enrichment.enrich_plan(plan, topic="AI 產業鏈")
    assert (
        TopicDiscoveryService.infer_source_intents(plan.subtopics[0])
        == topic_discovery_enrichment.infer_source_intents(plan.subtopics[0])
    )
    assert "補查矽晶圓、電子級化學品" not in service_source
    assert "補查矽晶圓、電子級化學品" in enrichment_source
    assert "def enrich_plan(" in enrichment_source


def test_topic_discovery_fallbacks_live_outside_service_module() -> None:
    service_source = Path("app/services/topic_discovery.py").read_text()
    fallback_source = Path("app/services/topic_discovery_fallbacks.py").read_text()

    for topic in ["AI 產業鏈", "機器人 產業鏈", "記憶體產業鏈", "量子運算"]:
        assert TopicDiscoveryService._fallback_plan(
            topic
        ) == topic_discovery_fallbacks.fallback_plan(topic)

    assert TopicDiscoveryService._generic_anchor_candidates(
        "量子運算"
    ) == topic_discovery_fallbacks.generic_anchor_candidates("量子運算")
    assert TopicDiscoveryService._is_robotics_topic(
        "humanoid robot"
    ) is topic_discovery_fallbacks.is_robotics_topic("humanoid robot")
    assert TopicDiscoveryService._is_memory_topic(
        "DRAM memory"
    ) is topic_discovery_fallbacks.is_memory_topic("DRAM memory")
    assert "AI 伺服器需求" not in service_source
    assert "AI 伺服器需求" in fallback_source
    assert "協作與人形機器人需求" in fallback_source
    assert "def fallback_plan(" in fallback_source
