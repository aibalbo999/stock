from datetime import date

from app.data_sources.news import NewsFetcher
from app.services.candidate_confidence import HIGH_CONFIDENCE_THRESHOLD
from app.services.llm_client import LLMResult
from app.services.topic_discovery import (
    DiscoveryPlanQuality,
    TopicDiscoveryPlan,
    TopicDiscoveryService,
)
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
              "name": "上游材料",
              "rationale": "材料供給",
              "objective": "確認矽晶圓、CCL、銅箔與玻纖布是否形成供給瓶頸",
              "required_evidence": ["矽晶圓", "CCL", "銅箔", "玻纖布"],
              "risk_focus": ["材料缺貨", "價格上漲"],
              "search_queries": ["AI 伺服器 上游材料 CCL 銅箔 玻纖布", "AI upstream materials silicon wafer CCL copper foil"]
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
            },
            {"ticker": "2382", "name": "廣達", "segment": "AI 伺服器代工", "rationale": "出貨", "evidence_keywords": ["AI 伺服器"]},
            {"ticker": "3231", "name": "緯創", "segment": "AI 伺服器代工", "rationale": "出貨", "evidence_keywords": ["AI 伺服器"]},
            {"ticker": "3324", "name": "雙鴻", "segment": "散熱模組", "rationale": "散熱", "evidence_keywords": ["液冷"]},
            {"ticker": "3017", "name": "奇鋐", "segment": "散熱模組", "rationale": "散熱", "evidence_keywords": ["散熱"]},
            {"ticker": "2059", "name": "川湖", "segment": "伺服器導軌", "rationale": "導軌", "evidence_keywords": ["導軌"]},
            {"ticker": "3131", "name": "弘塑", "segment": "先進封裝設備", "rationale": "設備", "evidence_keywords": ["CoWoS"]},
            {"ticker": "3583", "name": "辛耘", "segment": "半導體設備", "rationale": "設備", "evidence_keywords": ["先進封裝"]},
            {"ticker": "2308", "name": "台達電", "segment": "電源", "rationale": "電源", "evidence_keywords": ["電源"]},
            {"ticker": "6669", "name": "緯穎", "segment": "AI 伺服器", "rationale": "伺服器", "evidence_keywords": ["資料中心"]},
            {"ticker": "2368", "name": "金像電", "segment": "PCB", "rationale": "PCB", "evidence_keywords": ["PCB"]},
            {"ticker": "3037", "name": "欣興", "segment": "ABF 載板", "rationale": "載板", "evidence_keywords": ["ABF"]},
            {"ticker": "8046", "name": "南電", "segment": "ABF 載板", "rationale": "載板", "evidence_keywords": ["ABF"]},
            {"ticker": "6274", "name": "台燿", "segment": "高速材料 / CCL", "rationale": "材料", "evidence_keywords": ["CCL"]},
            {"ticker": "2383", "name": "台光電", "segment": "高速 CCL", "rationale": "材料", "evidence_keywords": ["CCL"]}
          ]
        }
        """
    )

    quality = TopicDiscoveryService.evaluate_plan_quality(plan)

    assert quality.status == "ready"
    assert quality.score >= 80
    assert quality.missing == []
    assert all(quality.coverage.values())
    assert quality.coverage["上游材料"] is True


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
    assert result["plan_quality"]["status"] == "caution"
    assert "AI 產業鏈候選公司少於 15 檔" in "；".join(result["plan_quality"]["missing"])
    assert any(subtopic["name"] == "上游半導體與板材材料" for subtopic in result["plan"]["subtopics"])
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


def test_robotics_fallback_plan_provides_ready_candidate_pool() -> None:
    plan = TopicDiscoveryService._fallback_plan("機器人 產業鏈")
    quality = TopicDiscoveryService.evaluate_plan_quality(plan)
    tickers = {candidate.ticker for candidate in plan.candidate_companies}

    assert quality.status == "ready"
    assert quality.score == 100
    assert len(plan.subtopics) >= 6
    assert len(plan.candidate_companies) == 20
    assert {"2308", "2049", "6188", "2002", "5009", "1303"}.issubset(tickers)
    assert any("協作" in subtopic.name for subtopic in plan.subtopics)
    assert any("上游材料" in subtopic.name for subtopic in plan.subtopics)
    assert quality.coverage["上游材料"] is True


def test_ai_fallback_plan_includes_upstream_material_layer() -> None:
    plan = TopicDiscoveryService._fallback_plan("AI 產業鏈低關注潛力股")
    quality = TopicDiscoveryService.evaluate_plan_quality(plan)
    tickers = {candidate.ticker for candidate in plan.candidate_companies}
    material_segments = {candidate.segment for candidate in plan.candidate_companies}

    assert quality.status == "ready"
    assert quality.coverage["上游材料"] is True
    assert {"2383", "6213", "1815", "8358", "6488"}.issubset(tickers)
    assert any("矽晶圓" in segment for segment in material_segments)
    assert any("銅箔" in segment or "玻纖" in segment or "CCL" in segment for segment in material_segments)


def test_memory_fallback_plan_includes_cyclic_and_material_coverage() -> None:
    plan = TopicDiscoveryService._fallback_plan("記憶體產業鏈")
    quality = TopicDiscoveryService.evaluate_plan_quality(plan)
    tickers = {candidate.ticker for candidate in plan.candidate_companies}

    assert quality.status in {"ready", "caution"}
    assert len(plan.subtopics) >= 5
    assert len(plan.candidate_companies) >= 8
    assert {"2408", "2344", "8299", "2451", "3260", "4967"}.issubset(tickers)
    assert any("庫存" in subtopic.name or "需求" in subtopic.name for subtopic in plan.subtopics)
    assert any(
        "memory" in query.lower() or "記憶體" in query
        for subtopic in plan.subtopics
        for query in subtopic.search_queries
    )


def test_generic_fallback_plan_uses_exploration_template_for_unknown_topics() -> None:
    plan = TopicDiscoveryService._fallback_plan("量子運算")
    quality = TopicDiscoveryService.evaluate_plan_quality(plan)

    assert len(plan.subtopics) >= 6
    assert len(plan.candidate_companies) >= 6
    assert any("候選驗證與收斂" in subtopic.name for subtopic in plan.subtopics)
    assert quality.status in {"caution", "ready"}


def test_enrich_plan_adds_upstream_material_layer_for_hardware_supply_chain() -> None:
    plan = TopicDiscoveryService.enrich_plan(
        TopicDiscoveryPlan(
            subtopics=[
                {
                    "name": "機器人需求",
                    "objective": "確認人形機器人訂單與出貨",
                    "required_evidence": ["訂單", "出貨"],
                    "risk_focus": ["需求下修"],
                    "search_queries": ["機器人 訂單 出貨", "robotics orders shipment Taiwan"],
                }
            ],
            candidate_companies=[
                {
                    "ticker": "2308",
                    "name": "台達電",
                    "segment": "伺服驅動",
                    "rationale": "控制系統",
                    "evidence_keywords": ["伺服", "機器人"],
                }
            ],
        ),
        topic="機器人 產業鏈",
    )
    quality = TopicDiscoveryService.evaluate_plan_quality(plan)
    tickers = {candidate.ticker for candidate in plan.candidate_companies}

    assert any("上游材料" in subtopic.name for subtopic in plan.subtopics)
    assert {"2002", "5009", "1303"}.issubset(tickers)
    assert quality.coverage["上游材料"] is True


def test_discover_uses_robotics_fallback_when_llm_returns_non_json() -> None:
    llm = FakeDiscoveryLLM(["不是 JSON 的拆解說明"])

    result = TopicDiscoveryService(llm=llm).discover("機器人 產業鏈")

    assert result["fallback_plan_applied"] is True
    assert result["plan_quality"]["status"] == "ready"
    assert any(candidate["ticker"] == "6188" for candidate in result["plan"]["candidate_companies"])
    assert any("協作" in subtopic["name"] for subtopic in result["plan"]["subtopics"])


def test_parse_plan_infers_source_intents_when_missing() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "估值與財務",
              "rationale": "避免追高",
              "objective": "比較營收、毛利與本益比",
              "required_evidence": ["營收", "毛利", "本益比"],
              "risk_focus": ["估值過高"],
              "search_queries": ["台股 財報 本益比 valuation"]
            }
          ],
          "candidate_companies": []
        }
        """
    )

    assert "financial_metrics" in plan.subtopics[0].source_intents
    assert "valuation" in plan.subtopics[0].source_intents
    assert "international_context" in plan.subtopics[0].source_intents


def test_candidate_validation_does_not_credit_other_company_filing_mentions() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [{"name": "機器人", "rationale": "", "search_queries": ["機器人"]}],
          "candidate_companies": [
            {
              "ticker": "2308",
              "name": "台達電",
              "segment": "伺服控制",
              "rationale": "機器人控制",
              "evidence_keywords": ["機器人"]
            },
            {
              "ticker": "2359",
              "name": "所羅門",
              "segment": "AI 視覺",
              "rationale": "機器人視覺",
              "evidence_keywords": ["機器人"]
            }
          ]
        }
        """
    )
    filing = NewsFetcher.from_manual_text(
        title="股東會年報",
        text="股票代號：2359\n公司名稱：所羅門\n文件類型：annual_report\n台達電為重要同業，機器人視覺需求成長。",
        publisher="公開資訊觀測站 MOPS",
        published_at=date(2026, 5, 19),
    ).model_copy(update={"id": "filing-solomon"})

    validated = TopicDiscoveryService().validate_candidates(plan, [filing])
    evidence_counts = {candidate.ticker: candidate.evidence_count for candidate in validated}

    assert evidence_counts["2359"] == 1
    assert evidence_counts["2308"] == 0


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
    assert "通過候選入選門檻" in candidates[0].validation_reason
    assert "正式分析可信度仍需另看風險/機會歸因" in candidates[0].validation_reason
    assert candidates[0].evidence_count == 2
    assert candidates[0].evidence_source_count == 2
    assert candidates[0].evidence_sources[0]["title"] == "台積電 CoWoS 產能擴張"
    assert candidates[0].evidence_sources[0]["publisher"] == "test-a"
    assert candidates[0].evidence_sources[0]["published_at"] == "2026-05-24"
    assert candidates[0].evidence_confidence_score >= HIGH_CONFIDENCE_THRESHOLD
    assert candidates[0].evidence_confidence_label == "高"
    assert candidates[0].latest_evidence_date == "2026-05-24"


def test_validate_candidates_lists_newest_evidence_sources_first() -> None:
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
            title="台積電 CoWoS 舊資料",
            text="台積電 CoWoS 產能擴張支撐 AI 需求。",
            publisher="test-old",
            published_at=date(2026, 4, 20),
        ),
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 最新資料",
            text="台積電 CoWoS 與先進封裝需求升溫。",
            publisher="test-new",
            published_at=date(2026, 5, 24),
        ),
    ]

    candidates = service.validate_candidates(plan, documents)

    assert candidates[0].evidence_sources[0]["title"] == "台積電 CoWoS 最新資料"
    assert candidates[0].evidence_sources[0]["published_at"] == "2026-05-24"


def test_validate_candidates_excludes_forum_and_investment_blog_sources() -> None:
    service = TopicDiscoveryService()
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [],
          "candidate_companies": [
            {
              "ticker": "1815",
              "name": "富喬",
              "segment": "玻纖布",
              "rationale": "AI 高階材料",
              "evidence_keywords": ["AI", "玻纖布"]
            }
          ]
        }
        """
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="1815 富喬- 追買低檔群創也不要去追高高檔的富喬住套房-股市爆料同學會 - CMoney",
            text="富喬 AI 玻纖布 需求 成長，但這是散戶閒聊。",
            publisher="CMoney",
            published_at=date(2026, 5, 12),
        ),
        NewsFetcher.from_manual_text(
            title="富喬 4月營收創歷史新高 受高階薄布需求帶動",
            text="1815 富喬 玻纖布與 AI 高階薄布需求成長。",
            publisher="CMoney投資網誌",
            published_at=date(2026, 5, 8),
        ),
        NewsFetcher.from_manual_text(
            title="富喬月營收創高 高階玻纖布需求升溫",
            text="1815 富喬月營收創高，高階玻纖布需求升溫。",
            publisher="經濟日報",
            published_at=date(2026, 5, 9),
        ),
    ]

    candidates = service.validate_candidates(plan, documents)

    assert candidates[0].evidence_count == 1
    assert candidates[0].evidence_sources[0]["title"] == "富喬月營收創高 高階玻纖布需求升溫"
    assert all("股市爆料同學會" not in source["title"] for source in candidates[0].evidence_sources)
    assert all(source["publisher"] != "CMoney投資網誌" for source in candidates[0].evidence_sources)


def test_validate_candidates_does_not_promote_when_sources_are_only_investment_blogs() -> None:
    service = TopicDiscoveryService()
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [],
          "candidate_companies": [
            {
              "ticker": "1815",
              "name": "富喬",
              "segment": "玻纖布",
              "rationale": "AI 高階材料",
              "evidence_keywords": ["AI", "玻纖布"]
            }
          ]
        }
        """
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="富喬 4月營收創歷史新高 受高階薄布需求帶動",
            text="1815 富喬 玻纖布與 AI 高階薄布需求成長。",
            publisher="CMoney投資網誌",
            published_at=date(2026, 5, 8),
        ),
        NewsFetcher.from_manual_text(
            title="富喬高階玻纖布需求延續",
            text="1815 富喬 AI 伺服器用高階玻纖布需求延續。",
            publisher="旺得富理財網",
            published_at=date(2026, 5, 9),
        ),
    ]

    candidates = service.validate_candidates(plan, documents)

    assert candidates[0].evidence_count == 0
    assert candidates[0].evidence_source_count == 0
    assert candidates[0].source_credibility_label == "未分級"
    assert candidates[0].evidence_confidence_score < HIGH_CONFIDENCE_THRESHOLD
    assert candidates[0].status == "needs_evidence"


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


def test_validate_candidates_marks_old_sources_as_stale() -> None:
    service = TopicDiscoveryService()
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [],
          "candidate_companies": [
            {
              "ticker": "3059",
              "name": "華晶科",
              "segment": "3D 感測相機",
              "rationale": "影像與 3D 感測可支援機器視覺",
              "evidence_keywords": ["3D 感測", "機器視覺"]
            }
          ]
        }
        """
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="華晶科 3D 感測相機應用",
            text="華晶科 3059 3D 感測與機器視覺應用。",
            publisher="test-a",
            published_at=date(2025, 8, 8),
        ),
        NewsFetcher.from_manual_text(
            title="華晶科 機器視覺布局",
            text="華晶科 3D 感測相機與機器視覺布局。",
            publisher="test-b",
            published_at=date(2025, 5, 29),
        ),
    ]

    candidates = service.validate_candidates(plan, documents)

    assert candidates[0].status == "weak_evidence"
    assert candidates[0].promotion_eligible is False
    assert candidates[0].evidence_stale is True
    assert candidates[0].latest_evidence_date == "2025-08-08"
    assert "超過 180 天新鮮度門檻" in candidates[0].validation_reason
    assert "最近 180 天內" in candidates[0].next_action


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


def test_validate_candidates_excludes_sources_with_unrelated_entity_metadata() -> None:
    service = TopicDiscoveryService()
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [],
          "candidate_companies": [
            {
              "ticker": "2308",
              "name": "台達電",
              "segment": "電源管理",
              "rationale": "AI 電源",
              "evidence_keywords": ["電源", "AI 伺服器"]
            }
          ]
        }
        """
    )
    wrong_company = NewsFetcher.from_manual_text(
        title="光寶科 AI 電源出貨升溫",
        text="光寶科 AI 伺服器電源需求增加，台達電同業也受市場關注。",
        publisher="test",
        published_at=date(2026, 5, 24),
    ).model_copy(update={"entity_tickers": ["2301"], "entity_names": ["光寶科"]})

    candidates = service.validate_candidates(plan, [wrong_company])

    assert candidates[0].status == "needs_evidence"
    assert candidates[0].evidence_count == 0


def test_validate_candidates_uses_matching_entity_metadata_as_company_evidence() -> None:
    service = TopicDiscoveryService()
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [],
          "candidate_companies": [
            {
              "ticker": "3017",
              "name": "奇鋐",
              "segment": "散熱模組",
              "rationale": "液冷散熱",
              "evidence_keywords": ["液冷", "散熱"]
            }
          ]
        }
        """
    )
    mapped_document = NewsFetcher.from_manual_text(
        title="AI 伺服器液冷散熱需求升溫",
        text="AI 伺服器液冷散熱需求增加，供應鏈接單升溫。",
        publisher="test",
        published_at=date(2026, 5, 24),
    ).model_copy(update={"entity_tickers": ["3017"], "entity_names": ["奇鋐"]})

    candidates = service.validate_candidates(plan, [mapped_document])

    assert candidates[0].status == "weak_evidence"
    assert candidates[0].evidence_count == 1
    assert candidates[0].evidence_sources[0]["title"] == "AI 伺服器液冷散熱需求升溫"


def test_validate_candidates_relaxes_context_for_memory_entity_matches() -> None:
    service = TopicDiscoveryService()
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [],
          "candidate_companies": [
            {
              "ticker": "2408",
              "name": "南亞科",
              "segment": "DRAM 記憶體",
              "rationale": "DRAM 原廠",
              "evidence_keywords": ["DRAM", "記憶體"]
            }
          ]
        }
        """
    )
    mapped_document = NewsFetcher.from_manual_text(
        title="南亞科法人說明會",
        text="公司說明產能利用率與毛利率展望。",
        publisher="公開資訊觀測站",
        published_at=date(2026, 5, 24),
    ).model_copy(update={"entity_tickers": ["2408"], "entity_names": ["南亞科"]})

    candidates = service.validate_candidates(plan, [mapped_document])

    assert candidates[0].status == "weak_evidence"
    assert candidates[0].evidence_count == 1


def test_validate_candidates_rejects_unrelated_release_notes_with_ticker_like_ids() -> None:
    service = TopicDiscoveryService()
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [],
          "candidate_companies": [
            {
              "ticker": "5443",
              "name": "均豪",
              "segment": "半導體自動化",
              "rationale": "機械手臂與自動化設備",
              "evidence_keywords": ["自動化", "機械手臂"]
            }
          ]
        }
        """
    )
    release_note = NewsFetcher.from_manual_text(
        title="May 21, 2026 / Google Cloud Release Notes",
        text="Issue 5443 updates automation tooling for cloud servers.",
        publisher="Google Cloud Release Notes",
        published_at=date(2026, 5, 21),
    )
    company_news = NewsFetcher.from_manual_text(
        title="均豪半導體自動化設備需求",
        text="均豪受惠半導體自動化與機械手臂設備需求。",
        publisher="test",
        published_at=date(2026, 5, 24),
    )

    candidates = service.validate_candidates(plan, [release_note, company_news])

    assert candidates[0].evidence_count == 1
    assert candidates[0].evidence_source_count == 1
    assert candidates[0].evidence_sources[0]["title"] == "均豪半導體自動化設備需求"
    assert all(
        "Google Cloud" not in source["publisher"] for source in candidates[0].evidence_sources
    )


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


def test_topic_discovery_prompt_requests_early_signal_and_low_attention_candidates() -> None:
    prompt = TopicDiscoveryService._prompt("AI 產業鏈")
    repair = TopicDiscoveryService._repair_prompt(
        "AI 產業鏈",
        TopicDiscoveryPlan(),
        DiscoveryPlanQuality(
            status="insufficient",
            score=0,
            missing=[],
            coverage={},
            subtopic_count=0,
            candidate_count=0,
            recommendation="補候選",
        ),
    )

    assert "early_signal" in prompt
    assert "報導較少但訊號可能轉強" in prompt
    assert "上游材料端" in prompt
    assert "material_supply" in prompt
    assert "長尾供應鏈候選" in repair
    assert "上游材料端" in repair
