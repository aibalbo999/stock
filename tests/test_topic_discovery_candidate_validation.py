from datetime import date

from app.data_sources.news import NewsFetcher
from app.services.candidate_confidence import HIGH_CONFIDENCE_THRESHOLD
from app.services.topic_discovery import TopicDiscoveryService
from app.services.whitelist import SupplyChainWhitelist


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
