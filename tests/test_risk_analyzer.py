from datetime import date

from app.data_sources.news import NewsFetcher
from app.models.schemas import RiskType
from app.services.risk_analyzer import LLMRiskClassifier, RiskAnalyzer, RiskClassification


def test_structural_bottleneck_gets_source_timestamp() -> None:
    document = NewsFetcher.from_manual_text(
        title="CoWoS 產能滿載影響 AI 伺服器交期",
        text="台積電 CoWoS 產能滿載，HBM 供給不足，使 AI 伺服器交期延長。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    findings = RiskAnalyzer().analyze_documents([document])

    assert findings[0].risk_type == RiskType.structural_bottleneck
    assert findings[0].source.published_at == date(2026, 5, 20)
    assert findings[0].related_companies[0].ticker == "2330"


def test_server_delay_without_upstream_evidence_is_insufficient_data() -> None:
    document = NewsFetcher.from_manual_text(
        title="AI 伺服器出貨延遲",
        text="廣達 AI 伺服器出貨延遲，但報導未說明上游供應或封裝瓶頸。",
        publisher="測試新聞",
        published_at=date(2026, 5, 21),
    )

    findings = RiskAnalyzer().analyze_documents([document])

    assert any(finding.risk_type == RiskType.insufficient_data for finding in findings)


def test_positive_liquid_cooling_demand_is_not_structural_bottleneck() -> None:
    document = NewsFetcher.from_manual_text(
        title="水冷需求旺 雙鴻董事長稱下半年滿好的",
        text="雙鴻因應水冷散熱需求擴產，有多少產能客戶就下多少訂單。",
        publisher="測試新聞",
        published_at=date(2026, 5, 21),
    )

    findings = RiskAnalyzer().analyze_documents([document])

    assert not any(finding.risk_type == RiskType.structural_bottleneck for finding in findings)


def test_cowos_capacity_tightness_is_structural_bottleneck() -> None:
    document = NewsFetcher.from_manual_text(
        title="台積電 CoWoS 產能吃緊",
        text="台積電 CoWoS 產能吃緊，AI 供應鏈尋找替代方案。",
        publisher="測試新聞",
        published_at=date(2026, 5, 12),
    )

    findings = RiskAnalyzer().analyze_documents([document])

    assert any(finding.risk_type == RiskType.structural_bottleneck for finding in findings)


def test_company_filing_boilerplate_macro_risk_is_not_reported_as_company_bottleneck() -> None:
    document = NewsFetcher.from_manual_text(
        title="股東會年報",
        text=(
            "股票代號：1504\n公司名稱：東元\n文件類型：annual_report\n"
            "三、未來公司發展策略，受到外部競爭環境、法規環境及總體經營環境之影響："
            "邁入 115 年，全球總體經濟與地緣政治等變因仍舊存在。"
        ),
        publisher="公開資訊觀測站 MOPS",
        published_at=date(2026, 5, 8),
    ).model_copy(update={"id": "filing-teco"})

    findings = RiskAnalyzer().analyze_documents([document])

    assert findings == []


def test_positive_company_filing_liquid_cooling_capability_is_not_bottleneck() -> None:
    document = NewsFetcher.from_manual_text(
        title="股東會年報",
        text=(
            "股票代號：2301\n公司名稱：光寶科\n文件類型：annual_report\n"
            "經營風險包含匯率與供應鏈變化，需持續管理。"
            "光寶為全球次世代 AI 關鍵基礎設施中的領先廠商，"
            "實機展示整合電源、機櫃以及液冷系統，助力資料中心客戶快速建置高效能、低能耗的 AI 基礎設施。"
        ),
        publisher="公開資訊觀測站 MOPS",
        published_at=date(2026, 4, 30),
    ).model_copy(update={"id": "filing-liteon-positive-liquid-cooling"})

    findings = RiskAnalyzer().analyze_documents([document])

    assert not any(finding.risk_type == RiskType.structural_bottleneck for finding in findings)


def test_company_filing_structural_evidence_uses_local_risk_sentence() -> None:
    document = NewsFetcher.from_manual_text(
        title="股東會年報",
        text=(
            "股票代號：2301\n公司名稱：光寶科\n文件類型：annual_report\n"
            "光寶實機展示整合電源、機櫃以及液冷系統，助力資料中心客戶建置低能耗 AI 基礎設施。"
            "因應出口管制法律法規之變化，本公司已就各事業單位日常營運狀況進行評估。"
        ),
        publisher="公開資訊觀測站 MOPS",
        published_at=date(2026, 4, 30),
    ).model_copy(update={"id": "filing-liteon-export-control"})

    findings = RiskAnalyzer().analyze_documents([document])

    structural = [finding for finding in findings if finding.risk_type == RiskType.structural_bottleneck]
    assert len(structural) == 1
    assert "出口管制" in structural[0].evidence
    assert "液冷系統" not in structural[0].evidence


def test_topic_keyword_without_risk_context_is_not_structural_bottleneck() -> None:
    document = NewsFetcher.from_manual_text(
        title="CoWoS 產能爆發 產業鏈機會受關注",
        text="市場關注下一代封裝技術產業鏈機會。",
        publisher="測試新聞",
        published_at=date(2026, 5, 23),
    )

    findings = RiskAnalyzer().analyze_documents([document])

    assert not any(finding.risk_type == RiskType.structural_bottleneck for finding in findings)


def test_growth_terms_trigger_ai_classification_candidates() -> None:
    analyzer = RiskAnalyzer()

    terms = analyzer._document_candidate_terms("廣達 AI 伺服器出貨成長，外資看好產業鏈獲利釋放。")

    assert "出貨成長" in terms
    assert "看好" in terms
    assert "獲利釋放" in terms


def test_ai_classifier_can_override_topic_keyword_as_growth_opportunity() -> None:
    class FakeClassifier:
        def classify(self, document, keywords, topic):
            return RiskClassification(
                classification="opportunity_or_growth",
                topic="需求成長",
                evidence="需求旺，訂單增加",
                confidence=0.91,
            )

    document = NewsFetcher.from_manual_text(
        title="新主題關鍵零組件需求旺",
        text="新主題關鍵零組件需求旺，訂單增加，未提到供給限制或出貨延遲。",
        publisher="測試新聞",
        published_at=date(2026, 5, 23),
    )

    findings = RiskAnalyzer(use_llm=True, classifier=FakeClassifier()).analyze_documents([document])

    assert len(findings) == 1
    assert findings[0].risk_type == RiskType.opportunity_or_growth
    assert findings[0].topic == "需求成長"


def test_ai_classifier_can_create_generic_structural_bottleneck() -> None:
    class FakeClassifier:
        def classify(self, document, keywords, topic):
            return RiskClassification(
                classification="structural_bottleneck",
                topic="上游材料限制",
                evidence="上游材料供給不足，導致出貨延遲",
                confidence=0.88,
            )

    document = NewsFetcher.from_manual_text(
        title="新主題供應鏈出貨延遲",
        text="上游材料供給不足，導致出貨延遲。",
        publisher="測試新聞",
        published_at=date(2026, 5, 23),
    )

    findings = RiskAnalyzer(use_llm=True, classifier=FakeClassifier()).analyze_documents([document])

    assert len(findings) == 1
    assert findings[0].risk_type == RiskType.structural_bottleneck
    assert findings[0].topic == "上游材料限制"


def test_ai_risk_classification_requires_evidence_from_document() -> None:
    class FakeClassifier:
        def classify(self, document, keywords, topic):
            return RiskClassification(
                classification="structural_bottleneck",
                topic="上游材料限制",
                evidence="這段證據不在原文",
                confidence=0.95,
            )

    document = NewsFetcher.from_manual_text(
        title="新主題供應鏈出貨延遲",
        text="上游材料供給不足，導致出貨延遲。",
        publisher="測試新聞",
        published_at=date(2026, 5, 23),
    )

    findings = RiskAnalyzer(use_llm=True, classifier=FakeClassifier()).analyze_documents([document])

    assert findings == []


def test_ai_risk_classification_requires_minimum_confidence() -> None:
    class FakeClassifier:
        def classify(self, document, keywords, topic):
            return RiskClassification(
                classification="structural_bottleneck",
                topic="上游材料限制",
                evidence="上游材料供給不足",
                confidence=0.3,
            )

    document = NewsFetcher.from_manual_text(
        title="新主題供應鏈出貨延遲",
        text="上游材料供給不足，導致出貨延遲。",
        publisher="測試新聞",
        published_at=date(2026, 5, 23),
    )

    findings = RiskAnalyzer(use_llm=True, classifier=FakeClassifier()).analyze_documents([document])

    assert findings == []


def test_ai_risk_classification_normalizes_generic_topic() -> None:
    class FakeClassifier:
        def classify(self, document, keywords, topic):
            return RiskClassification(
                classification="structural_bottleneck",
                topic="晶圓代工: 2330 台積電",
                evidence="台積電 CoWoS 產能吃緊",
                confidence=0.9,
            )

    document = NewsFetcher.from_manual_text(
        title="台積電 CoWoS 產能吃緊",
        text="台積電 CoWoS 產能吃緊，AI 供應鏈尋找替代方案。",
        publisher="測試新聞",
        published_at=date(2026, 5, 12),
    )

    findings = RiskAnalyzer(use_llm=True, classifier=FakeClassifier()).analyze_documents([document])

    assert findings[0].topic == "2330 台積電"


def test_ai_classifier_batch_is_used_once_for_multiple_documents() -> None:
    class FakeClassifier:
        def __init__(self):
            self.calls = 0

        def classify_many(self, items, topic):
            self.calls += 1
            return {
                document.id: RiskClassification(
                    classification="opportunity_or_growth",
                    topic="需求成長",
                    evidence="需求旺",
                    confidence=0.8,
                )
                for document, _keywords in items
            }

    classifier = FakeClassifier()
    documents = [
        NewsFetcher.from_manual_text(
            title=f"新主題需求旺 {index}",
            text="需求旺，訂單增加。",
            publisher="測試新聞",
            published_at=date(2026, 5, 23),
        )
        for index in range(3)
    ]

    findings = RiskAnalyzer(use_llm=True, classifier=classifier).analyze_documents(documents)

    assert len(findings) == 3
    assert all(finding.risk_type == RiskType.opportunity_or_growth for finding in findings)
    assert classifier.calls == 1


def test_llm_risk_classifier_parse_many() -> None:
    payload = """
    {
      "items": [
        {
          "document_id": "doc-1",
          "classification": "structural_bottleneck",
          "topic": "上游限制",
          "evidence": "供給不足導致出貨延遲",
          "confidence": 0.91
        },
        {
          "document_id": "doc-2",
          "classification": "opportunity_or_growth",
          "topic": "需求成長",
          "evidence": "需求旺",
          "confidence": 0.87
        }
      ]
    }
    """

    parsed = LLMRiskClassifier._parse_many(payload)

    assert parsed["doc-1"].classification == "structural_bottleneck"
    assert parsed["doc-2"].classification == "opportunity_or_growth"


def test_llm_classifier_does_not_cache_unvalidated_risk(monkeypatch) -> None:
    document = NewsFetcher.from_manual_text(
        title="新主題供應鏈出貨延遲",
        text="上游材料供給不足，導致出貨延遲。",
        publisher="測試新聞",
        published_at=date(2026, 5, 23),
    )

    classifier = object.__new__(LLMRiskClassifier)
    classifier.client = None
    monkeypatch.setattr(
        classifier,
        "_classify_batch",
        lambda items, topic: {
            document.id: RiskClassification(
                classification="structural_bottleneck",
                topic="上游材料限制",
                evidence="不在原文的證據",
                confidence=0.95,
            )
        },
    )
    cache_calls = []
    monkeypatch.setattr(classifier, "_cache_get", lambda document_id, topic_hash: None)
    monkeypatch.setattr(
        classifier,
        "_cache_upsert",
        lambda document_id, topic_hash, classification, keywords: cache_calls.append(document_id),
    )

    results = classifier.classify_many([(document, ["出貨延遲"])], topic="測試主題")

    assert results == {}
    assert cache_calls == []
