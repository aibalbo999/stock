from __future__ import annotations

import json
import re
from urllib.parse import quote_plus

from pydantic import BaseModel, Field, ValidationError

from app.models.schemas import NewsDocument
from app.services.llm_client import LLMClient
from app.services.whitelist import SupplyChainWhitelist


class DiscoverySubtopic(BaseModel):
    name: str = Field(min_length=1)
    rationale: str = ""
    objective: str = ""
    required_evidence: list[str] = Field(default_factory=list, max_length=6)
    risk_focus: list[str] = Field(default_factory=list, max_length=6)
    search_queries: list[str] = Field(default_factory=list, max_length=5)


class CandidateCompany(BaseModel):
    ticker: str = Field(pattern=r"^\d{4}$")
    name: str = Field(min_length=1)
    segment: str = Field(min_length=1)
    rationale: str = ""
    evidence_keywords: list[str] = Field(default_factory=list, max_length=8)


class TopicDiscoveryPlan(BaseModel):
    subtopics: list[DiscoverySubtopic] = Field(default_factory=list, max_length=8)
    candidate_companies: list[CandidateCompany] = Field(default_factory=list, max_length=20)


class ValidatedCandidate(BaseModel):
    ticker: str
    name: str
    segment: str
    rationale: str
    evidence_keywords: list[str]
    evidence_count: int
    evidence_source_count: int = 0
    evidence_titles: list[str]
    status: str


class TopicDiscoveryService:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    def discover(self, topic: str) -> dict:
        result = self.llm.generate_with_metadata(self._prompt(topic))
        if result.fallback:
            return {
                "topic": topic,
                "fallback": True,
                "message": result.text,
                "plan": TopicDiscoveryPlan().model_dump(),
            }
        try:
            plan = self.parse_plan(result.text)
        except ValueError as exc:
            return {
                "topic": topic,
                "fallback": True,
                "message": f"AI discovery JSON parse failed: {exc}",
                "raw_preview": result.text[:500],
                "plan": TopicDiscoveryPlan().model_dump(),
            }
        return {
            "topic": topic,
            "fallback": False,
            "model": result.model,
            "key_index": result.key_index,
            "plan": plan.model_dump(),
        }

    def google_news_urls(
        self,
        plan: TopicDiscoveryPlan,
        include_international: bool = True,
        max_urls: int | None = None,
    ) -> list[str]:
        seen = set()
        urls = []
        queries: list[str] = []
        for subtopic in plan.subtopics:
            task_terms = " ".join(
                [subtopic.name, *subtopic.required_evidence[:2], *subtopic.risk_focus[:2]]
                if subtopic.required_evidence or subtopic.risk_focus
                else []
            )
            if task_terms.strip():
                queries.append(task_terms.strip())
            for query in subtopic.search_queries:
                queries.append(query)
                if include_international:
                    queries.append(f"{query} global market")
        for candidate in plan.candidate_companies:
            keywords = " ".join(candidate.evidence_keywords[:2])
            queries.append(f"{candidate.name} {keywords}".strip())
            queries.append(f"{candidate.ticker} {candidate.name}")
            if include_international:
                english_terms = " ".join(candidate.evidence_keywords[:3])
                queries.append(f"{candidate.name} {candidate.ticker} {english_terms} Taiwan stock")
                queries.append(f"{candidate.segment} {english_terms} global supply chain")
        if include_international:
            queries.extend(self._international_context_queries())
        for query in queries:
            normalized = query.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            urls.append(
                "https://news.google.com/rss/search?"
                f"q={quote_plus(normalized)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
            )
            if max_urls and len(urls) >= max_urls:
                break
        return urls

    def supplemental_google_news_urls(
        self,
        plan: TopicDiscoveryPlan,
        validated_candidates: list[ValidatedCandidate],
        include_international: bool = True,
        max_urls: int | None = None,
        existing_urls: list[str] | None = None,
    ) -> list[str]:
        supported_tickers = {
            candidate.ticker
            for candidate in validated_candidates
            if candidate.status == "evidence_supported"
        }
        weak_candidates = [
            candidate
            for candidate in plan.candidate_companies
            if candidate.ticker not in supported_tickers
        ]
        queries: list[str] = []
        for candidate in weak_candidates:
            keywords = " ".join(candidate.evidence_keywords[:3])
            queries.append(f"{candidate.ticker} {candidate.name} {candidate.segment} {keywords}".strip())
            queries.append(f"{candidate.name} {candidate.segment} 最新消息")
            if keywords:
                queries.append(f"{candidate.name} {keywords} 營收")
            if include_international:
                queries.append(f"{candidate.name} {candidate.ticker} Taiwan supplier {keywords}".strip())
                queries.append(f"{candidate.segment} {keywords} Taiwan listed company".strip())
        for subtopic in plan.subtopics:
            evidence_terms = " ".join(subtopic.required_evidence[:2])
            risk_terms = " ".join(subtopic.risk_focus[:2])
            queries.append(f"{subtopic.name} {subtopic.rationale} {evidence_terms} 台股".strip())
            if risk_terms:
                queries.append(f"{subtopic.name} {risk_terms} 風險 瓶頸".strip())
            for query in subtopic.search_queries[:2]:
                queries.append(f"{query} 最新")

        return self._google_news_urls_from_queries(
            queries,
            max_urls=max_urls,
            existing_urls=existing_urls or [],
        )

    @staticmethod
    def _google_news_urls_from_queries(
        queries: list[str],
        max_urls: int | None = None,
        existing_urls: list[str] | None = None,
    ) -> list[str]:
        seen = set(existing_urls or [])
        urls = []
        normalized_queries = set()
        for query in queries:
            normalized = query.strip()
            if not normalized or normalized in normalized_queries:
                continue
            normalized_queries.add(normalized)
            url = (
                "https://news.google.com/rss/search?"
                f"q={quote_plus(normalized)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
            )
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
            if max_urls and len(urls) >= max_urls:
                break
        return urls

    @staticmethod
    def _international_context_queries() -> list[str]:
        return [
            "NVIDIA AI server supply chain Taiwan ODM",
            "NVIDIA GB200 GB300 Rubin AI server supply chain",
            "CoWoS HBM capacity bottleneck global AI chips",
            "AI data center liquid cooling supply chain",
            "AI data center power grid constraint semiconductor",
            "US export controls AI chips Taiwan supply chain",
            "North American cloud AI server capex TrendForce",
        ]

    def validate_candidates(
        self,
        plan: TopicDiscoveryPlan,
        documents: list[NewsDocument],
    ) -> list[ValidatedCandidate]:
        validated: list[ValidatedCandidate] = []
        for candidate in plan.candidate_companies:
            evidence_documents = []
            entity_terms = self._candidate_entity_terms(candidate)
            context_terms = self._candidate_context_terms(candidate)
            for document in documents:
                haystack = f"{document.title}\n{document.text}"
                if self._has_entity_and_context(haystack, entity_terms, context_terms):
                    evidence_documents.append(document)
            deduped_titles = list(dict.fromkeys(document.title for document in evidence_documents))[:5]
            source_count = self._evidence_source_count(evidence_documents)
            validated.append(
                ValidatedCandidate(
                    ticker=candidate.ticker,
                    name=candidate.name,
                    segment=candidate.segment,
                    rationale=candidate.rationale,
                    evidence_keywords=candidate.evidence_keywords,
                    evidence_count=len(evidence_documents),
                    evidence_source_count=source_count,
                    evidence_titles=deduped_titles,
                    status=self._candidate_status(len(evidence_documents), source_count),
                )
            )
        return validated

    @staticmethod
    def _candidate_entity_terms(candidate: CandidateCompany) -> list[str]:
        terms = [candidate.ticker, candidate.name]
        whitelist = SupplyChainWhitelist()
        for company in whitelist.companies():
            if company.ticker == candidate.ticker or company.name == candidate.name:
                terms.extend(company.aliases)
                terms.append(company.name)
                break
        return list(dict.fromkeys(term for term in terms if term))

    @staticmethod
    def _candidate_context_terms(candidate: CandidateCompany) -> list[str]:
        return list(dict.fromkeys(term for term in candidate.evidence_keywords if term))

    @staticmethod
    def _has_entity_and_context(haystack: str, entity_terms: list[str], context_terms: list[str]) -> bool:
        normalized = haystack.lower()
        has_entity = any(term and term.lower() in normalized for term in entity_terms)
        if not has_entity:
            return False
        if not context_terms:
            return True
        return any(term and term.lower() in normalized for term in context_terms)

    @staticmethod
    def _evidence_source_count(documents: list[NewsDocument]) -> int:
        sources = {
            (document.source.publisher or document.source.url or document.source.title or document.title).strip()
            for document in documents
            if (document.source.publisher or document.source.url or document.source.title or document.title).strip()
        }
        return len(sources)

    @staticmethod
    def _candidate_status(evidence_count: int, source_count: int) -> str:
        if evidence_count == 0:
            return "needs_evidence"
        if evidence_count >= 2 and source_count >= 2:
            return "evidence_supported"
        return "weak_evidence"

    @staticmethod
    def parse_plan(raw_text: str) -> TopicDiscoveryPlan:
        json_text = TopicDiscoveryService._extract_json(raw_text)
        try:
            return TopicDiscoveryPlan.model_validate_json(json_text)
        except (ValidationError, ValueError) as exc:
            raise ValueError("invalid topic discovery json") from exc

    @staticmethod
    def _extract_json(raw_text: str) -> str:
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
        if fenced:
            return fenced.group(1)
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("json object not found")
        candidate = raw_text[start : end + 1]
        json.loads(candidate)
        return candidate

    @staticmethod
    def _prompt(topic: str) -> str:
        return f"""
你是台股產業研究助理。請針對主題「{topic}」自動拆解研究子題，並提出台股候選研究公司。

約束：
- 只能輸出 JSON，不要 Markdown，不要解釋，不要前後文。
- 回覆第一個字元必須是 {{，最後一個字元必須是 }}。
- subtopics 最多 5 筆；candidate_companies 最多 10 筆。
- rationale 每欄最多 25 個中文字；search query 每筆最多 30 個中文字。
- 子題應是一個可執行研究任務，不只是關鍵字。
- 每個子題需包含 objective、required_evidence、risk_focus，說明研究目的、需要查核的資料、需監控的風險。
- 子題應能驅動資料抓取，例如 CoWoS、HBM、AI 伺服器、液冷、地緣政治、缺電等，但不要固定死在這些範例。
- candidate_companies 是「候選研究清單」，不是正式投資推薦。
- 公司必須是台股 4 碼 ticker。
- 不確定 ticker 時不要輸出該公司。
- search_queries 要適合 Google News RSS 搜尋，使用繁體中文為主。
- 拆解時至少涵蓋：需求/成長、供給/產能、財務/營收、估值/股價、風險/瓶頸；若主題不適用可合併但不可完全缺漏。
- 不可把「熱門股票」當作子題；必須先說明產業因果，再提出候選公司。

JSON schema:
{{
  "subtopics": [
    {{
      "name": "string",
      "rationale": "string",
      "objective": "string",
      "required_evidence": ["營收", "產能", "訂單"],
      "risk_focus": ["供給瓶頸", "價格下修"],
      "search_queries": ["string"]
    }}
  ],
  "candidate_companies": [
    {{
      "ticker": "2330",
      "name": "台積電",
      "segment": "晶圓代工",
      "rationale": "string",
      "evidence_keywords": ["CoWoS", "HBM"]
    }}
  ]
}}
"""
