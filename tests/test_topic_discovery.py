from datetime import date

from app.data_sources.news import NewsFetcher
from app.services.candidate_confidence import HIGH_CONFIDENCE_THRESHOLD
from app.services.llm_client import LLMResult
from app.services.topic_discovery import TopicDiscoveryService
from app.services.whitelist import SupplyChainWhitelist


class FakeDiscoveryLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    def generate_with_metadata(self, prompt: str) -> LLMResult:
        self.prompts.append(prompt)
        return LLMResult(
            text=self.responses.pop(0),
            key_index=0,
            model="fake-model",
        )


def test_parse_topic_discovery_plan() -> None:
    raw = """
    {
      "subtopics": [
        {
          "name": "CoWoS",
          "rationale": "AI GPU supply chain bottleneck",
          "objective": "查核先進封裝是否限制出貨",
          "required_evidence": ["產能", "訂單"],
          "risk_focus": ["供給瓶頸"],
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
    assert plan.subtopics[0].objective == "查核先進封裝是否限制出貨"
    assert plan.subtopics[0].required_evidence == ["產能", "訂單"]
    assert plan.subtopics[0].risk_focus == ["供給瓶頸"]
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


def test_evaluate_plan_quality_marks_complete_research_tasks_ready() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "需求成長",
              "rationale": "雲端資本支出",
              "objective": "確認訂單與市場規模是否成長",
              "required_evidence": ["訂單", "市場規模", "營收"],
              "risk_focus": ["需求下修"],
              "search_queries": ["AI 伺服器 訂單 營收"]
            },
            {
              "name": "供給產能",
              "rationale": "CoWoS 與 HBM",
              "objective": "確認產能與良率瓶頸",
              "required_evidence": ["產能", "良率"],
              "risk_focus": ["供給瓶頸", "缺電"],
              "search_queries": ["CoWoS HBM 產能 良率"]
            },
            {
              "name": "估值股價",
              "rationale": "股價反映程度",
              "objective": "比較估值與本益比",
              "required_evidence": ["股價", "本益比"],
              "risk_focus": ["估值過高"],
              "search_queries": ["台股 AI 伺服器 本益比 估值"]
            }
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

    quality = TopicDiscoveryService.evaluate_plan_quality(plan)

    assert quality.status == "ready"
    assert quality.score >= 80
    assert quality.missing == []
    assert all(quality.coverage.values())


def test_evaluate_plan_quality_flags_incomplete_research_tasks() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {"name": "熱門股票", "rationale": "", "search_queries": []}
          ],
          "candidate_companies": []
        }
        """
    )

    quality = TopicDiscoveryService.evaluate_plan_quality(plan)

    assert quality.status == "insufficient"
    assert "熱門股票 缺少研究目的" in quality.missing
    assert "熱門股票 缺少必查證據" in quality.missing
    assert "熱門股票 缺少風險焦點" in quality.missing
    assert "熱門股票 缺少搜尋 query" in quality.missing
    assert "缺少候選公司" in quality.missing


def test_evaluate_plan_quality_flags_narrow_ai_supply_chain_candidate_pool() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "AI 伺服器需求",
              "rationale": "雲端資本支出",
              "objective": "確認 AI 伺服器出貨與台廠訂單是否成長",
              "required_evidence": ["AI 伺服器出貨", "月營收"],
              "risk_focus": ["需求下修"],
              "search_queries": ["AI 伺服器 出貨 月營收", "cloud capex AI server"]
            },
            {
              "name": "CoWoS 與 HBM",
              "rationale": "上游瓶頸",
              "objective": "查核 CoWoS 與 HBM 是否限制 AI 晶片出貨",
              "required_evidence": ["CoWoS 產能", "HBM 供給"],
              "risk_focus": ["供給瓶頸"],
              "search_queries": ["CoWoS HBM 產能 良率", "CoWoS HBM capacity"]
            },
            {
              "name": "液冷散熱電源",
              "rationale": "功耗升級",
              "objective": "確認液冷與電源是否形成瓶頸",
              "required_evidence": ["液冷訂單", "電源規格"],
              "risk_focus": ["認證延遲"],
              "search_queries": ["AI 伺服器 液冷 電源", "AI data center liquid cooling"]
            },
            {
              "name": "估值股價",
              "rationale": "避免追高",
              "objective": "比較估值與股價風險",
              "required_evidence": ["本益比", "股價"],
              "risk_focus": ["估值過高"],
              "search_queries": ["台股 AI 供應鏈 本益比", "Taiwan AI supply chain valuation"]
            }
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
              "rationale": "伺服器出貨",
              "evidence_keywords": ["AI 伺服器"]
            }
          ]
        }
        """
    )

    quality = TopicDiscoveryService.evaluate_plan_quality(plan)

    assert quality.status == "caution"
    assert any("AI 產業鏈候選公司少於 15 檔" in item for item in quality.missing)


def test_evaluate_plan_quality_flags_generic_and_unaligned_queries() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "需求成長",
              "rationale": "雲端資本支出",
              "objective": "確認訂單與市場規模是否成長",
              "required_evidence": ["訂單", "市場規模"],
              "risk_focus": ["需求下修"],
              "search_queries": ["AI", "台積電 法說會"]
            }
          ],
          "candidate_companies": [
            {
              "ticker": "2382",
              "name": "廣達",
              "segment": "AI 伺服器代工",
              "rationale": "伺服器訂單",
              "evidence_keywords": ["AI server", "訂單"]
            }
          ]
        }
        """
    )

    quality = TopicDiscoveryService.evaluate_plan_quality(plan)

    assert quality.status == "insufficient"
    assert "需求成長 搜尋 query 過於籠統：AI" in quality.missing
    assert "需求成長 搜尋 query 未對應研究證據或風險：台積電 法說會" in quality.missing
    assert quality.query_quality["generic_query_count"] == 1
    assert quality.query_quality["subtopics"]["需求成長"]["unaligned_queries"] == ["台積電 法說會"]


def test_evaluate_plan_quality_requires_international_query_per_subtopic() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "估值股價",
              "rationale": "市場反映程度",
              "objective": "比較估值與本益比",
              "required_evidence": ["股價", "本益比"],
              "risk_focus": ["估值過高"],
              "search_queries": ["台股 伺服器 股價 本益比"]
            }
          ],
          "candidate_companies": [
            {
              "ticker": "6669",
              "name": "緯穎",
              "segment": "AI 伺服器",
              "rationale": "伺服器營收",
              "evidence_keywords": ["AI server", "營收"]
            }
          ]
        }
        """
    )

    quality = TopicDiscoveryService.evaluate_plan_quality(plan)

    assert quality.status == "insufficient"
    assert "估值股價 缺少國際資料 query" in quality.missing
    assert quality.query_quality["international_query_count"] == 0


def test_discover_repairs_incomplete_plan_once() -> None:
    weak_plan = """
    {
      "subtopics": [
        {"name": "熱門股票", "rationale": "", "search_queries": []}
      ],
      "candidate_companies": []
    }
    """
    repaired_plan = """
    {
      "subtopics": [
        {
          "name": "需求成長",
          "rationale": "雲端資本支出",
          "objective": "確認訂單與市場規模是否成長",
          "required_evidence": ["訂單", "市場規模", "營收"],
          "risk_focus": ["需求下修"],
          "search_queries": ["AI 伺服器 訂單 營收"]
        },
        {
          "name": "供給產能",
          "rationale": "關鍵零組件供應",
          "objective": "確認產能與良率瓶頸",
          "required_evidence": ["產能", "良率"],
          "risk_focus": ["供給瓶頸", "缺電"],
          "search_queries": ["AI 供應鏈 產能 良率"]
        },
        {
          "name": "估值股價",
          "rationale": "市場反映程度",
          "objective": "比較估值與本益比",
          "required_evidence": ["股價", "本益比"],
          "risk_focus": ["估值過高"],
          "search_queries": ["台股 AI 本益比 估值"]
        }
      ],
      "candidate_companies": [
        {
          "ticker": "2330",
          "name": "台積電",
          "segment": "晶圓代工",
          "rationale": "先進製程與封裝",
          "evidence_keywords": ["CoWoS", "先進封裝"]
        }
      ]
    }
    """
    llm = FakeDiscoveryLLM([weak_plan, repaired_plan])

    result = TopicDiscoveryService(llm=llm).discover("AI 產業鏈")

    assert result["repair_attempted"] is True
    assert result["repair_applied"] is True
    assert result["initial_plan_quality"]["status"] == "insufficient"
    assert result["plan_quality"]["status"] == "ready"
    assert result["plan"]["subtopics"][0]["name"] == "需求成長"
    assert "品質狀態" in llm.prompts[1]


def test_discover_keeps_original_when_repair_is_worse() -> None:
    caution_plan = """
    {
      "subtopics": [
        {
          "name": "需求成長",
          "rationale": "訂單追蹤",
          "objective": "確認需求與營收",
          "required_evidence": ["訂單", "營收"],
          "risk_focus": ["需求下修"],
          "search_queries": ["AI 伺服器 訂單 營收"]
        }
      ],
      "candidate_companies": [
        {
          "ticker": "2382",
          "name": "廣達",
          "segment": "AI 伺服器",
          "rationale": "伺服器代工",
          "evidence_keywords": ["AI 伺服器"]
        }
      ]
    }
    """
    weak_plan = """
    {
      "subtopics": [
        {"name": "熱門股票", "rationale": "", "search_queries": []}
      ],
      "candidate_companies": []
    }
    """
    llm = FakeDiscoveryLLM([caution_plan, weak_plan])

    result = TopicDiscoveryService(llm=llm).discover("AI 產業鏈")

    assert result["repair_attempted"] is True
    assert result["repair_applied"] is False
    assert result["plan"]["subtopics"][0]["name"] == "需求成長"
    assert result["plan_quality"]["score"] >= result["initial_plan_quality"]["score"]


def test_discover_uses_fallback_plan_when_llm_returns_non_json() -> None:
    llm = FakeDiscoveryLLM(["不是 JSON 的拆解說明"])

    result = TopicDiscoveryService(llm=llm).discover("AI 產業鏈")

    assert result["fallback_plan_applied"] is True
    assert result["plan_quality"]["status"] in {"ready", "caution"}
    assert result["plan"]["candidate_companies"]
    assert any(candidate["ticker"] == "2330" for candidate in result["plan"]["candidate_companies"])
    assert any("CoWoS" in subtopic["name"] for subtopic in result["plan"]["subtopics"])


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
    assert all("hypothesis" in item and "evidence_type" in item and "language" in item for item in metadata)
    assert metadata[0]["hypothesis"] == "確認需求"
    assert metadata[0]["evidence_type"] in {"需求/成長", "風險/瓶頸"}


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
    assert candidates[0].promotion_eligible is True
    assert "通過正式分析門檻" in candidates[0].validation_reason
    assert candidates[0].evidence_count == 2
    assert candidates[0].evidence_source_count == 2
    assert candidates[0].evidence_sources[0]["title"] == "台積電 CoWoS 產能擴張"
    assert candidates[0].evidence_sources[0]["publisher"] == "test-a"
    assert candidates[0].evidence_sources[0]["published_at"] == "2026-05-24"
    assert candidates[0].evidence_confidence_score >= HIGH_CONFIDENCE_THRESHOLD
    assert candidates[0].evidence_confidence_label == "高"
    assert candidates[0].latest_evidence_date == "2026-05-24"


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
    assert candidates[0].promotion_eligible is False
    assert "弱證據" in candidates[0].validation_reason
    assert "補抓" in candidates[0].next_action
    assert candidates[0].evidence_confidence_score < HIGH_CONFIDENCE_THRESHOLD


def test_validate_candidates_requires_high_confidence_before_promotion() -> None:
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
            published_at=None,
        ),
        NewsFetcher.from_manual_text(
            title="台積電先進封裝擴產",
            text="台積電 CoWoS 與先進封裝需求升溫。",
            publisher="test-b",
            published_at=None,
        ),
    ]

    candidates = service.validate_candidates(plan, documents)

    assert candidates[0].evidence_count == 2
    assert candidates[0].evidence_source_count == 2
    assert candidates[0].evidence_confidence_score < HIGH_CONFIDENCE_THRESHOLD
    assert candidates[0].status == "weak_evidence"
    assert candidates[0].promotion_eligible is False
    assert "篇數與來源數達標" in candidates[0].validation_reason
    assert "有日期、近期" in candidates[0].next_action


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


def test_validate_candidates_uses_segment_and_rationale_as_context() -> None:
    service = TopicDiscoveryService()
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "AI 伺服器",
              "required_evidence": ["雲端資本支出"]
            }
          ],
          "candidate_companies": [
            {
              "ticker": "2382",
              "name": "廣達",
              "segment": "AI伺服器代工",
              "rationale": "美系 CSP 伺服器出貨",
              "evidence_keywords": ["GB200 訂單"]
            }
          ]
        }
        """
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="廣達 AI 伺服器出貨受惠雲端資本支出",
            text="廣達受惠 AI 伺服器與美系雲端資本支出，未提到 GB200。",
            publisher="test-a",
            published_at=date(2026, 5, 24),
        ),
        NewsFetcher.from_manual_text(
            title="廣達伺服器代工需求維持高檔",
            text="美系 CSP 伺服器出貨帶動廣達營運。",
            publisher="test-b",
            published_at=date(2026, 5, 24),
        ),
    ]

    candidates = service.validate_candidates(plan, documents)

    assert candidates[0].status == "evidence_supported"
    assert candidates[0].evidence_count == 2


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
    assert len(whitelist.candidate_audit()) == 2


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
