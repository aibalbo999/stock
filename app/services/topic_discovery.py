from __future__ import annotations

import json
import re
from datetime import date
from typing import Optional
from urllib.parse import quote_plus

from pydantic import BaseModel, Field, ValidationError

from app.core.time import today_taipei
from app.models.schemas import NewsDocument
from app.services.candidate_confidence import confidence_level, is_high_confidence
from app.services.llm_client import LLMClient
from app.services.whitelist import SupplyChainWhitelist


class DiscoverySubtopic(BaseModel):
    name: str = Field(min_length=1)
    rationale: str = ""
    objective: str = ""
    required_evidence: list[str] = Field(default_factory=list, max_length=6)
    risk_focus: list[str] = Field(default_factory=list, max_length=6)
    search_queries: list[str] = Field(default_factory=list, max_length=5)
    source_intents: list[str] = Field(default_factory=list, max_length=6)


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
    query_quality: dict = Field(default_factory=dict)
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
    evidence_sources: list[dict] = Field(default_factory=list)
    evidence_confidence_score: int = 0
    evidence_confidence_label: str = "低"
    latest_evidence_date: Optional[str] = None
    status: str
    validation_reason: str = ""
    next_action: str = ""
    promotion_eligible: bool = False


class TopicDiscoveryService:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    def discover(self, topic: str) -> dict:
        result = self.llm.generate_with_metadata(self._prompt(topic))
        if result.fallback:
            fallback_plan = self._fallback_plan(topic)
            fallback_quality = self.evaluate_plan_quality(fallback_plan)
            return {
                "topic": topic,
                "fallback": True,
                "message": result.text,
                "plan": fallback_plan.model_dump(),
                "plan_quality": fallback_quality.model_dump(),
                "initial_plan_quality": self.evaluate_plan_quality(TopicDiscoveryPlan()).model_dump(),
                "repair_attempted": False,
                "repair_applied": False,
                "fallback_plan_applied": True,
            }
        try:
            plan = self.parse_plan(result.text)
        except ValueError as exc:
            fallback_plan = self._fallback_plan(topic)
            fallback_quality = self.evaluate_plan_quality(fallback_plan)
            return {
                "topic": topic,
                "fallback": True,
                "message": f"AI discovery JSON parse failed: {exc}",
                "raw_preview": result.text[:500],
                "plan": fallback_plan.model_dump(),
                "plan_quality": fallback_quality.model_dump(),
                "initial_plan_quality": self.evaluate_plan_quality(TopicDiscoveryPlan()).model_dump(),
                "repair_attempted": False,
                "repair_applied": False,
                "fallback_plan_applied": True,
            }
        initial_quality = self.evaluate_plan_quality(plan)
        repair = None
        final_plan = plan
        final_quality = initial_quality
        if initial_quality.status != "ready":
            repair = self.repair_plan(topic, plan, initial_quality)
            if repair is not None and repair["quality"].score >= initial_quality.score:
                final_plan = repair["plan"]
                final_quality = repair["quality"]
        fallback_plan_applied = False
        if final_quality.status == "insufficient":
            fallback_plan = self._fallback_plan(topic)
            fallback_quality = self.evaluate_plan_quality(fallback_plan)
            if fallback_quality.score > final_quality.score:
                final_plan = fallback_plan
                final_quality = fallback_quality
                fallback_plan_applied = True
        return {
            "topic": topic,
            "fallback": fallback_plan_applied,
            "model": result.model,
            "key_index": result.key_index,
            "plan": final_plan.model_dump(),
            "plan_quality": final_quality.model_dump(),
            "initial_plan_quality": initial_quality.model_dump(),
            "repair_attempted": initial_quality.status != "ready",
            "repair_applied": final_plan is not plan,
            "fallback_plan_applied": fallback_plan_applied,
            "repair_model": repair["model"] if repair else None,
            "repair_key_index": repair["key_index"] if repair else None,
        }

    def repair_plan(
        self,
        topic: str,
        plan: TopicDiscoveryPlan,
        quality: DiscoveryPlanQuality,
    ) -> dict | None:
        result = self.llm.generate_with_metadata(self._repair_prompt(topic, plan, quality))
        if result.fallback:
            return None
        try:
            repaired_plan = self.parse_plan(result.text)
        except ValueError:
            return None
        return {
            "plan": repaired_plan,
            "quality": self.evaluate_plan_quality(repaired_plan),
            "model": result.model,
            "key_index": result.key_index,
        }

    @staticmethod
    def _fallback_plan(topic: str) -> TopicDiscoveryPlan:
        if "AI" not in topic.upper() and "人工智慧" not in topic:
            return TopicDiscoveryService.enrich_plan(
                TopicDiscoveryPlan(
                subtopics=[
                    DiscoverySubtopic(
                        name=f"{topic} 需求與成長",
                        rationale="確認產業需求",
                        objective="查核需求、訂單與營收是否支持投資假設",
                        required_evidence=["需求", "訂單", "營收"],
                        risk_focus=["需求下修", "競爭加劇"],
                        search_queries=[f"{topic} 需求 訂單 營收", f"{topic} demand revenue outlook"],
                    ),
                    DiscoverySubtopic(
                        name=f"{topic} 估值與風險",
                        rationale="避免只看題材",
                        objective="比較估值、股價與主要風險",
                        required_evidence=["股價", "本益比", "風險"],
                        risk_focus=["估值過高", "政策風險"],
                        search_queries=[f"{topic} 台股 估值 本益比 風險", f"{topic} valuation risk"],
                    ),
                ],
                candidate_companies=[],
                )
            )
        return TopicDiscoveryService.enrich_plan(
            TopicDiscoveryPlan(
            subtopics=[
                DiscoverySubtopic(
                    name="AI 伺服器需求",
                    rationale="雲端資本支出",
                    objective="確認 CSP 資本支出、AI 伺服器出貨與台廠訂單是否成長",
                    required_evidence=["CSP 資本支出", "AI 伺服器出貨", "月營收"],
                    risk_focus=["需求下修", "砍單", "客戶集中"],
                    search_queries=["AI 伺服器 出貨 月營收 台廠", "cloud capex AI server 出貨 月營收"],
                ),
                DiscoverySubtopic(
                    name="CoWoS 與 HBM 產能",
                    rationale="上游瓶頸",
                    objective="查核先進封裝、HBM 與良率是否限制 AI 晶片出貨",
                    required_evidence=["CoWoS 產能", "HBM 供給", "良率"],
                    risk_focus=["產能滿載", "良率問題", "交期延遲"],
                    search_queries=["台積電 CoWoS 產能 HBM 良率", "CoWoS HBM capacity bottleneck"],
                ),
                DiscoverySubtopic(
                    name="液冷散熱與電源",
                    rationale="功耗升級",
                    objective="確認液冷、散熱與高功率電源是否形成成長或出貨瓶頸",
                    required_evidence=["液冷訂單", "散熱滲透率", "電源規格"],
                    risk_focus=["技術轉換延遲", "認證延遲", "毛利壓力"],
                    search_queries=["AI 伺服器 液冷訂單 散熱滲透率 電源規格", "AI data center liquid cooling 電源規格"],
                ),
                DiscoverySubtopic(
                    name="高速 PCB 與載板",
                    rationale="訊號與材料升級",
                    objective="確認 AI 伺服器 PCB、載板與高速材料是否受惠或形成供給瓶頸",
                    required_evidence=["PCB 訂單", "載板需求", "高速材料"],
                    risk_focus=["良率瓶頸", "價格下修", "庫存調整"],
                    search_queries=["AI 伺服器 PCB 載板 高速材料", "AI server PCB substrate CCL Taiwan"],
                ),
                DiscoverySubtopic(
                    name="財務與估值",
                    rationale="避免題材追高",
                    objective="比較候選公司營收、獲利、現金流、P/E 與 P/B 是否支持評價",
                    required_evidence=["月營收", "毛利率", "本益比", "現金流"],
                    risk_focus=["估值過高", "營收放緩", "毛利下滑"],
                    search_queries=["台股 AI 供應鏈 月營收 本益比 估值", "Taiwan AI valuation revenue margin 本益比"],
                ),
                DiscoverySubtopic(
                    name="地緣政治與電力",
                    rationale="外部限制",
                    objective="評估出口管制、缺電與資料中心電網限制對供應鏈的影響",
                    required_evidence=["出口管制", "缺電", "電網負荷"],
                    risk_focus=["美國晶片管制", "地緣政治", "電力瓶頸"],
                    search_queries=["AI 晶片 出口管制 台灣 供應鏈 缺電", "US export controls AI chips 電網負荷"],
                ),
            ],
            candidate_companies=[
                CandidateCompany(
                    ticker="2330",
                    name="台積電",
                    segment="晶圓代工",
                    rationale="CoWoS 與先進製程",
                    evidence_keywords=["CoWoS", "先進封裝", "AI 晶片"],
                ),
                CandidateCompany(
                    ticker="2382",
                    name="廣達",
                    segment="AI 伺服器代工",
                    rationale="CSP 伺服器代工",
                    evidence_keywords=["AI 伺服器", "CSP", "出貨"],
                ),
                CandidateCompany(
                    ticker="3231",
                    name="緯創",
                    segment="AI 伺服器代工",
                    rationale="伺服器與 GPU 基板",
                    evidence_keywords=["AI 伺服器", "GPU", "出貨"],
                ),
                CandidateCompany(
                    ticker="3324",
                    name="雙鴻",
                    segment="散熱模組",
                    rationale="液冷散熱升級",
                    evidence_keywords=["液冷", "散熱", "水冷板"],
                ),
                CandidateCompany(
                    ticker="3017",
                    name="奇鋐",
                    segment="散熱模組",
                    rationale="液冷與散熱供應",
                    evidence_keywords=["液冷", "散熱", "CDU"],
                ),
                CandidateCompany(
                    ticker="2059",
                    name="川湖",
                    segment="伺服器導軌",
                    rationale="AI 伺服器導軌",
                    evidence_keywords=["伺服器導軌", "AI 伺服器", "毛利率"],
                ),
                CandidateCompany(
                    ticker="3131",
                    name="弘塑",
                    segment="先進封裝設備",
                    rationale="CoWoS 設備供應",
                    evidence_keywords=["CoWoS", "先進封裝", "設備"],
                ),
                CandidateCompany(
                    ticker="3583",
                    name="辛耘",
                    segment="半導體設備",
                    rationale="先進封裝設備",
                    evidence_keywords=["CoWoS", "先進封裝", "設備"],
                ),
                CandidateCompany(
                    ticker="2308",
                    name="台達電",
                    segment="電源與散熱",
                    rationale="資料中心電源",
                    evidence_keywords=["電源", "資料中心", "液冷"],
                ),
                CandidateCompany(
                    ticker="6669",
                    name="緯穎",
                    segment="AI 伺服器",
                    rationale="CSP 伺服器",
                    evidence_keywords=["AI 伺服器", "CSP", "資料中心"],
                ),
                CandidateCompany(
                    ticker="2317",
                    name="鴻海",
                    segment="AI 伺服器代工",
                    rationale="伺服器與機櫃整合",
                    evidence_keywords=["AI 伺服器", "機櫃", "CSP"],
                ),
                CandidateCompany(
                    ticker="2356",
                    name="英業達",
                    segment="AI 伺服器代工",
                    rationale="伺服器代工",
                    evidence_keywords=["AI 伺服器", "雲端", "出貨"],
                ),
                CandidateCompany(
                    ticker="2376",
                    name="技嘉",
                    segment="AI 伺服器與主機板",
                    rationale="伺服器板卡",
                    evidence_keywords=["AI 伺服器", "主機板", "GPU"],
                ),
                CandidateCompany(
                    ticker="2377",
                    name="微星",
                    segment="AI 伺服器與板卡",
                    rationale="伺服器板卡",
                    evidence_keywords=["AI 伺服器", "GPU", "主機板"],
                ),
                CandidateCompany(
                    ticker="3706",
                    name="神達",
                    segment="AI 伺服器",
                    rationale="伺服器系統",
                    evidence_keywords=["AI 伺服器", "資料中心", "系統"],
                ),
                CandidateCompany(
                    ticker="2368",
                    name="金像電",
                    segment="AI 伺服器 PCB",
                    rationale="高階伺服器板",
                    evidence_keywords=["AI 伺服器", "PCB", "高速板"],
                ),
                CandidateCompany(
                    ticker="3037",
                    name="欣興",
                    segment="ABF 載板 / PCB",
                    rationale="載板與高階板",
                    evidence_keywords=["ABF", "載板", "AI 伺服器"],
                ),
                CandidateCompany(
                    ticker="8046",
                    name="南電",
                    segment="ABF 載板",
                    rationale="高階載板",
                    evidence_keywords=["ABF", "載板", "AI 晶片"],
                ),
                CandidateCompany(
                    ticker="6274",
                    name="台燿",
                    segment="高速材料 / CCL",
                    rationale="高速材料升級",
                    evidence_keywords=["CCL", "高速材料", "AI 伺服器"],
                ),
                CandidateCompany(
                    ticker="3653",
                    name="健策",
                    segment="散熱與金屬件",
                    rationale="高功耗散熱",
                    evidence_keywords=["散熱", "均熱片", "AI 伺服器"],
                ),
            ],
            )
        )

    @staticmethod
    def evaluate_plan_quality(plan: TopicDiscoveryPlan) -> DiscoveryPlanQuality:
        missing = []
        query_quality = TopicDiscoveryService._plan_query_quality(plan)
        if not plan.subtopics:
            missing.append("缺少研究子題")
        if not plan.candidate_companies:
            missing.append("缺少候選公司")
        if TopicDiscoveryService._requires_broad_candidate_pool(plan) and len(plan.candidate_companies) < 15:
            missing.append("AI 產業鏈候選公司少於 15 檔，容易漏掉伺服器、散熱、PCB、電源與設備環節")
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
            subtopic_query_quality = query_quality["subtopics"].get(label, {})
            if subtopic.search_queries and not subtopic_query_quality.get("has_international_query"):
                missing.append(f"{label} 缺少國際資料 query")
            for query in subtopic_query_quality.get("generic_queries", [])[:2]:
                missing.append(f"{label} 搜尋 query 過於籠統：{query}")
            for query in subtopic_query_quality.get("unaligned_queries", [])[:2]:
                missing.append(f"{label} 搜尋 query 未對應研究證據或風險：{query}")

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
            and query_quality["subtopics"].get(subtopic.name or "", {}).get("has_international_query")
            and not query_quality["subtopics"].get(subtopic.name or "", {}).get("generic_queries")
            and not query_quality["subtopics"].get(subtopic.name or "", {}).get("unaligned_queries")
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
            query_quality=query_quality,
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
    def _requires_broad_candidate_pool(plan: TopicDiscoveryPlan) -> bool:
        if len(plan.subtopics) < 4:
            return False
        text = " ".join(
            [
                *[
                    " ".join(
                        [
                            subtopic.name,
                            subtopic.rationale,
                            subtopic.objective,
                            *subtopic.required_evidence,
                            *subtopic.risk_focus,
                            *subtopic.search_queries,
                        ]
                    )
                    for subtopic in plan.subtopics
                ],
                *[
                    " ".join([candidate.segment, candidate.rationale, *candidate.evidence_keywords])
                    for candidate in plan.candidate_companies
                ],
            ]
        ).lower()
        has_ai_theme = any(term in text for term in ["ai", "人工智慧", "伺服器", "server", "資料中心", "datacenter"])
        has_supply_chain_theme = any(
            term in text
            for term in ["cowos", "hbm", "封裝", "散熱", "液冷", "電源", "pcb", "載板", "設備", "供應鏈"]
        )
        return has_ai_theme and has_supply_chain_theme

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
                    *subtopic.source_intents,
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

    @staticmethod
    def _plan_query_quality(plan: TopicDiscoveryPlan) -> dict:
        subtopic_quality = {}
        total_queries = 0
        aligned_queries = 0
        international_query_count = 0
        generic_query_count = 0
        for subtopic in plan.subtopics:
            label = subtopic.name or "未命名子題"
            generic_queries = []
            unaligned_queries = []
            languages = []
            for query in subtopic.search_queries:
                total_queries += 1
                language = TopicDiscoveryService._query_language(query)
                languages.append(language)
                if TopicDiscoveryService._is_generic_query(query):
                    generic_queries.append(query)
                    generic_query_count += 1
                    continue
                if language in {"en", "mixed"}:
                    international_query_count += 1
                if TopicDiscoveryService._query_aligns_subtopic(query, subtopic):
                    aligned_queries += 1
                else:
                    unaligned_queries.append(query)
            subtopic_quality[label] = {
                "query_count": len(subtopic.search_queries),
                "languages": languages,
                "has_international_query": any(
                    TopicDiscoveryService._query_language(query) in {"en", "mixed"}
                    and not TopicDiscoveryService._is_generic_query(query)
                    for query in subtopic.search_queries
                ),
                "generic_queries": generic_queries,
                "unaligned_queries": unaligned_queries,
            }
        return {
            "total_queries": total_queries,
            "aligned_queries": aligned_queries,
            "international_query_count": international_query_count,
            "generic_query_count": generic_query_count,
            "subtopics": subtopic_quality,
        }

    @staticmethod
    def _query_aligns_subtopic(query: str, subtopic: DiscoverySubtopic) -> bool:
        query_text = query.lower()
        terms = TopicDiscoveryService._research_terms(subtopic)
        return any(term.lower() in query_text for term in terms)

    @staticmethod
    def _research_terms(subtopic: DiscoverySubtopic) -> list[str]:
        raw_terms = [
            subtopic.name,
            *subtopic.required_evidence,
            *subtopic.risk_focus,
            *TopicDiscoveryService._meaningful_tokens(subtopic.objective),
            *TopicDiscoveryService._meaningful_tokens(subtopic.rationale),
        ]
        return [
            term
            for term in dict.fromkeys(term.strip() for term in raw_terms)
            if term and not TopicDiscoveryService._is_noise_term(term)
        ]

    @staticmethod
    def _meaningful_tokens(text: str) -> list[str]:
        return [
            token
            for token in re.findall(r"[A-Za-z][A-Za-z0-9+\-/]{1,}|\d{2,}|[\u4e00-\u9fff]{2,}", text)
            if not TopicDiscoveryService._is_noise_term(token)
        ]

    @staticmethod
    def _is_generic_query(query: str) -> bool:
        tokens = TopicDiscoveryService._meaningful_tokens(query)
        if len(tokens) <= 1:
            return True
        signal_tokens = [token for token in tokens if not TopicDiscoveryService._is_noise_term(token)]
        return len(signal_tokens) <= 1

    @staticmethod
    def _is_noise_term(term: str) -> bool:
        normalized = term.strip().lower()
        return normalized in {
            "ai",
            "台股",
            "股票",
            "概念股",
            "熱門",
            "產業",
            "供應鏈",
            "最新",
            "市場",
            "global",
            "market",
            "stock",
            "stocks",
            "company",
            "companies",
            "supplier",
            "supply",
            "chain",
        }

    def google_news_urls(
        self,
        plan: TopicDiscoveryPlan,
        include_international: bool = True,
        max_urls: int | None = None,
        topic: str | None = None,
        include_metadata: bool = False,
    ) -> list[str] | list[dict]:
        seen = set()
        urls: list[str] = []
        metadata: list[dict] = []
        queries: list[dict] = []
        for subtopic in plan.subtopics:
            task_terms = " ".join(
                [subtopic.name, *subtopic.required_evidence[:2], *subtopic.risk_focus[:2]]
                if subtopic.required_evidence or subtopic.risk_focus
                else []
            )
            if task_terms.strip():
                queries.append(
                    self._query_item(
                        task_terms.strip(),
                        "research_task",
                        self._subtopic_hypothesis(subtopic),
                        self._evidence_type(subtopic.required_evidence, subtopic.risk_focus),
                        self._primary_source_intent(subtopic),
                    )
                )
            for query in subtopic.search_queries:
                queries.append(
                    self._query_item(
                        query,
                        "subtopic",
                        self._subtopic_hypothesis(subtopic),
                        self._evidence_type(subtopic.required_evidence, subtopic.risk_focus),
                        self._primary_source_intent(subtopic),
                    )
                )
                if include_international:
                    queries.append(
                        self._query_item(
                            f"{query} global market",
                            "subtopic_international",
                            self._subtopic_hypothesis(subtopic),
                            self._evidence_type(subtopic.required_evidence, subtopic.risk_focus),
                            "international_context",
                        )
                    )
        for candidate in plan.candidate_companies:
            keywords = " ".join(candidate.evidence_keywords[:2])
            candidate_hypothesis = f"驗證 {candidate.ticker} {candidate.name} 是否與「{candidate.segment}」及主題證據直接相關。"
            queries.append(
                self._query_item(
                    f"{candidate.name} {keywords}".strip(),
                    "candidate",
                    candidate_hypothesis,
                    "候選公司證據",
                    "company_disclosure",
                )
            )
            queries.append(
                self._query_item(
                    f"{candidate.ticker} {candidate.name}",
                    "candidate",
                    candidate_hypothesis,
                    "公司實體驗證",
                    "company_disclosure",
                )
            )
            if include_international:
                english_terms = " ".join(candidate.evidence_keywords[:3])
                queries.append(
                    self._query_item(
                        f"{candidate.name} {candidate.ticker} {english_terms} Taiwan stock",
                        "candidate_international",
                        candidate_hypothesis,
                        "國際供應鏈證據",
                        "international_context",
                    )
                )
                queries.append(
                    self._query_item(
                        f"{candidate.segment} {english_terms} global supply chain",
                        "candidate_international",
                        candidate_hypothesis,
                        "國際供應鏈證據",
                        "international_context",
                    )
                )
        if topic:
            plan_quality = self.evaluate_plan_quality(plan)
            queries.extend(
                self._query_item(
                    query,
                    "query_quality_gap",
                    f"補強「{topic}」中過於籠統、未對齊或缺國際資料的搜尋 query。",
                    "查詢品質補強",
                    "industry_news",
                )
                for query in self.query_quality_gap_queries(topic, plan, plan_quality)
            )
            queries.extend(
                self._query_item(
                    query,
                    "coverage_gap",
                    f"補齊「{topic}」研究拆解品質缺口。",
                    "品質缺口補強",
                    "industry_news",
                )
                for query in self.coverage_gap_queries(topic, plan_quality)
            )
        if include_international:
            queries.extend(
                self._query_item(
                    query,
                    "international_context",
                    "補充國際市場、雲端資本支出與供應鏈背景，避免只看台灣新聞。",
                    "國際背景",
                    "international_context",
                )
                for query in self._international_context_queries()
            )
        for item in queries:
            query = item["query"]
            normalized = query.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            url = (
                "https://news.google.com/rss/search?"
                f"q={quote_plus(normalized)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
            )
            urls.append(url)
            metadata.append({**item, "url": url, "query": normalized, "language": self._query_language(normalized)})
            if max_urls and len(urls) >= max_urls:
                break
        return metadata if include_metadata else urls

    @staticmethod
    def _query_item(
        query: str,
        source_type: str,
        hypothesis: str,
        evidence_type: str,
        source_intent: str,
    ) -> dict:
        return {
            "query": query,
            "source_type": source_type,
            "hypothesis": hypothesis,
            "evidence_type": evidence_type,
            "source_intent": source_intent,
        }

    @staticmethod
    def _subtopic_hypothesis(subtopic: DiscoverySubtopic) -> str:
        objective = subtopic.objective.strip()
        if objective:
            return objective
        return f"驗證「{subtopic.name}」是否影響本主題的投資機會或風險。"

    @staticmethod
    def _evidence_type(required_evidence: list[str], risk_focus: list[str]) -> str:
        text = " ".join([*required_evidence, *risk_focus]).lower()
        if any(term in text for term in ["估值", "股價", "本益比", "pe", "valuation"]):
            return "估值/股價"
        if any(term in text for term in ["營收", "財務", "毛利", "獲利", "revenue", "margin"]):
            return "財務/營收"
        if any(term in text for term in ["風險", "瓶頸", "缺電", "地緣", "管制", "risk"]):
            return "風險/瓶頸"
        if any(term in text for term in ["產能", "供給", "良率", "capacity", "supply"]):
            return "供給/產能"
        return "需求/成長"

    @staticmethod
    def _primary_source_intent(subtopic: DiscoverySubtopic) -> str:
        if subtopic.source_intents:
            return subtopic.source_intents[0]
        return TopicDiscoveryService.infer_source_intents(subtopic)[0]

    @staticmethod
    def _query_language(query: str) -> str:
        has_cjk = any("\u4e00" <= char <= "\u9fff" for char in query)
        has_ascii = any(char.isascii() and char.isalpha() for char in query)
        if has_cjk and has_ascii:
            return "mixed"
        if has_cjk:
            return "zh"
        return "en"

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

    @staticmethod
    def query_quality_gap_queries(topic: str, plan: TopicDiscoveryPlan, quality: DiscoveryPlanQuality) -> list[str]:
        query_quality = quality.query_quality or {}
        subtopic_quality = query_quality.get("subtopics") or {}
        queries = []
        for subtopic in plan.subtopics:
            label = subtopic.name or "未命名子題"
            detail = subtopic_quality.get(label) or {}
            evidence_terms = " ".join(subtopic.required_evidence[:2])
            risk_terms = " ".join(subtopic.risk_focus[:1])
            base = " ".join(part for part in [topic, subtopic.name, evidence_terms, risk_terms] if part).strip()
            if not base:
                continue
            if detail.get("generic_queries") or detail.get("unaligned_queries"):
                queries.append(base)
            if subtopic.search_queries and not detail.get("has_international_query"):
                queries.append(f"{base} global market")
        return list(dict.fromkeys(query for query in queries if query))

    def supplemental_google_news_urls(
        self,
        plan: TopicDiscoveryPlan,
        validated_candidates: list[ValidatedCandidate],
        include_international: bool = True,
        max_urls: int | None = None,
        existing_urls: list[str] | None = None,
    ) -> list[str]:
        return [
            item["url"]
            for item in self.supplemental_google_news_query_metadata(
                plan,
                validated_candidates,
                include_international=include_international,
                max_urls=max_urls,
                existing_urls=existing_urls,
            )
        ]

    def supplemental_google_news_query_metadata(
        self,
        plan: TopicDiscoveryPlan,
        validated_candidates: list[ValidatedCandidate],
        include_international: bool = True,
        max_urls: int | None = None,
        existing_urls: list[str] | None = None,
        missing_subtopics: list[str] | None = None,
    ) -> list[dict]:
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
        target_names = set(missing_subtopics or [])
        target_subtopics = [
            subtopic
            for subtopic in plan.subtopics
            if not target_names or (subtopic.name or "未命名子題") in target_names
        ]
        for subtopic in target_subtopics:
            evidence_terms = " ".join(subtopic.required_evidence[:2])
            risk_terms = " ".join(subtopic.risk_focus[:2])
            queries.append(f"{subtopic.name} {subtopic.rationale} {evidence_terms} 台股".strip())
            if risk_terms:
                queries.append(f"{subtopic.name} {risk_terms} 風險 瓶頸".strip())
            for query in subtopic.search_queries[:2]:
                queries.append(f"{query} 最新")

        return self._google_news_metadata_from_queries(
            queries,
            source_type="supplemental",
            hypothesis="補強弱證據候選與低覆蓋子題，重新驗證是否可進入正式分析。",
            evidence_type="補抓資料源",
            source_intent="company_disclosure",
            max_urls=max_urls,
            existing_urls=existing_urls or [],
        )

    @staticmethod
    def missing_subtopic_names(source_relevance: dict) -> list[str]:
        readiness = source_relevance.get("subtopic_readiness") or {}
        return [
            name
            for name, detail in readiness.items()
            if isinstance(detail, dict) and detail.get("status") == "missing"
        ]

    @staticmethod
    def _google_news_urls_from_queries(
        queries: list[str],
        max_urls: int | None = None,
        existing_urls: list[str] | None = None,
    ) -> list[str]:
        return [
            item["url"]
            for item in TopicDiscoveryService._google_news_metadata_from_queries(
                queries,
                source_type="supplemental",
                hypothesis="補強資料來源。",
                evidence_type="補抓資料源",
                source_intent="industry_news",
                max_urls=max_urls,
                existing_urls=existing_urls,
            )
        ]

    @staticmethod
    def _google_news_metadata_from_queries(
        queries: list[str],
        source_type: str,
        hypothesis: str,
        evidence_type: str,
        source_intent: str = "industry_news",
        max_urls: int | None = None,
        existing_urls: list[str] | None = None,
    ) -> list[dict]:
        seen = set(existing_urls or [])
        metadata = []
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
            metadata.append(
                {
                    "url": url,
                    "query": normalized,
                    "source_type": source_type,
                    "hypothesis": hypothesis,
                    "evidence_type": evidence_type,
                    "source_intent": source_intent,
                    "language": TopicDiscoveryService._query_language(normalized),
                }
            )
            if max_urls and len(metadata) >= max_urls:
                break
        return metadata

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
            context_terms = self._candidate_context_terms(candidate, plan)
            for document in documents:
                haystack = f"{document.title}\n{document.text}"
                if self._has_entity_and_context(haystack, entity_terms, context_terms):
                    evidence_documents.append(document)
            deduped_titles = list(dict.fromkeys(document.title for document in evidence_documents))[:5]
            source_count = self._evidence_source_count(evidence_documents)
            evidence_sources = self._candidate_evidence_sources(evidence_documents)
            confidence = self._candidate_evidence_confidence(evidence_documents, source_count)
            status = self._candidate_status(len(evidence_documents), source_count, confidence["score"])
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
                    evidence_sources=evidence_sources,
                    evidence_confidence_score=confidence["score"],
                    evidence_confidence_label=confidence["label"],
                    latest_evidence_date=confidence["latest_evidence_date"],
                    status=status,
                    validation_reason=self._candidate_validation_reason(
                        len(evidence_documents),
                        source_count,
                        confidence["score"],
                    ),
                    next_action=self._candidate_next_action(len(evidence_documents), source_count, confidence["score"]),
                    promotion_eligible=status == "evidence_supported",
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
    def _candidate_context_terms(candidate: CandidateCompany, plan: TopicDiscoveryPlan | None = None) -> list[str]:
        terms = []
        terms.extend(candidate.evidence_keywords)
        terms.extend(TopicDiscoveryService._context_phrases(candidate.segment))
        terms.extend(TopicDiscoveryService._context_phrases(candidate.rationale))
        for subtopic in (plan.subtopics if plan else []):
            terms.extend(TopicDiscoveryService._context_phrases(subtopic.name))
            terms.extend(subtopic.required_evidence)
            terms.extend(subtopic.risk_focus)
        terms.extend(
            [
                "AI 伺服器",
                "AI伺服器",
                "資料中心",
                "CoWoS",
                "HBM",
                "先進封裝",
                "液冷",
                "散熱",
                "電源",
                "算力",
                "雲端",
                "CSP",
                "capex",
                "server",
            ]
        )
        return list(dict.fromkeys(term.strip() for term in terms if term and term.strip()))

    @staticmethod
    def _context_phrases(text: str) -> list[str]:
        if not text:
            return []
        normalized = re.sub(r"[，,。；;：:（）()、/|]+", " ", text)
        parts = [part.strip() for part in normalized.split() if len(part.strip()) >= 2]
        phrases = [text.strip()]
        phrases.extend(parts)
        return phrases

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
    def _candidate_evidence_sources(documents: list[NewsDocument], limit: int = 5) -> list[dict]:
        sources = []
        seen = set()
        for document in documents:
            source_key = (
                document.title,
                document.source.publisher,
                document.source.url,
                document.source.published_at.isoformat() if document.source.published_at else "",
            )
            if source_key in seen:
                continue
            seen.add(source_key)
            sources.append(
                {
                    "title": document.title,
                    "publisher": document.source.publisher or document.source.title or "",
                    "published_at": document.source.published_at.isoformat() if document.source.published_at else None,
                    "url": document.source.url,
                }
            )
            if len(sources) >= limit:
                break
        return sources

    @staticmethod
    def _candidate_evidence_confidence(documents: list[NewsDocument], source_count: int) -> dict:
        evidence_count = len(documents)
        dated_documents = [document for document in documents if document.source.published_at]
        latest_date = max((document.source.published_at for document in dated_documents), default=None)
        evidence_score = min(evidence_count, 3) / 3 * 35
        source_score = min(source_count, 3) / 3 * 35
        timestamp_score = (len(dated_documents) / evidence_count * 10) if evidence_count else 0
        recency_score = TopicDiscoveryService._recency_score(latest_date)
        score = int(round(evidence_score + source_score + timestamp_score + recency_score))
        return {
            "score": min(score, 100),
            "label": TopicDiscoveryService._confidence_label(score),
            "latest_evidence_date": latest_date.isoformat() if latest_date else None,
        }

    @staticmethod
    def _recency_score(latest_date: Optional[date]) -> int:
        if latest_date is None:
            return 0
        age_days = (today_taipei() - latest_date).days
        if age_days <= 30:
            return 20
        if age_days <= 90:
            return 12
        if age_days <= 180:
            return 6
        return 0

    @staticmethod
    def _confidence_label(score: int) -> str:
        return confidence_level(score)

    @staticmethod
    def _candidate_status(evidence_count: int, source_count: int, confidence_score: int = 0) -> str:
        if evidence_count == 0:
            return "needs_evidence"
        if evidence_count >= 2 and source_count >= 2 and is_high_confidence(confidence_score):
            return "evidence_supported"
        return "weak_evidence"

    @staticmethod
    def _candidate_validation_reason(evidence_count: int, source_count: int, confidence_score: int = 0) -> str:
        if evidence_count >= 2 and source_count >= 2 and is_high_confidence(confidence_score):
            return "通過正式分析門檻：至少 2 篇公司主題證據、2 個以上來源，且證據信心達高分。"
        if evidence_count >= 2 and source_count >= 2:
            return f"弱證據：篇數與來源數達標，但證據信心只有 {confidence_score} 分，需補近期或有日期來源。"
        if evidence_count > 0:
            return f"弱證據：目前只有 {evidence_count} 篇、{source_count} 個來源，避免單一來源造成誤判。"
        return "待補證據：尚未找到公司實體與主題上下文同時成立的來源。"

    @staticmethod
    def _candidate_next_action(evidence_count: int, source_count: int, confidence_score: int = 0) -> str:
        if evidence_count >= 2 and source_count >= 2 and is_high_confidence(confidence_score):
            return "納入正式分析。"
        if evidence_count >= 2 and source_count >= 2:
            return "補抓有日期、近期且不同發布者的公司與主題來源後再驗證。"
        if evidence_count > 0:
            return "補抓公司新聞、法說會、月營收與國際供應鏈資料後再驗證。"
        return "用公司名稱、代號、產業位置與主題關鍵字重新補抓來源。"

    @staticmethod
    def parse_plan(raw_text: str) -> TopicDiscoveryPlan:
        json_text = TopicDiscoveryService._extract_json(raw_text)
        try:
            return TopicDiscoveryService.enrich_plan(TopicDiscoveryPlan.model_validate_json(json_text))
        except (ValidationError, ValueError) as exc:
            raise ValueError("invalid topic discovery json") from exc

    @staticmethod
    def enrich_plan(plan: TopicDiscoveryPlan) -> TopicDiscoveryPlan:
        for subtopic in plan.subtopics:
            if not subtopic.source_intents:
                subtopic.source_intents = TopicDiscoveryService.infer_source_intents(subtopic)
        return plan

    @staticmethod
    def infer_source_intents(subtopic: DiscoverySubtopic) -> list[str]:
        text = " ".join(
            [
                subtopic.name,
                subtopic.rationale,
                subtopic.objective,
                *subtopic.required_evidence,
                *subtopic.risk_focus,
                *subtopic.search_queries,
            ]
        ).lower()
        rules = [
            ("financial_metrics", ["營收", "獲利", "毛利", "現金流", "roe", "revenue", "margin", "profit"]),
            ("valuation", ["估值", "股價", "本益比", "pe", "p/e", "pb", "valuation", "price"]),
            ("company_disclosure", ["法說", "年報", "公開說明書", "重大訊息", "訂單", "出貨", "客戶"]),
            ("industry_news", ["產業", "市場", "需求", "供給", "成長", "market", "demand", "supply"]),
            ("capacity_supply", ["產能", "良率", "瓶頸", "交期", "capacity", "yield", "bottleneck"]),
            ("regulatory_policy", ["政策", "法規", "管制", "禁令", "地緣", "regulation", "export control"]),
            ("international_context", ["國際", "全球", "美國", "global", "us ", "worldwide"]),
        ]
        intents = [intent for intent, terms in rules if any(term in text for term in terms)]
        if not intents:
            intents.append("industry_news")
        if "international_context" not in intents and any(
            TopicDiscoveryService._query_language(query) in {"en", "mixed"} for query in subtopic.search_queries
        ):
            intents.append("international_context")
        return list(dict.fromkeys(intents))[:6]

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
- subtopics 最多 6 筆；candidate_companies 最多 20 筆。
- rationale 每欄最多 25 個中文字；search query 每筆最多 30 個中文字。
- 子題應是一個可執行研究任務，不只是關鍵字。
- 每個子題需包含 objective、required_evidence、risk_focus，說明研究目的、需要查核的資料、需監控的風險。
- 每個子題需包含 source_intents，表示應抓取的資料類型，例如 industry_news、company_disclosure、financial_metrics、valuation、capacity_supply、regulatory_policy、international_context。
- 子題應能驅動資料抓取，例如 CoWoS、HBM、AI 伺服器、液冷、地緣政治、缺電等，但不要固定死在這些範例。
- candidate_companies 是「候選研究清單」，不是正式投資推薦。
- 若主題是大型產業鏈，候選清單應保持寬口徑；AI 產業鏈通常至少列出 15 檔可驗證台股候選，再交由後續證據升格。
- 公司必須是台股 4 碼 ticker。
- 不確定 ticker 時不要輸出該公司。
- search_queries 要適合 Google News RSS 搜尋；繁體中文為主，但每個子題至少 1 筆可用英文或中英混合詞查國際資料。
- search_queries 必須對應 objective、required_evidence 或 risk_focus，不可只是公司名或籠統題材詞。
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
      "search_queries": ["string"],
      "source_intents": ["industry_news", "company_disclosure"]
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

    @staticmethod
    def _repair_prompt(topic: str, plan: TopicDiscoveryPlan, quality: DiscoveryPlanQuality) -> str:
        return f"""
你是台股產業研究總監。請修正主題「{topic}」的研究拆解 JSON，讓它成為可執行、可查證、可用於後續投資研究的任務清單。

目前品質狀態：
{json.dumps(quality.model_dump(), ensure_ascii=False)}

目前 JSON：
{json.dumps(plan.model_dump(), ensure_ascii=False)}

修正要求：
- 只能輸出 JSON，不要 Markdown，不要解釋，不要前後文。
- 回覆第一個字元必須是 {{，最後一個字元必須是 }}。
- 保留合理的原子題與候選公司，但必須補齊品質缺口。
- subtopics 最多 8 筆；candidate_companies 最多 20 筆。
- 每個子題都要有 objective、required_evidence、risk_focus、search_queries。
- 每個子題都要有 source_intents，讓系統知道應補哪類來源；可用值包含 industry_news、company_disclosure、financial_metrics、valuation、capacity_supply、regulatory_policy、international_context。
- 子題必須是可執行研究任務，不能只是熱門股、概念股或單一關鍵字。
- search_queries 要能直接用於 Google News RSS，並兼顧台灣與國際資料；每個子題至少保留 1 筆英文或中英混合國際查詢。
- search_queries 必須能說明要驗證哪個投資假設，不可只是公司名、熱門股或籠統題材詞。
- 至少涵蓋品質缺口中提到的研究面向；若主題不適用，需用同一子題合併處理但不能空缺。
- candidate_companies 只是候選研究清單，不是投資推薦；公司必須是台股 4 碼 ticker，不確定 ticker 不要輸出。
- evidence_keywords 必須能用來驗證公司與主題的真實關聯，不能只寫「AI」或「熱門」。

JSON schema:
{{
  "subtopics": [
    {{
      "name": "string",
      "rationale": "string",
      "objective": "string",
      "required_evidence": ["營收", "產能", "訂單"],
      "risk_focus": ["供給瓶頸", "價格下修"],
      "search_queries": ["string"],
      "source_intents": ["industry_news", "company_disclosure"]
    }}
  ],
  "candidate_companies": [
    {{
      "ticker": "2330",
      "name": "台積電",
      "segment": "晶圓代工",
      "rationale": "string",
      "evidence_keywords": ["CoWoS", "先進封裝"]
    }}
  ]
}}
"""
