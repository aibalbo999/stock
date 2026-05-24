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


class DiscoveryPlanQuality(BaseModel):
    status: str
    score: int
    missing: list[str]
    coverage: dict[str, bool]
    subtopic_count: int
    candidate_count: int
    recommendation: str


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
            "plan_quality": self.evaluate_plan_quality(plan).model_dump(),
        }

    @staticmethod
    def evaluate_plan_quality(plan: TopicDiscoveryPlan) -> DiscoveryPlanQuality:
        missing = []
        if not plan.subtopics:
            missing.append("缺少研究子題")
        if not plan.candidate_companies:
            missing.append("缺少候選公司")
        for index, subtopic in enumerate(plan.subtopics, start=1):
            label = subtopic.name or f"子題 {index}"
            if not subtopic.objective.strip():
                missing.append(f"{label} 缺少研究目的")
            if not subtopic.required_evidence:
                missing.append(f"{label} 缺少必查證據")
            if not subtopic.risk_focus:
                missing.append(f"{label} 缺少風險焦點")
            if not subtopic.search_queries:
                missing.append(f"{label} 缺少搜尋 query")

        coverage = TopicDiscoveryService._plan_theme_coverage(plan)
        for theme, covered in coverage.items():
            if not covered:
                missing.append(f"缺少{theme}任務")

        complete_subtopics = sum(
            1
            for subtopic in plan.subtopics
            if subtopic.objective.strip()
            and subtopic.required_evidence
            and subtopic.risk_focus
            and subtopic.search_queries
        )
        score = 0
        if plan.subtopics:
            score += int(40 * complete_subtopics / len(plan.subtopics))
        score += int(30 * sum(1 for covered in coverage.values() if covered) / len(coverage))
        if plan.candidate_companies:
            score += 20
        if all(candidate.evidence_keywords for candidate in plan.candidate_companies):
            score += 10
        status = "ready" if score >= 80 and not missing else "caution" if score >= 55 else "insufficient"
        return DiscoveryPlanQuality(
            status=status,
            score=min(score, 100),
            missing=missing,
            coverage=coverage,
            subtopic_count=len(plan.subtopics),
            candidate_count=len(plan.candidate_companies),
            recommendation=(
                "拆解任務完整，可進入資料抓取。"
                if status == "ready"
                else "拆解任務可用但需留意缺口。"
                if status == "caution"
                else "拆解任務不足，應要求 AI 重新拆解或人工補充。"
            ),
        )

    @staticmethod
    def _plan_theme_coverage(plan: TopicDiscoveryPlan) -> dict[str, bool]:
        texts = [
            " ".join(
                [
                    subtopic.name,
                    subtopic.rationale,
                    subtopic.objective,
                    *subtopic.required_evidence,
                    *subtopic.risk_focus,
                    *subtopic.search_queries,
                ]
            ).lower()
            for subtopic in plan.subtopics
        ]
        joined = "\n".join(texts)
        themes = {
            "需求/成長": ["需求", "成長", "訂單", "出貨", "市場規模", "capex", "demand", "growth"],
            "供給/產能": ["供給", "產能", "良率", "供應", "瓶頸", "capacity", "supply", "yield"],
            "財務/營收": ["財務", "營收", "毛利", "獲利", "現金流", "revenue", "margin", "profit"],
            "估值/股價": ["估值", "股價", "本益比", "pe", "p/e", "pb", "valuation", "price"],
            "風險/瓶頸": ["風險", "瓶頸", "限制", "缺電", "地緣", "管制", "risk", "bottleneck"],
        }
        return {
            theme: any(keyword in joined for keyword in keywords)
            for theme, keywords in themes.items()
        }

    def google_news_urls(
        self,
        plan: TopicDiscoveryPlan,
        include_international: bool = True,
        max_urls: int | None = None,
        topic: str | None = None,
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
        if topic:
            queries.extend(self.coverage_gap_queries(topic, self.evaluate_plan_quality(plan)))
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

    @staticmethod
    def coverage_gap_queries(topic: str, quality: DiscoveryPlanQuality) -> list[str]:
        if quality.status == "ready":
            return []
        query_terms = {
            "需求/成長": ["需求 成長 訂單 出貨", "市場規模 展望"],
            "供給/產能": ["供給 產能 良率 瓶頸", "供應鏈 交期"],
            "財務/營收": ["營收 毛利 獲利", "財報 現金流"],
            "估值/股價": ["股價 估值 本益比", "同業 比較"],
            "風險/瓶頸": ["風險 瓶頸 限制", "地緣政治 缺電 管制"],
        }
        queries = []
        for theme, covered in quality.coverage.items():
            if covered:
                continue
            for terms in query_terms.get(theme, []):
                queries.append(f"{topic} {terms}".strip())
        return queries

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
