from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass

from app.core.prompts import RISK_CLASSIFICATION_BATCH_PROMPT, RISK_CLASSIFICATION_PROMPT
from app.db.session import session_scope
from app.models.schemas import NewsDocument, RiskFinding, RiskType
from app.services.entity_mapping import EntityMapper, company_filing_owner_ticker
from app.services.llm_client import LLMClient
from app.services.persistence import RiskClassificationRepository
from app.services.whitelist import SupplyChainWhitelist


@dataclass(frozen=True)
class RiskClassification:
    classification: str
    topic: str
    evidence: str
    confidence: float = 0.0


MIN_LLM_RISK_CONFIDENCE = 0.55
MAX_LLM_RISK_DOCUMENTS = 32


class LLMRiskClassifier:
    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient()

    def classify(
        self,
        document: NewsDocument,
        keywords: list[str],
        topic: str,
    ) -> RiskClassification | None:
        prompt = RISK_CLASSIFICATION_PROMPT.format(
            topic=topic,
            keywords=", ".join(keywords) or "無",
            title=document.title[:300],
            text=document.text[:1600],
        )
        result = self.client.generate_with_metadata(prompt)
        if result.fallback:
            return None
        return self._parse(result.text)

    def classify_many(
        self,
        items: list[tuple[NewsDocument, list[str]]],
        topic: str,
        batch_size: int = 8,
    ) -> dict[str, RiskClassification]:
        results: dict[str, RiskClassification] = {}
        misses: list[tuple[NewsDocument, list[str]]] = []
        topic_hash = self._topic_hash(topic)

        for document, keywords in items:
            cached = self._cache_get(document.id, topic_hash)
            if cached:
                results[document.id] = cached
            else:
                misses.append((document, keywords))

        for index in range(0, len(misses), batch_size):
            batch = misses[index : index + batch_size]
            batch_results = self._classify_batch(batch, topic)
            for document, keywords in batch:
                classification = batch_results.get(document.id)
                if classification and RiskAnalyzer._is_usable_or_non_risk_classification(
                    classification,
                    f"{document.title}\n{document.text}",
                ):
                    results[document.id] = classification
                    self._cache_upsert(document.id, topic_hash, classification, keywords)
        return results

    def _classify_batch(
        self,
        items: list[tuple[NewsDocument, list[str]]],
        topic: str,
    ) -> dict[str, RiskClassification]:
        documents_json = json.dumps(
            [
                {
                    "document_id": document.id,
                    "keywords": keywords,
                    "title": document.title[:300],
                    "text": document.text[:1200],
                    "source_date": document.source.published_at.isoformat()
                    if document.source.published_at
                    else None,
                    "publisher": document.source.publisher,
                }
                for document, keywords in items
            ],
            ensure_ascii=False,
        )
        prompt = RISK_CLASSIFICATION_BATCH_PROMPT.format(
            topic=topic,
            documents_json=documents_json,
        )
        result = self.client.generate_with_metadata(prompt)
        if result.fallback:
            return {}
        return self._parse_many(result.text)

    @staticmethod
    def _parse(text: str) -> RiskClassification | None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        classification = str(payload.get("classification", "")).strip()
        if classification not in {
            "structural_bottleneck",
            "short_term_volatility",
            "opportunity_or_growth",
            "insufficient_data",
            "neutral",
        }:
            return None
        try:
            confidence = float(payload.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        return RiskClassification(
            classification=classification,
            topic=str(payload.get("topic") or classification),
            evidence=str(payload.get("evidence") or ""),
            confidence=confidence,
        )

    @classmethod
    def _parse_many(cls, text: str) -> dict[str, RiskClassification]:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
        items = payload.get("items", [])
        if not isinstance(items, list):
            return {}
        results: dict[str, RiskClassification] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            document_id = str(item.get("document_id") or "")
            classification = cls._parse(json.dumps(item, ensure_ascii=False))
            if document_id and classification:
                results[document_id] = classification
        return results

    @staticmethod
    def _cache_get(document_id: str, topic_hash: str) -> RiskClassification | None:
        try:
            with session_scope() as session:
                cached = RiskClassificationRepository(session).get(document_id, topic_hash)
        except Exception:
            return None
        if not cached:
            return None
        return RiskClassification(
            classification=cached["classification"],
            topic=cached["topic"],
            evidence=cached["evidence"],
            confidence=float(cached["confidence"] or 0.0),
        )

    def _cache_upsert(
        self,
        document_id: str,
        topic_hash: str,
        classification: RiskClassification,
        keywords: list[str],
    ) -> None:
        try:
            with session_scope() as session:
                RiskClassificationRepository(session).upsert(
                    document_id=document_id,
                    topic_hash=topic_hash,
                    classification=classification.classification,
                    topic=classification.topic,
                    evidence=classification.evidence,
                    confidence=classification.confidence,
                    keywords=keywords,
                    model=self.client.settings.primary_llm_model,
                )
        except Exception:
            return

    @staticmethod
    def _topic_hash(topic: str) -> str:
        return hashlib.sha256(topic.encode("utf-8")).hexdigest()


class RiskAnalyzer:
    def __init__(
        self,
        whitelist: SupplyChainWhitelist | None = None,
        mapper: EntityMapper | None = None,
        use_llm: bool = False,
        classifier: LLMRiskClassifier | None = None,
    ) -> None:
        self.whitelist = whitelist or SupplyChainWhitelist()
        self.mapper = mapper or EntityMapper(self.whitelist)
        self.use_llm = use_llm
        self.classifier = classifier or (LLMRiskClassifier() if use_llm else None)

    def analyze_documents(self, documents: list[NewsDocument]) -> list[RiskFinding]:
        findings: list[RiskFinding] = []
        keyword_map: dict[str, list[str]] = {}
        ai_classifications: dict[str, RiskClassification] = {}
        if self.use_llm and self.classifier:
            ai_items = []
            for document in documents:
                text = f"{document.title}\n{document.text}"
                keywords = self._document_candidate_terms(text)
                keyword_map[document.id] = keywords
                if keywords:
                    ai_items.append((document, keywords))
            if hasattr(self.classifier, "classify_many") and ai_items:
                ai_classifications = self.classifier.classify_many(
                    ai_items[:MAX_LLM_RISK_DOCUMENTS],
                    self.whitelist.as_prompt_context(),
                )

        for document in documents:
            text = f"{document.title}\n{document.text}"
            structural_hits = self._hits(text, self.whitelist.risk_keywords["structural_bottleneck"])
            volatility_hits = self._hits(text, self.whitelist.risk_keywords["short_term_volatility"])
            causal_hits = self._hits(text, self.whitelist.risk_keywords["causal_checks"])
            all_hits = keyword_map.get(
                document.id,
                self._candidate_terms(text, structural_hits + volatility_hits + causal_hits),
            )
            companies = self.mapper.match_document(document)

            classification = ai_classifications.get(document.id) or self._classify_with_ai(document, all_hits)
            if classification:
                finding = self._finding_from_classification(document, classification, companies, text)
                if finding:
                    findings.append(finding)
                continue

            if structural_hits and self._has_structural_risk_context(text, structural_hits):
                evidence = self._structural_evidence_sentence(text, structural_hits)
                if not evidence:
                    continue
                if self._is_generic_company_filing_risk(document, evidence, structural_hits):
                    continue
                findings.append(
                    RiskFinding(
                        risk_type=RiskType.structural_bottleneck,
                        topic=", ".join(structural_hits[:3]),
                        evidence=evidence,
                        source=document.source,
                        related_companies=companies,
                    )
                )
            elif volatility_hits:
                findings.append(
                    RiskFinding(
                        risk_type=RiskType.short_term_volatility,
                        topic=", ".join(volatility_hits[:3]),
                        evidence=self._evidence_sentence(text, volatility_hits),
                        source=document.source,
                        related_companies=companies,
                    )
                )

            if causal_hits and not structural_hits:
                findings.append(
                    RiskFinding(
                        risk_type=RiskType.insufficient_data,
                        topic="伺服器出貨延遲原因待查",
                        evidence="文本提到出貨或交期異常，但缺少 CoWoS/HBM/先進封裝等上游證據；目前無足夠數據判斷。",
                        source=document.source,
                        related_companies=companies,
                    )
                )
        return findings

    def _classify_with_ai(
        self,
        document: NewsDocument,
        keywords: list[str],
    ) -> RiskClassification | None:
        if not self.use_llm or not self.classifier or not keywords:
            return None
        return self.classifier.classify(document, keywords, self.whitelist.as_prompt_context())

    @staticmethod
    def _finding_from_classification(
        document: NewsDocument,
        classification: RiskClassification,
        companies,
        text: str,
    ) -> RiskFinding | None:
        risk_type_map = {
            "structural_bottleneck": RiskType.structural_bottleneck,
            "short_term_volatility": RiskType.short_term_volatility,
            "opportunity_or_growth": RiskType.opportunity_or_growth,
            "insufficient_data": RiskType.insufficient_data,
        }
        risk_type = risk_type_map.get(classification.classification)
        if risk_type is None:
            return None
        if not RiskAnalyzer._is_usable_ai_classification(classification, text):
            return None
        evidence = RiskAnalyzer._validated_evidence(classification.evidence, text)
        if not evidence:
            return None
        return RiskFinding(
            risk_type=risk_type,
            topic=RiskAnalyzer._normalized_topic(classification.topic, classification.classification),
            evidence=evidence[:240],
            source=document.source,
            related_companies=companies,
        )

    @staticmethod
    def _is_usable_ai_risk_classification(
        classification: RiskClassification,
        text: str,
    ) -> bool:
        if classification.classification == "opportunity_or_growth":
            return RiskAnalyzer._is_usable_ai_opportunity_classification(classification, text)
        if classification.confidence < MIN_LLM_RISK_CONFIDENCE:
            return False
        if not RiskAnalyzer._validated_evidence(classification.evidence, text):
            return False
        topic = RiskAnalyzer._normalized_topic(classification.topic, classification.classification)
        return topic not in {"structural_bottleneck", "short_term_volatility", "insufficient_data", "風險", "機會"}

    @staticmethod
    def _is_usable_ai_opportunity_classification(
        classification: RiskClassification,
        text: str,
    ) -> bool:
        if classification.confidence < MIN_LLM_RISK_CONFIDENCE:
            return False
        if not RiskAnalyzer._validated_evidence(classification.evidence, text):
            return False
        topic = RiskAnalyzer._normalized_topic(classification.topic, classification.classification)
        return topic not in {"opportunity_or_growth", "neutral", "風險", "機會"}

    @staticmethod
    def _is_usable_ai_classification(
        classification: RiskClassification,
        text: str,
    ) -> bool:
        if classification.classification == "opportunity_or_growth":
            return RiskAnalyzer._is_usable_ai_opportunity_classification(classification, text)
        return RiskAnalyzer._is_usable_ai_risk_classification(classification, text)

    @staticmethod
    def _is_usable_or_non_risk_classification(
        classification: RiskClassification,
        text: str,
    ) -> bool:
        if classification.classification in {"opportunity_or_growth", "neutral"}:
            return classification.confidence >= MIN_LLM_RISK_CONFIDENCE
        return RiskAnalyzer._is_usable_ai_risk_classification(classification, text)

    @staticmethod
    def _validated_evidence(evidence: str, text: str) -> str:
        cleaned = " ".join(evidence.strip().split())
        if not cleaned:
            return ""
        compact_evidence = "".join(cleaned.split())
        compact_text = "".join(text.split())
        if compact_evidence in compact_text:
            return cleaned
        sentences = [part.strip() for part in text.replace("。", ".").split(".") if part.strip()]
        for sentence in sentences:
            compact_sentence = "".join(sentence.split())
            if compact_sentence and compact_sentence in compact_evidence:
                return sentence[:240]
        return ""

    @staticmethod
    def _normalized_topic(topic: str, classification: str) -> str:
        cleaned = topic.strip(" ：:，,。 \n\t")
        generic_topics = {
            "",
            "晶圓代工",
            "伺服器代工",
            "散熱模組",
            "系統組裝",
            "半導體設備",
            "AI 產業鏈",
            "AI產業鏈",
        }
        if cleaned in generic_topics:
            return classification
        if ":" in cleaned:
            left, right = cleaned.split(":", 1)
            if left.strip() in generic_topics:
                return right.strip() or classification
        return cleaned

    @staticmethod
    def _hits(text: str, keywords: list[str]) -> list[str]:
        lowered = text.lower()
        hits: list[str] = []
        for keyword in keywords:
            keyword_lower = keyword.lower()
            index = lowered.find(keyword_lower)
            if index == -1:
                continue
            prefix = lowered[max(0, index - 12) : index]
            if any(negation in prefix for negation in ["未說明", "沒有", "缺少", "無"]):
                continue
            hits.append(keyword)
        return hits

    @staticmethod
    def _candidate_terms(text: str, hits: list[str]) -> list[str]:
        generic_terms = [
            "供給不足",
            "供應不足",
            "產能不足",
            "產能吃緊",
            "出貨延遲",
            "交期延長",
            "良率",
            "缺電",
            "管制",
            "制裁",
            "需求旺",
            "需求成長",
            "訂單增加",
            "大單",
            "營收成長",
            "獲利成長",
            "獲利釋放",
            "出貨升",
            "出貨成長",
            "擴產",
            "受惠",
            "看好",
            "商機",
            "爆單",
            "爆發",
            "獲利了結",
            "重挫",
            "庫存調整",
        ]
        combined = list(hits)
        for term in generic_terms:
            if term in text and term not in combined:
                combined.append(term)
        return combined

    def _document_candidate_terms(self, text: str) -> list[str]:
        return self._candidate_terms(
            text,
            self._hits(text, self.whitelist.risk_keywords["structural_bottleneck"])
            + self._hits(text, self.whitelist.risk_keywords["short_term_volatility"])
            + self._hits(text, self.whitelist.risk_keywords["causal_checks"]),
        )

    @staticmethod
    def _has_structural_risk_context(text: str, hits: list[str]) -> bool:
        return bool(RiskAnalyzer._structural_evidence_sentence(text, hits))

    @staticmethod
    def _structural_evidence_sentence(text: str, hits: list[str]) -> str:
        direct_risk_hits = {
            "產能滿載",
            "封裝瓶頸",
            "電網負荷",
            "缺電",
            "美國晶片法案",
            "出口管制",
            "地緣政治",
        }

        risk_terms = [
            "瓶頸",
            "不足",
            "吃緊",
            "受限",
            "延遲",
            "遞延",
            "供給緊",
            "供應緊",
            "供不應求",
            "轉換延遲",
            "禁令",
            "制裁",
            "管制",
            "負荷",
            "風險",
            "重挫",
            "下滑",
            "不佳",
            "偏低",
            "不穩",
        ]
        sentences = [part.strip() for part in text.replace("。", ".").split(".") if part.strip()]
        for sentence in sentences:
            lowered_sentence = sentence.lower()
            if any(hit.lower() in lowered_sentence for hit in hits if hit in direct_risk_hits):
                return sentence[:240]
        for sentence in sentences:
            lowered_sentence = sentence.lower()
            if not any(hit.lower() in lowered_sentence for hit in hits):
                continue
            if any(term in sentence for term in risk_terms):
                return sentence[:240]
        return ""

    @staticmethod
    def _is_generic_company_filing_risk(document: NewsDocument, evidence: str, hits: list[str]) -> bool:
        if not company_filing_owner_ticker(document):
            return False
        lowered = evidence.lower()
        generic_markers = [
            "全球總體經濟",
            "地緣政治",
            "法規環境",
            "外部競爭環境",
            "變因仍舊存在",
            "不確定因素",
            "未來公司發展策略",
        ]
        company_specific_markers = [
            "訂單",
            "客戶",
            "毛利",
            "產能",
            "良率",
            "出貨",
            "庫存",
            "應收",
            "產品",
            "技術",
            "研發",
            "擴產",
            "缺料",
            "供應鏈",
            "電力",
            "液冷",
            "水冷",
            "伺服",
            "機器人",
            "ai",
            "hbm",
            "cowos",
        ]
        generic_hit = any(marker in lowered for marker in generic_markers)
        specific_hit = any(marker in lowered for marker in company_specific_markers)
        broad_macro_hits = {"地緣政治", "美國晶片法案", "出口管制"}
        return generic_hit and not specific_hit and any(hit in broad_macro_hits for hit in hits)

    @staticmethod
    def _evidence_sentence(text: str, hits: list[str]) -> str:
        sentences = [part.strip() for part in text.replace("。", ".").split(".") if part.strip()]
        for sentence in sentences:
            if any(hit.lower() in sentence.lower() for hit in hits):
                return sentence[:240]
        return "；".join(hits)
