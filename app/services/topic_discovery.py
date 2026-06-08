from __future__ import annotations

import json
import re
from datetime import date
from typing import Optional
from urllib.parse import quote_plus

from pydantic import ValidationError

from app.core.time import today_taipei
from app.models.schemas import NewsDocument
from app.services import topic_discovery_prompts
from app.services.candidate_confidence import confidence_level, is_high_confidence
from app.services.entity_mapping import alias_matches_text, alias_positions, company_filing_owner_ticker
from app.services.llm_client import LLMClient
from app.services.source_quality import is_formal_evidence_document
from app.services.source_quality import summarize_source_credibility
from app.services.topic_discovery_models import (
    CandidateCompany as CandidateCompany,
    DiscoveryPlanQuality as DiscoveryPlanQuality,
    DiscoverySubtopic as DiscoverySubtopic,
    TopicDiscoveryPlan as TopicDiscoveryPlan,
    ValidatedCandidate as ValidatedCandidate,
)
from app.services.whitelist import SupplyChainWhitelist

STALE_CANDIDATE_EVIDENCE_DAYS = 180


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
            plan = self.enrich_plan(self.parse_plan(result.text), topic=topic)
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
            repaired_plan = self.enrich_plan(self.parse_plan(result.text), topic=topic)
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
        if TopicDiscoveryService._is_robotics_topic(topic):
            return TopicDiscoveryService._robotics_fallback_plan(topic)
        if TopicDiscoveryService._is_memory_topic(topic):
            return TopicDiscoveryService._memory_fallback_plan(topic)
        if "AI" not in topic.upper() and "人工智慧" not in topic:
            return TopicDiscoveryService._generic_exploration_plan(topic)
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
                    name="高速 PCB、載板與上游材料",
                    rationale="訊號與材料升級",
                    objective="確認 AI 伺服器 PCB、載板、CCL、銅箔與玻纖布是否受惠或形成供給瓶頸",
                    required_evidence=["PCB 訂單", "載板需求", "CCL", "銅箔", "玻纖布"],
                    risk_focus=["良率瓶頸", "材料缺貨", "價格下修", "庫存調整"],
                    search_queries=[
                        "AI 伺服器 PCB 載板 CCL 銅箔 玻纖布",
                        "AI server PCB substrate CCL copper foil glass fiber Taiwan",
                    ],
                ),
                DiscoverySubtopic(
                    name="半導體上游材料與特化",
                    rationale="晶圓與化學材料",
                    objective="查核矽晶圓、電子級化學品、特用氣體、光阻與 CMP 材料是否形成成本或供給瓶頸",
                    required_evidence=["矽晶圓", "電子級化學品", "特用氣體", "光阻", "CMP 材料"],
                    risk_focus=["材料漲價", "供應受限", "認證週期", "客戶集中"],
                    search_queries=[
                        "AI 晶片 半導體材料 矽晶圓 電子級化學品 特用氣體",
                        "AI semiconductor materials silicon wafer specialty chemicals photoresist CMP Taiwan",
                    ],
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
                    ticker="2383",
                    name="台光電",
                    segment="高速 CCL / 低損耗材料",
                    rationale="AI 伺服器高速板材",
                    evidence_keywords=["CCL", "低損耗材料", "AI 伺服器"],
                ),
                CandidateCompany(
                    ticker="6213",
                    name="聯茂",
                    segment="高速 CCL",
                    rationale="高速材料需求提升",
                    evidence_keywords=["CCL", "高速材料", "資料中心"],
                ),
                CandidateCompany(
                    ticker="1815",
                    name="富喬",
                    segment="玻纖布",
                    rationale="PCB 上游玻纖材料",
                    evidence_keywords=["玻纖布", "PCB", "AI 伺服器"],
                ),
                CandidateCompany(
                    ticker="8358",
                    name="金居",
                    segment="銅箔",
                    rationale="高階 PCB 上游銅箔",
                    evidence_keywords=["銅箔", "PCB", "AI 伺服器"],
                ),
                CandidateCompany(
                    ticker="6488",
                    name="環球晶",
                    segment="矽晶圓",
                    rationale="半導體上游晶圓材料",
                    evidence_keywords=["矽晶圓", "半導體材料", "AI 晶片"],
                ),
            ],
            )
        )

    @staticmethod
    def _generic_exploration_plan(topic: str) -> TopicDiscoveryPlan:
        anchor_candidates = TopicDiscoveryService._generic_anchor_candidates(topic)
        return TopicDiscoveryService.enrich_plan(
            TopicDiscoveryPlan(
                subtopics=[
                    DiscoverySubtopic(
                        name=f"{topic} 主題定義與範圍收斂",
                        rationale="先確認主題是否有明確主線，避免一開始就展太開",
                        objective="辨識核心產品、直接受惠公司、周邊公司與應排除的噪音標的",
                        required_evidence=["產業定義", "核心產品", "直接受惠", "排除範圍"],
                        risk_focus=["主題誤判", "範圍過寬", "噪音標的混入"],
                        search_queries=[
                            f"{topic} 產業定義 核心產品 直接受惠 公司",
                            f"{topic} industry definition core product direct beneficiaries Taiwan",
                        ],
                        source_intents=["industry_news", "company_disclosure", "international_context"],
                    ),
                    DiscoverySubtopic(
                        name=f"{topic} 需求與成長",
                        rationale="先確認這個主題到底對應哪一段需求鏈",
                        objective="查核需求、訂單、出貨與市場規模是否支持投資假設",
                        required_evidence=["需求", "訂單", "出貨", "市場規模"],
                        risk_focus=["需求下修", "競爭加劇", "市場規模不如預期"],
                        search_queries=[f"{topic} 需求 訂單 出貨 市場規模", f"{topic} 需求 demand 訂單 order 出貨 shipment"],
                        source_intents=["industry_news", "international_context", "early_signal"],
                    ),
                    DiscoverySubtopic(
                        name=f"{topic} 供給與瓶頸",
                        rationale="找出供給端或產能端的約束",
                        objective="查核產能、良率、交期或供應瓶頸是否限制成長",
                        required_evidence=["產能", "良率", "交期", "瓶頸"],
                        risk_focus=["產能不足", "良率問題", "供給過剩"],
                        search_queries=[f"{topic} 產能 良率 交期 瓶頸", f"{topic} 產能 capacity 良率 yield 交期 lead time"],
                        source_intents=["capacity_supply", "industry_news", "international_context"],
                    ),
                    DiscoverySubtopic(
                        name=f"{topic} 財務與估值",
                        rationale="先判斷市場是否已經過度反映",
                        objective="比較月營收、毛利率、本益比與現金流是否匹配成長假設",
                        required_evidence=["月營收", "毛利率", "本益比", "現金流"],
                        risk_focus=["估值過高", "獲利下滑", "現金流惡化"],
                        search_queries=[f"{topic} 月營收 毛利率 本益比 現金流", f"{topic} 月營收 revenue 毛利率 margin 本益比 valuation"],
                        source_intents=["financial_metrics", "valuation", "company_disclosure"],
                    ),
                    DiscoverySubtopic(
                        name=f"{topic} 上游材料與設備",
                        rationale="確認上游原料、材料或設備是否會成為新瓶頸",
                        objective="追蹤材料、零組件、設備與供應商是否能支持主題成長",
                        required_evidence=["材料", "設備", "供應商", "原料"],
                        risk_focus=["材料漲價", "供應受限", "設備交期"],
                        search_queries=[f"{topic} 材料 設備 供應商 原料", f"{topic} 材料 materials 設備 equipment 供應商 supplier"],
                        source_intents=["material_supply", "capacity_supply", "company_disclosure"],
                    ),
                    DiscoverySubtopic(
                        name=f"{topic} 風險與外部變數",
                        rationale="把政策、國際與執行風險先攤開",
                        objective="評估政策、法規、地緣與市場情緒對主題的影響",
                        required_evidence=["政策", "法規", "國際", "風險"],
                        risk_focus=["政策變動", "地緣政治", "外部需求放緩"],
                        search_queries=[f"{topic} 政策 法規 國際 風險", f"{topic} 政策 policy 法規 regulation 國際 global"],
                        source_intents=["regulatory_policy", "international_context", "industry_news"],
                    ),
                    DiscoverySubtopic(
                        name=f"{topic} 候選驗證與收斂",
                        rationale="先用候選驗證把主題落到公司層級",
                        objective="找出能被新聞、公司文件與財務資料共同驗證的候選公司",
                        required_evidence=["公司文件", "新聞", "月營收", "財務資料"],
                        risk_focus=["錯誤歸因", "過度題材化", "證據不足"],
                        search_queries=[f"{topic} 公司文件 月營收 財務 資料", f"{topic} 公司文件 company disclosure 月營收 revenue 財務 financial"],
                        source_intents=["company_disclosure", "financial_metrics", "industry_news"],
                    ),
                ],
                candidate_companies=anchor_candidates,
            )
        )

    @staticmethod
    def _generic_anchor_candidates(topic: str) -> list[CandidateCompany]:
        whitelist = SupplyChainWhitelist()
        segment_lookup: dict[str, str] = {}
        for segment in whitelist.segments:
            for company in segment.companies:
                segment_lookup[company.ticker] = segment.name
        all_companies = whitelist.companies()
        topic_text = topic.lower()
        scored: list[tuple[int, CandidateCompany]] = []
        for company in all_companies:
            segment_name = segment_lookup.get(company.ticker, "探索錨點")
            haystack = " ".join(
                [
                    company.ticker,
                    company.name,
                    segment_name,
                    " ".join(getattr(company, "aliases", []) or []),
                    " ".join(getattr(company, "evidence_keywords", []) or []),
                    topic_text,
                ]
            ).lower()
            score = 0
            for keyword in [topic_text, *re.findall(r"[\u4e00-\u9fff]{2,}|[a-z]{3,}", topic_text)]:
                if keyword and keyword in haystack:
                    score += 2
            score += len(getattr(company, "evidence_keywords", []) or [])
            scored.append(
                (
                    score,
                    CandidateCompany(
                        ticker=company.ticker,
                        name=company.name,
                        segment=segment_name,
                        rationale=f"以 {segment_name} 作為未知主題的探索錨點",
                        evidence_keywords=list(getattr(company, "evidence_keywords", []) or [])[:6]
                        or [company.name, company.ticker],
                    ),
                )
            )
        ranked = [candidate for _, candidate in sorted(scored, key=lambda item: (-item[0], item[1].ticker))]
        if ranked:
            return ranked[: max(6, min(12, len(ranked)))]
        return []

    @staticmethod
    def _memory_fallback_plan(topic: str) -> TopicDiscoveryPlan:
        return TopicDiscoveryService.enrich_plan(
            TopicDiscoveryPlan(
                subtopics=[
                    DiscoverySubtopic(
                        name="需求與庫存循環",
                        rationale="記憶體景氣高度受供需循環影響",
                        objective="確認 DRAM / NAND 價格、客戶庫存與出貨是否進入補庫存或下行修正循環",
                        required_evidence=["價格", "庫存", "出貨", "合約價"],
                        risk_focus=["報價下跌", "庫存調整", "需求轉弱"],
                        search_queries=[
                            f"{topic} DRAM NAND 價格 庫存 出貨",
                            "DRAM NAND price inventory shipment contract price Taiwan memory",
                        ],
                    ),
                    DiscoverySubtopic(
                        name="製程與產能",
                        rationale="製程世代與產能利用率決定成本與供給",
                        objective="查核先進製程、產能利用率、投片與良率是否影響記憶體供給",
                        required_evidence=["製程", "產能利用率", "投片", "良率"],
                        risk_focus=["產能擴張", "良率問題", "投資延遲"],
                        search_queries=[
                            f"{topic} 製程 產能利用率 良率 投片",
                            f"{topic} memory 製程 產能利用率 良率 投片",
                        ],
                    ),
                    DiscoverySubtopic(
                        name="下游模組與應用",
                        rationale="模組與系統應用決定終端拉貨力道",
                        objective="確認模組廠、PC / server / mobile / AI 應用需求是否拉動記憶體採購",
                        required_evidence=["模組", "拉貨", "訂單", "終端需求"],
                        risk_focus=["終端需求放緩", "通路去庫存", "訂單遞延"],
                        search_queries=[
                            f"{topic} 模組 拉貨 訂單 終端需求",
                            "memory module demand server pc mobile AI ordering",
                        ],
                    ),
                    DiscoverySubtopic(
                        name="財務與估值",
                        rationale="記憶體股常受循環與估值雙重驅動",
                        objective="比較月營收、毛利率、本益比與現金流，避免只因價格循環追高",
                        required_evidence=["月營收", "毛利率", "本益比", "現金流"],
                        risk_focus=["估值過高", "獲利回落", "資本支出壓力"],
                        search_queries=[
                            f"{topic} 月營收 毛利率 本益比 現金流",
                            f"{topic} memory 月營收 毛利率 本益比 現金流",
                        ],
                    ),
                    DiscoverySubtopic(
                        name="上游材料與設備",
                        rationale="材料與設備決定供給擴張速度與成本",
                        objective="追蹤矽晶圓、特用氣體、光阻、設備與封裝材料是否形成瓶頸或擴產契機",
                        required_evidence=["矽晶圓", "特用氣體", "光阻", "設備"],
                        risk_focus=["材料漲價", "設備交期", "擴產延遲"],
                        search_queries=[
                            f"{topic} 矽晶圓 特用氣體 光阻 設備",
                            f"{topic} memory 矽晶圓 特用氣體 光阻 設備",
                        ],
                    ),
                    DiscoverySubtopic(
                        name="風險與國際競爭",
                        rationale="記憶體價格與供應受國際大廠與地緣影響很大",
                        objective="評估韓國、美國與中國供應擴張、出口管制與地緣政治對台廠的影響",
                        required_evidence=["國際競爭", "出口管制", "供應擴張", "風險"],
                        risk_focus=["價格戰", "出口管制", "需求轉弱"],
                        search_queries=[
                            f"{topic} 國際競爭 出口管制 供應擴張",
                            f"{topic} memory 國際競爭 出口管制 供應擴張",
                        ],
                    ),
                ],
                candidate_companies=[
                    CandidateCompany(
                        ticker="2408",
                        name="南亞科",
                        segment="DRAM 記憶體",
                        rationale="DRAM 原廠，直接反映記憶體循環",
                        evidence_keywords=["DRAM", "記憶體", "月營收"],
                    ),
                    CandidateCompany(
                        ticker="2344",
                        name="華邦電",
                        segment="DRAM / NOR Flash",
                        rationale="記憶體產品組合完整，兼具循環與產品組合變化",
                        evidence_keywords=["DRAM", "NOR Flash", "記憶體"],
                    ),
                    CandidateCompany(
                        ticker="8299",
                        name="群聯",
                        segment="NAND 控制晶片 / SSD",
                        rationale="NAND 與儲存應用需求可驗證終端拉貨與控制晶片景氣",
                        evidence_keywords=["NAND", "SSD", "控制晶片"],
                    ),
                    CandidateCompany(
                        ticker="2451",
                        name="創見",
                        segment="記憶體模組 / 儲存",
                        rationale="模組與儲存應用可觀察終端需求與庫存循環",
                        evidence_keywords=["記憶體模組", "SSD", "儲存"],
                    ),
                    CandidateCompany(
                        ticker="3260",
                        name="威剛",
                        segment="記憶體模組 / 通路",
                        rationale="模組通路可驗證拉貨與庫存回補",
                        evidence_keywords=["記憶體模組", "拉貨", "庫存"],
                    ),
                    CandidateCompany(
                        ticker="4967",
                        name="十銓",
                        segment="記憶體模組",
                        rationale="模組需求與價格循環的中小型觀察點",
                        evidence_keywords=["記憶體模組", "價格", "終端需求"],
                    ),
                    CandidateCompany(
                        ticker="2337",
                        name="旺宏",
                        segment="NOR Flash / 記憶體",
                        rationale="NOR Flash 與記憶體循環的核心觀察點",
                        evidence_keywords=["NOR Flash", "記憶體", "月營收"],
                    ),
                    CandidateCompany(
                        ticker="8150",
                        name="南茂",
                        segment="記憶體封裝 / 測試",
                        rationale="記憶體封裝測試與供應鏈景氣觀察點",
                        evidence_keywords=["記憶體", "封裝", "測試"],
                    ),
                ],
            )
        )

    @staticmethod
    def _is_robotics_topic(topic: str) -> bool:
        normalized = topic.lower()
        return any(term in normalized for term in ["機器人", "robot", "robotics", "humanoid", "協作機器人"])

    @staticmethod
    def _is_memory_topic(topic: str) -> bool:
        normalized = topic.lower()
        return any(term in normalized for term in ["記憶體", "memory", "dram", "nand", "flash", "ssd"])

    @staticmethod
    def _is_memory_plan(plan: TopicDiscoveryPlan) -> bool:
        text = TopicDiscoveryService._plan_search_text(plan)
        return any(term in text for term in ["記憶體", "memory", "dram", "nand", "flash", "ssd"])

    @staticmethod
    def _robotics_fallback_plan(topic: str) -> TopicDiscoveryPlan:
        return TopicDiscoveryService.enrich_plan(
            TopicDiscoveryPlan(
                subtopics=[
                    DiscoverySubtopic(
                        name="協作與人形機器人需求",
                        rationale="確認機器人導入是否從題材進入實際採購",
                        objective="追蹤協作機器人、人形機器人與工廠自動化的出貨、訂單與導入進度",
                        required_evidence=["協作機器人出貨", "人形機器人導入", "訂單", "營收"],
                        risk_focus=["商業化延遲", "客戶導入放緩", "需求下修"],
                        search_queries=[
                            "協作機器人 出貨 訂單 營收 台廠",
                            "協作機器人出貨 humanoid robot commercialization orders revenue Taiwan suppliers",
                        ],
                    ),
                    DiscoverySubtopic(
                        name="伺服馬達與控制系統",
                        rationale="控制與驅動是機器人核心零組件",
                        objective="查核伺服馬達、控制器、工業電腦與邊緣運算供應商是否有機器人訂單與毛利改善",
                        required_evidence=["伺服馬達", "控制器", "工業電腦", "毛利率"],
                        risk_focus=["價格競爭", "中國供應商競爭", "毛利下滑"],
                        search_queries=[
                            "伺服馬達 控制器 機器人 訂單 毛利率 台股",
                            "伺服馬達 servo motor robot controller Taiwan supplier margin",
                        ],
                    ),
                    DiscoverySubtopic(
                        name="減速器與線性傳動",
                        rationale="精密傳動影響機器人關節成本與供給",
                        objective="追蹤諧波減速器、滾珠螺桿、線性滑軌與微型滑軌的產能、技術瓶頸與供應鏈地位",
                        required_evidence=["諧波減速器", "滾珠螺桿", "線性滑軌", "產能"],
                        risk_focus=["良率瓶頸", "技術門檻不足", "產能過剩"],
                        search_queries=[
                            "諧波減速器 滾珠螺桿 線性滑軌 機器人 產能",
                            "諧波減速器 harmonic reducer ball screw linear guide robot capacity Taiwan",
                        ],
                    ),
                    DiscoverySubtopic(
                        name="視覺感測與機構件",
                        rationale="機器人需要感測、鏡頭與輕量化機構件",
                        objective="確認 3D 視覺、光學鏡頭、鎂鋁機構件與轉軸是否有機器人供應鏈實績",
                        required_evidence=["3D 視覺", "光學鏡頭", "機構件", "轉軸"],
                        risk_focus=["認證延遲", "單一客戶", "規格變更"],
                        search_queries=[
                            "3D 視覺 光學鏡頭 機器人 機構件 台股",
                            "機器視覺 robot vision sensor hinge lightweight component Taiwan supplier",
                        ],
                    ),
                    DiscoverySubtopic(
                        name="上游材料與關鍵原料",
                        rationale="材料決定成本良率",
                        objective="查核磁材、電磁鋼、軸承鋼/特殊鋼、工程塑膠、碳纖與鎂鋁合金是否限制機器人成本、重量與供給",
                        required_evidence=["稀土磁材", "電磁鋼", "特殊鋼", "工程塑膠", "碳纖", "鎂鋁合金"],
                        risk_focus=["原料漲價", "供應集中", "認證週期", "替代材料競爭"],
                        search_queries=[
                            "機器人 上游材料 稀土磁材 電磁鋼 特殊鋼 工程塑膠",
                            "robotics upstream materials 稀土磁材 electrical steel 工程塑膠 carbon fiber Taiwan",
                        ],
                    ),
                    DiscoverySubtopic(
                        name="財務與估值檢查",
                        rationale="避免只因機器人題材追高",
                        objective="比較候選公司的月營收、毛利率、本益比、資本支出與機器人業務佔比",
                        required_evidence=["月營收", "毛利率", "本益比", "資本支出", "業務佔比"],
                        risk_focus=["估值過高", "營收未反映", "題材占比過低"],
                        search_queries=[
                            "機器人 台股 月營收 毛利率 本益比 估值",
                            "機器人 月營收 毛利率 本益比 robotics Taiwan stocks valuation capex",
                        ],
                    ),
                    DiscoverySubtopic(
                        name="政策與國際競爭",
                        rationale="機器人供應鏈受中國、日本與歐美競爭影響",
                        objective="評估政策補助、出口管制、國際競爭與客戶移轉對台廠機器人供應鏈的影響",
                        required_evidence=["政策補助", "出口管制", "國際競爭", "客戶移轉"],
                        risk_focus=["政策退場", "地緣政治", "國際大廠競爭"],
                        search_queries=[
                            "機器人 政策補助 出口管制 國際競爭 台灣",
                            "機器人 政策補助 出口管制 國際競爭 robotics subsidy Taiwan",
                        ],
                    ),
                ],
                candidate_companies=[
                    CandidateCompany(ticker="2308", name="台達電", segment="伺服驅動與控制系統", rationale="工業自動化、伺服驅動與電源管理完整", evidence_keywords=["伺服馬達", "控制器", "智慧製造"]),
                    CandidateCompany(ticker="2359", name="所羅門", segment="AI 3D 視覺軟體", rationale="AI 視覺與機器人辨識題材", evidence_keywords=["AI 視覺", "3D 視覺", "機器人"]),
                    CandidateCompany(ticker="2049", name="上銀", segment="滾珠螺桿與線性滑軌", rationale="精密傳動元件與自動化需求相關", evidence_keywords=["滾珠螺桿", "線性滑軌", "機器人"]),
                    CandidateCompany(ticker="1590", name="亞德客-KY", segment="氣動與線性傳動", rationale="自動化氣動元件受惠工廠自動化", evidence_keywords=["氣動元件", "自動化", "線性傳動"]),
                    CandidateCompany(ticker="2395", name="研華", segment="工業電腦與邊緣運算", rationale="工業電腦、邊緣 AI 與機器人控制應用", evidence_keywords=["工業電腦", "邊緣運算", "機器人"]),
                    CandidateCompany(ticker="6235", name="華孚", segment="鎂鋁合金機構件", rationale="輕量化金屬機構件可用於機器人與電動載具", evidence_keywords=["鎂鋁合金", "機構件", "輕量化"]),
                    CandidateCompany(ticker="4583", name="大銀微系統", segment="直驅馬達與定位平台", rationale="精密定位平台與直驅元件具機器人關聯", evidence_keywords=["直驅馬達", "定位平台", "精密傳動"]),
                    CandidateCompany(ticker="1597", name="直得", segment="微型線性滑軌", rationale="微型線性滑軌可切入精密自動化與機器人", evidence_keywords=["微型線性滑軌", "機器人", "自動化"]),
                    CandidateCompany(ticker="3059", name="華晶科", segment="3D 感測相機", rationale="影像與 3D 感測可支援機器視覺", evidence_keywords=["3D 感測", "機器視覺", "鏡頭"]),
                    CandidateCompany(ticker="4540", name="盟立", segment="自動化系統整合", rationale="自動化設備與系統整合具機器人導入題材", evidence_keywords=["自動化", "系統整合", "機器人"]),
                    CandidateCompany(ticker="6188", name="廣明", segment="協作型機器人", rationale="協作型機器人與自動化設備題材", evidence_keywords=["協作機器人", "自動化", "機器人"]),
                    CandidateCompany(ticker="2301", name="光寶科", segment="電源管理系統", rationale="電源與感測模組可用於機器人平台", evidence_keywords=["電源", "感測", "機器人"]),
                    CandidateCompany(ticker="1504", name="東元", segment="伺服馬達與 AGV", rationale="馬達、電控與 AGV 自動化應用", evidence_keywords=["伺服馬達", "AGV", "自動化"]),
                    CandidateCompany(ticker="3019", name="亞光", segment="光學鏡頭", rationale="光學鏡頭與感測可支援機器視覺", evidence_keywords=["光學鏡頭", "機器視覺", "感測"]),
                    CandidateCompany(ticker="3548", name="兆利", segment="精密轉軸與關節機構", rationale="轉軸與精密機構件可對應機器人關節", evidence_keywords=["轉軸", "關節", "機構件"]),
                    CandidateCompany(ticker="5443", name="均豪", segment="半導體自動化與機械手臂整合", rationale="自動化設備與機械手臂整合經驗", evidence_keywords=["自動化", "機械手臂", "半導體設備"]),
                    CandidateCompany(ticker="8374", name="羅昇", segment="自動化驅動與視覺代理", rationale="代理自動化零組件與視覺控制產品", evidence_keywords=["自動化", "驅動", "機器視覺"]),
                    CandidateCompany(ticker="2002", name="中鋼", segment="電磁鋼 / 特殊鋼材", rationale="馬達與結構材料上游", evidence_keywords=["電磁鋼", "特殊鋼", "機器人"]),
                    CandidateCompany(ticker="5009", name="榮剛", segment="特殊合金鋼", rationale="齒輪與關節用鋼材", evidence_keywords=["特殊鋼", "合金鋼", "精密機械"]),
                    CandidateCompany(ticker="1303", name="南亞", segment="工程塑膠 / 電子材料", rationale="輕量化與絕緣材料", evidence_keywords=["工程塑膠", "電子材料", "複合材料"]),
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
        if TopicDiscoveryService._requires_upstream_material_coverage(plan) and not TopicDiscoveryService._is_generic_exploration_plan(plan):
            coverage["上游材料"] = TopicDiscoveryService._has_upstream_material_coverage(plan)
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
        if TopicDiscoveryService._is_generic_exploration_plan(plan):
            return False
        if TopicDiscoveryService._is_memory_plan(plan):
            return False
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
        has_robotics_theme = any(
            term in text for term in ["機器人", "robot", "robotics", "humanoid", "自動化", "servo", "馬達"]
        )
        return has_ai_theme or has_robotics_theme

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
            theme: any(TopicDiscoveryService._keyword_in_text(joined, keyword) for keyword in keywords)
            for theme, keywords in themes.items()
        }

    @staticmethod
    def _keyword_in_text(text: str, keyword: str) -> bool:
        normalized = keyword.lower()
        if normalized in {"pe", "pb"}:
            return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", text))
        return normalized in text

    @staticmethod
    def _requires_upstream_material_coverage(plan: TopicDiscoveryPlan, topic: str | None = None) -> bool:
        if TopicDiscoveryService._is_generic_exploration_plan(plan):
            return False
        text = " ".join([topic or "", TopicDiscoveryService._plan_search_text(plan)]).lower()
        trigger_terms = [
            "ai 伺服器",
            "ai伺服器",
            "資料中心",
            "cowos",
            "hbm",
            "pcb",
            "載板",
            "機器人",
            "robot",
            "robotics",
            "自動化",
            "伺服",
            "馬達",
            "減速器",
        ]
        if not any(term in text for term in trigger_terms):
            return False
        material_terms = [
            "矽晶圓",
            "電子級化學品",
            "特用氣體",
            "光阻",
            "cmp",
            "ccl",
            "銅箔",
            "玻纖",
            "abf",
            "樹脂",
            "稀土",
            "磁材",
            "電磁鋼",
            "特殊鋼",
            "工程塑膠",
            "碳纖",
            "複合材料",
            "鎂鋁合金",
        ]
        return any(term in text for term in material_terms) or any(term in text for term in trigger_terms)

    @staticmethod
    def _is_generic_exploration_plan(plan: TopicDiscoveryPlan) -> bool:
        if len(plan.subtopics) < 6:
            return False
        names = {subtopic.name for subtopic in plan.subtopics}
        expected_suffixes = {
            "主題定義與範圍收斂",
            "需求與成長",
            "供給與瓶頸",
            "財務與估值",
            "上游材料與設備",
            "風險與外部變數",
            "候選驗證與收斂",
        }
        matched = sum(1 for name in names if any(name.endswith(suffix) for suffix in expected_suffixes))
        return matched >= 6

    @staticmethod
    def _has_upstream_material_coverage(plan: TopicDiscoveryPlan) -> bool:
        text = TopicDiscoveryService._plan_search_text(plan)
        ai_material_groups = [
            ["矽晶圓", "晶圓材料", "電子級", "特用氣體", "化學品", "光阻", "cmp", "silicon wafer", "photoresist"],
            ["ccl", "銅箔", "玻纖", "玻纖布", "abf", "樹脂", "低損耗材料", "copper foil", "glass fiber"],
        ]
        robotics_material_groups = [
            ["磁材", "稀土", "rare earth", "magnet"],
            ["特殊鋼", "軸承鋼", "電磁鋼", "鋼材", "合金鋼", "steel"],
            ["工程塑膠", "碳纖", "複合材料", "engineering plastics", "carbon fiber", "composite"],
            ["鎂鋁", "鋁鎂", "輕量化金屬", "magnesium", "aluminum"],
        ]
        groups = ai_material_groups if not TopicDiscoveryService._is_robotics_plan(plan) else robotics_material_groups
        covered_groups = sum(1 for group in groups if any(term in text for term in group))
        return covered_groups >= 2

    @staticmethod
    def _plan_search_text(plan: TopicDiscoveryPlan) -> str:
        parts = []
        for subtopic in plan.subtopics:
            parts.extend(
                [
                    subtopic.name,
                    subtopic.rationale,
                    subtopic.objective,
                    *subtopic.required_evidence,
                    *subtopic.risk_focus,
                    *subtopic.search_queries,
                    *subtopic.source_intents,
                ]
            )
        for candidate in plan.candidate_companies:
            parts.extend([candidate.name, candidate.segment, candidate.rationale, *candidate.evidence_keywords])
        return " ".join(part for part in parts if part).lower()

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
        if any(term.lower() in query_text for term in terms):
            return True
        query_tokens = set(TopicDiscoveryService._meaningful_tokens(query_text))
        term_tokens = set()
        for term in terms:
            term_tokens.update(TopicDiscoveryService._meaningful_tokens(term))
        return bool(query_tokens & term_tokens)

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
        subtopic_primary_queries: list[dict] = []
        subtopic_extra_queries: list[dict] = []
        for subtopic in plan.subtopics:
            task_terms = " ".join(
                [subtopic.name, *subtopic.required_evidence[:2], *subtopic.risk_focus[:2]]
                if subtopic.required_evidence or subtopic.risk_focus
                else []
            )
            if task_terms.strip():
                subtopic_primary_queries.append(
                    self._query_item(
                        task_terms.strip(),
                        "research_task",
                        self._subtopic_hypothesis(subtopic),
                        self._evidence_type(subtopic.required_evidence, subtopic.risk_focus),
                        self._primary_source_intent(subtopic),
                    )
                )
            for query_index, query in enumerate(subtopic.search_queries):
                item = self._query_item(
                    query,
                    "subtopic",
                    self._subtopic_hypothesis(subtopic),
                    self._evidence_type(subtopic.required_evidence, subtopic.risk_focus),
                    self._primary_source_intent(subtopic),
                )
                if query_index == 0:
                    subtopic_primary_queries.append(item)
                else:
                    subtopic_extra_queries.append(item)
                if include_international:
                    international_item = (
                        self._query_item(
                            f"{query} global market",
                            "subtopic_international",
                            self._subtopic_hypothesis(subtopic),
                            self._evidence_type(subtopic.required_evidence, subtopic.risk_focus),
                            "international_context",
                        )
                    )
                    if query_index == 0:
                        subtopic_primary_queries.append(international_item)
                    else:
                        subtopic_extra_queries.append(international_item)
        queries.extend(subtopic_primary_queries)
        queries.extend(self._round_robin_query_groups(
            [
                self._candidate_query_items(candidate, include_international=include_international)
                for candidate in plan.candidate_companies
            ]
        ))
        queries.extend(subtopic_extra_queries)
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
            "上游材料": ["上游材料 原料 供給 瓶頸", "材料端 成本 認證 供應鏈"],
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
        query_items: list[dict] = []
        query_items.extend(
            self._round_robin_query_groups(
                [
                    self._supplemental_candidate_query_items(
                        candidate,
                        include_international=include_international,
                    )
                    for candidate in weak_candidates
                ]
            )
        )
        target_names = set(missing_subtopics or [])
        target_subtopics = [
            subtopic
            for subtopic in plan.subtopics
            if not target_names or (subtopic.name or "未命名子題") in target_names
        ]
        queries: list[str] = []
        for subtopic in target_subtopics:
            evidence_terms = " ".join(subtopic.required_evidence[:2])
            risk_terms = " ".join(subtopic.risk_focus[:2])
            queries.append(f"{subtopic.name} {subtopic.rationale} {evidence_terms} 台股".strip())
            if risk_terms:
                queries.append(f"{subtopic.name} {risk_terms} 風險 瓶頸".strip())
            for query in subtopic.search_queries[:2]:
                queries.append(f"{query} 最新")

        query_items.extend(
            self._google_news_metadata_from_queries(
                queries,
                source_type="supplemental",
                hypothesis="補強弱證據候選與低覆蓋子題，重新驗證是否可進入正式分析。",
                evidence_type="補抓資料源",
                source_intent="company_disclosure",
                max_urls=None,
                existing_urls=[],
            )
        )
        return self._dedupe_query_metadata(
            query_items,
            max_urls=max_urls,
            existing_urls=existing_urls or [],
        )

    @staticmethod
    def _candidate_query_items(candidate: CandidateCompany, include_international: bool = True) -> list[dict]:
        keywords = " ".join(candidate.evidence_keywords[:3])
        candidate_hypothesis = f"驗證 {candidate.ticker} {candidate.name} 是否與「{candidate.segment}」及主題證據直接相關。"
        items = [
            TopicDiscoveryService._query_item(
                f"{candidate.ticker} {candidate.name} {candidate.segment} {keywords}".strip(),
                "candidate",
                candidate_hypothesis,
                "候選公司證據",
                "industry_news",
            ),
            TopicDiscoveryService._query_item(
                f"{candidate.ticker} {candidate.name} 法說會 年報 月營收".strip(),
                "candidate",
                candidate_hypothesis,
                "公司公開資訊",
                "company_disclosure",
            ),
            TopicDiscoveryService._query_item(
                f"{candidate.name} {candidate.segment} 訂單 營收 出貨".strip(),
                "candidate",
                candidate_hypothesis,
                "財務/營收",
                "financial_metrics",
            ),
            TopicDiscoveryService._query_item(
                f"{candidate.ticker} {candidate.name} 公開資訊觀測站 法人說明會".strip(),
                "candidate",
                candidate_hypothesis,
                "公司公開資訊",
                "company_disclosure",
            ),
        ]
        if include_international:
            items.extend(
                [
                    TopicDiscoveryService._query_item(
                        f"{candidate.name} {candidate.ticker} Taiwan supplier {keywords}".strip(),
                        "candidate_international",
                        candidate_hypothesis,
                        "國際供應鏈證據",
                        "international_context",
                    ),
                    TopicDiscoveryService._query_item(
                        f"{candidate.segment} {keywords} global supply chain Taiwan listed company".strip(),
                        "candidate_international",
                        candidate_hypothesis,
                        "國際供應鏈證據",
                        "international_context",
                    ),
                ]
            )
        return TopicDiscoveryService._dedupe_query_items(items)

    @staticmethod
    def _supplemental_candidate_query_items(
        candidate: CandidateCompany,
        include_international: bool = True,
    ) -> list[dict]:
        return [
            {
                **item,
                "source_type": "supplemental",
                "hypothesis": "補強弱證據候選與低覆蓋子題，重新驗證是否可進入正式分析。",
                "evidence_type": "補抓資料源",
            }
            for item in TopicDiscoveryService._candidate_query_items(
                candidate,
                include_international=include_international,
            )
        ]

    @staticmethod
    def _round_robin_query_groups(groups: list[list[dict]]) -> list[dict]:
        items: list[dict] = []
        max_depth = max((len(group) for group in groups), default=0)
        for index in range(max_depth):
            for group in groups:
                if index < len(group):
                    items.append(group[index])
        return TopicDiscoveryService._dedupe_query_items(items)

    @staticmethod
    def _dedupe_query_items(items: list[dict]) -> list[dict]:
        deduped = []
        seen = set()
        for item in items:
            normalized = re.sub(r"\s+", " ", str(item.get("query") or "")).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append({**item, "query": normalized})
        return deduped

    @staticmethod
    def _dedupe_query_metadata(
        items: list[dict],
        max_urls: int | None = None,
        existing_urls: list[str] | None = None,
    ) -> list[dict]:
        seen_urls = set(existing_urls or [])
        seen_queries = set()
        metadata = []
        for item in items:
            normalized = re.sub(r"\s+", " ", str(item.get("query") or "")).strip()
            url = item.get("url") or (
                "https://news.google.com/rss/search?"
                f"q={quote_plus(normalized)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
            )
            if not normalized or normalized in seen_queries or url in seen_urls:
                continue
            seen_queries.add(normalized)
            seen_urls.add(url)
            metadata.append(
                {
                    **item,
                    "url": url,
                    "query": normalized,
                    "language": TopicDiscoveryService._query_language(normalized),
                }
            )
            if max_urls and len(metadata) >= max_urls:
                break
        return metadata

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
            "AI server upstream materials CCL copper foil glass fiber Taiwan",
            "semiconductor materials silicon wafer specialty chemicals AI chip Taiwan",
            "AI data center liquid cooling supply chain",
            "AI data center power grid constraint semiconductor",
            "US export controls AI chips Taiwan supply chain",
            "robotics upstream materials rare earth magnet special steel engineering plastics",
            "North American cloud AI server capex TrendForce",
        ]

    def validate_candidates(
        self,
        plan: TopicDiscoveryPlan,
        documents: list[NewsDocument],
    ) -> list[ValidatedCandidate]:
        validated: list[ValidatedCandidate] = []
        relax_context_for_entity_match = self._is_memory_plan(plan)
        for candidate in plan.candidate_companies:
            evidence_documents = []
            entity_terms = self._candidate_entity_terms(candidate)
            context_terms = self._candidate_context_terms(candidate, plan)
            for document in documents:
                if not is_formal_evidence_document(document):
                    continue
                if self._document_supports_candidate(
                    document,
                    entity_terms,
                    context_terms,
                    relax_context_for_entity_match=relax_context_for_entity_match,
                ):
                    evidence_documents.append(document)
            deduped_titles = list(dict.fromkeys(document.title for document in evidence_documents))[:5]
            source_count = self._evidence_source_count(evidence_documents)
            evidence_sources = self._candidate_evidence_sources(evidence_documents)
            confidence = self._candidate_evidence_confidence(evidence_documents, source_count)
            status = self._candidate_status(
                len(evidence_documents),
                source_count,
                confidence["score"],
                confidence["evidence_stale"],
            )
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
                    source_credibility_score=confidence["source_credibility_score"],
                    source_credibility_label=confidence["source_credibility_label"],
                    source_credibility_counts=confidence["source_credibility_counts"],
                    latest_evidence_date=confidence["latest_evidence_date"],
                    evidence_age_days=confidence["evidence_age_days"],
                    evidence_stale=confidence["evidence_stale"],
                    status=status,
                    validation_reason=self._candidate_validation_reason(
                        len(evidence_documents),
                        source_count,
                        confidence["score"],
                        confidence["latest_evidence_date"],
                        confidence["evidence_age_days"],
                        confidence["evidence_stale"],
                    ),
                    next_action=self._candidate_next_action(
                        len(evidence_documents),
                        source_count,
                        confidence["score"],
                        confidence["evidence_stale"],
                    ),
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
        if TopicDiscoveryService._plan_or_candidate_mentions_robotics(candidate, plan):
            terms.extend(
                [
                    "機器人",
                    "自動化",
                    "協作機器人",
                    "人形機器人",
                    "工業機器人",
                    "機器視覺",
                    "3D 視覺",
                    "感測",
                    "伺服",
                    "伺服馬達",
                    "控制器",
                    "減速器",
                    "滾珠螺桿",
                    "線性滑軌",
                    "精密傳動",
                    "AGV",
                    "robot",
                    "robotics",
                    "automation",
                    "servo",
                    "machine vision",
                    "motion control",
                    "磁材",
                    "稀土",
                    "電磁鋼",
                    "特殊鋼",
                    "工程塑膠",
                    "碳纖",
                    "鎂鋁合金",
                    "rare earth",
                    "magnet",
                    "special steel",
                    "engineering plastics",
                    "carbon fiber",
                ]
            )
        return list(dict.fromkeys(term.strip() for term in terms if term and term.strip()))

    @staticmethod
    def _is_robotics_plan(plan: TopicDiscoveryPlan, topic: str | None = None) -> bool:
        text = " ".join([topic or "", TopicDiscoveryService._plan_search_text(plan)]).lower()
        return "機器人" in text or any(
            term in text
            for term in ["robot", "robotics", "humanoid", "servo", "automation", "agv"]
        )

    @staticmethod
    def _plan_or_candidate_mentions_robotics(candidate: CandidateCompany, plan: TopicDiscoveryPlan | None = None) -> bool:
        parts = [
            candidate.segment,
            candidate.rationale,
            *candidate.evidence_keywords,
        ]
        if plan:
            for subtopic in plan.subtopics:
                parts.extend(
                    [
                        subtopic.name,
                        subtopic.rationale,
                        subtopic.objective,
                        *subtopic.required_evidence,
                        *subtopic.risk_focus,
                    ]
                )
        text = " ".join(part for part in parts if part).lower()
        return any(term in text for term in ["機器人", "robot", "robotics", "automation", "自動化", "agv"])

    @staticmethod
    def _context_phrases(text: str) -> list[str]:
        if not text:
            return []
        normalized = re.sub(r"[，,。；;：:（）()、/|與及和]+", " ", text)
        parts = [part.strip() for part in normalized.split() if len(part.strip()) >= 2]
        phrases = [text.strip()]
        phrases.extend(parts)
        return phrases

    @staticmethod
    def _has_entity_and_context(haystack: str, entity_terms: list[str], context_terms: list[str]) -> bool:
        normalized = haystack.lower()
        has_entity = any(TopicDiscoveryService._contains_entity_term(normalized, term) for term in entity_terms)
        if not has_entity:
            return False
        if not context_terms:
            return True
        return any(term and term.lower() in normalized for term in context_terms)

    @staticmethod
    def _has_entity_and_context_nearby(
        haystack: str,
        entity_terms: list[str],
        context_terms: list[str],
        window: int = 900,
    ) -> bool:
        normalized = haystack.lower()
        entity_positions = TopicDiscoveryService._term_positions(normalized, entity_terms)
        if not entity_positions:
            return False
        if not context_terms:
            return True
        context_positions = TopicDiscoveryService._term_positions(normalized, context_terms)
        if not context_positions:
            return False
        if len(normalized) <= 1500:
            return True
        return any(abs(entity - context) <= window for entity in entity_positions for context in context_positions)

    @staticmethod
    def _document_supports_candidate(
        document: NewsDocument,
        entity_terms: list[str],
        context_terms: list[str],
        relax_context_for_entity_match: bool = False,
    ) -> bool:
        haystack = f"{document.title}\n{document.text}"
        metadata_match = TopicDiscoveryService._document_entity_metadata_match(document, entity_terms)
        if metadata_match is False:
            return False
        owner_ticker = company_filing_owner_ticker(document)
        if owner_ticker:
            ticker_terms = {term for term in entity_terms if term.isdigit()}
            if ticker_terms and owner_ticker not in ticker_terms:
                return False
        if metadata_match is True:
            normalized = haystack.lower()
            if context_terms and not TopicDiscoveryService._has_context_term(normalized, context_terms):
                if not relax_context_for_entity_match:
                    return False
        else:
            if not TopicDiscoveryService._has_entity_and_context_nearby(haystack, entity_terms, context_terms):
                return False
        if not TopicDiscoveryService._looks_like_unrelated_release_document(document):
            return True
        named_terms = [term for term in entity_terms if term and not term.isdigit()]
        normalized = haystack.lower()
        return any(TopicDiscoveryService._contains_entity_term(normalized, term) for term in named_terms)

    @staticmethod
    def _document_entity_metadata_match(document: NewsDocument, entity_terms: list[str]) -> bool | None:
        entity_tickers = {str(ticker) for ticker in document.entity_tickers if str(ticker)}
        ticker_terms = {str(term) for term in entity_terms if str(term).isdigit()}
        if not entity_tickers or not ticker_terms:
            return None
        return bool(entity_tickers & ticker_terms)

    @staticmethod
    def _has_context_term(normalized_haystack: str, context_terms: list[str]) -> bool:
        return any(term and term.lower() in normalized_haystack for term in context_terms)

    @staticmethod
    def _term_positions(haystack: str, terms: list[str]) -> list[int]:
        positions: list[int] = []
        for term in terms:
            normalized_term = (term or "").lower()
            if not normalized_term:
                continue
            positions.extend(alias_positions(haystack, normalized_term))
        return positions

    @staticmethod
    def _contains_entity_term(haystack: str, term: str) -> bool:
        return alias_matches_text(haystack, term) if term else False

    @staticmethod
    def _looks_like_unrelated_release_document(document: NewsDocument) -> bool:
        haystack = " ".join(
            [
                document.title,
                document.source.title or "",
                document.source.publisher or "",
                document.source.url or "",
            ]
        ).lower()
        release_markers = (
            "google cloud release notes",
            "release notes",
            "changelog",
            "版本資訊",
            "更新日誌",
        )
        return any(marker in haystack for marker in release_markers)

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
        dated_documents = sorted(
            enumerate(documents),
            key=lambda pair: (pair[1].source.published_at or date.min, -pair[0]),
            reverse=True,
        )
        for _, document in dated_documents:
            source_key = (
                document.title,
                document.source.publisher,
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
        evidence_age_days = (today_taipei() - latest_date).days if latest_date else None
        evidence_stale = evidence_age_days is not None and evidence_age_days > STALE_CANDIDATE_EVIDENCE_DAYS
        credibility = summarize_source_credibility(documents)
        credibility_weight = float(credibility["average_weight"] or 0)
        evidence_score = min(evidence_count, 3) / 3 * 35
        source_score = min(source_count, 3) / 3 * 35
        timestamp_score = (len(dated_documents) / evidence_count * 10) if evidence_count else 0
        recency_score = TopicDiscoveryService._recency_score(latest_date)
        score = int(round(evidence_score + source_score + timestamp_score + recency_score))
        score = TopicDiscoveryService._cap_confidence_by_source_credibility(score, credibility)
        return {
            "score": min(score, 100),
            "label": TopicDiscoveryService._confidence_label(score),
            "source_credibility_score": int(round(credibility_weight * 100)),
            "source_credibility_label": TopicDiscoveryService._source_credibility_label(credibility_weight),
            "source_credibility_counts": credibility["tier_counts"],
            "latest_evidence_date": latest_date.isoformat() if latest_date else None,
            "evidence_age_days": evidence_age_days,
            "evidence_stale": evidence_stale,
        }

    @staticmethod
    def _cap_confidence_by_source_credibility(score: int, credibility: dict) -> int:
        high_ratio = credibility.get("high_credibility_ratio")
        low_ratio = credibility.get("low_credibility_ratio")
        average_weight = float(credibility.get("average_weight") or 0)
        high_count = int(credibility.get("high_credibility_count") or 0)
        low_count = int(credibility.get("low_credibility_count") or 0)
        if low_count and high_count < 2:
            return min(score, 74)
        if low_count and low_ratio and low_ratio >= 0.34:
            return min(score, 84)
        if high_ratio == 0 and low_ratio and low_ratio >= 0.5:
            return min(score, 74)
        if high_ratio == 0:
            return min(score, 88)
        if average_weight < 0.65:
            return min(score, 74)
        if average_weight < 0.75:
            return min(score, 84)
        return score

    @staticmethod
    def _source_credibility_label(weight: float) -> str:
        if weight >= 0.85:
            return "高"
        if weight >= 0.65:
            return "中"
        if weight > 0:
            return "低"
        return "未分級"

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
    def _candidate_status(
        evidence_count: int,
        source_count: int,
        confidence_score: int = 0,
        evidence_stale: bool = False,
    ) -> str:
        if evidence_count == 0:
            return "needs_evidence"
        if evidence_stale:
            return "weak_evidence"
        if evidence_count >= 2 and source_count >= 2 and is_high_confidence(confidence_score):
            return "evidence_supported"
        return "weak_evidence"

    @staticmethod
    def _candidate_validation_reason(
        evidence_count: int,
        source_count: int,
        confidence_score: int = 0,
        latest_evidence_date: Optional[str] = None,
        evidence_age_days: Optional[int] = None,
        evidence_stale: bool = False,
    ) -> str:
        stale_note = ""
        if evidence_stale and latest_evidence_date:
            stale_note = (
                f"最新候選來源為 {latest_evidence_date}，距今約 {evidence_age_days} 天，"
                "已超過 180 天新鮮度門檻；"
            )
        if evidence_count >= 2 and source_count >= 2 and is_high_confidence(confidence_score):
            return (
                stale_note
                + "通過候選入選門檻：至少 2 篇公司主題證據、2 個以上來源，且入選支持度達高分；"
                "正式分析可信度仍需另看風險/機會歸因、財報、估值與公司文件。"
            )
        if evidence_count >= 2 and source_count >= 2:
            return (
                stale_note
                + f"弱證據：篇數與來源數達標，但入選支持度只有 {confidence_score} 分，需補近期或有日期來源。"
            )
        if evidence_count > 0:
            return (
                stale_note
                + f"弱證據：目前只有 {evidence_count} 篇、{source_count} 個來源，避免單一來源造成誤判。"
            )
        return "待補證據：尚未找到公司實體與主題上下文同時成立的來源。"

    @staticmethod
    def _candidate_next_action(
        evidence_count: int,
        source_count: int,
        confidence_score: int = 0,
        evidence_stale: bool = False,
    ) -> str:
        if evidence_stale:
            return "優先補抓最近 180 天內官方公告、法說會、月營收與公司新聞後再驗證。"
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
    def enrich_plan(plan: TopicDiscoveryPlan, topic: str | None = None) -> TopicDiscoveryPlan:
        plan = plan.model_copy(deep=True)
        plan = TopicDiscoveryService._ensure_upstream_material_layer(plan, topic=topic)
        for subtopic in plan.subtopics:
            if not subtopic.source_intents:
                subtopic.source_intents = TopicDiscoveryService.infer_source_intents(subtopic)
        return plan

    @staticmethod
    def _ensure_upstream_material_layer(plan: TopicDiscoveryPlan, topic: str | None = None) -> TopicDiscoveryPlan:
        if not topic:
            return plan
        if not TopicDiscoveryService._requires_upstream_material_coverage(plan, topic=topic):
            return plan
        if TopicDiscoveryService._has_upstream_material_coverage(plan):
            return plan

        if TopicDiscoveryService._is_robotics_plan(plan, topic=topic):
            material_subtopics = TopicDiscoveryService._robotics_upstream_material_subtopics()
            material_candidates = TopicDiscoveryService._robotics_upstream_material_candidates()
        else:
            material_subtopics = TopicDiscoveryService._ai_upstream_material_subtopics()
            material_candidates = TopicDiscoveryService._ai_upstream_material_candidates()

        existing_subtopic_names = {subtopic.name for subtopic in plan.subtopics}
        for subtopic in material_subtopics:
            if subtopic.name in existing_subtopic_names:
                continue
            if len(plan.subtopics) >= 10:
                break
            plan.subtopics.append(subtopic)
            existing_subtopic_names.add(subtopic.name)

        existing_tickers = {candidate.ticker for candidate in plan.candidate_companies}
        for candidate in material_candidates:
            if candidate.ticker in existing_tickers:
                continue
            if len(plan.candidate_companies) >= 24:
                break
            plan.candidate_companies.append(candidate)
            existing_tickers.add(candidate.ticker)
        return plan

    @staticmethod
    def _ai_upstream_material_subtopics() -> list[DiscoverySubtopic]:
        return [
            DiscoverySubtopic(
                name="上游半導體與板材材料",
                rationale="材料端常先吃緊",
                objective="補查矽晶圓、電子級化學品、特用氣體、光阻、CCL、銅箔與玻纖布是否形成 AI 供應鏈瓶頸",
                required_evidence=["矽晶圓", "電子級化學品", "特用氣體", "CCL", "銅箔", "玻纖布"],
                risk_focus=["材料漲價", "供應受限", "認證週期", "庫存調整"],
                search_queries=[
                    "AI 供應鏈 上游材料 矽晶圓 電子級化學品 CCL 銅箔 玻纖布",
                    "AI supply chain upstream materials silicon wafer CCL copper foil glass fiber Taiwan",
                ],
                source_intents=["industry_news", "capacity_supply", "material_supply", "international_context"],
            )
        ]

    @staticmethod
    def _robotics_upstream_material_subtopics() -> list[DiscoverySubtopic]:
        return [
            DiscoverySubtopic(
                name="上游材料與關鍵原料",
                rationale="材料決定成本良率",
                objective="補查磁材、電磁鋼、軸承鋼/特殊鋼、工程塑膠、碳纖與鎂鋁合金是否限制機器人成本、重量與供給",
                required_evidence=["稀土磁材", "電磁鋼", "特殊鋼", "工程塑膠", "碳纖", "鎂鋁合金"],
                risk_focus=["原料漲價", "供應集中", "認證週期", "替代材料競爭"],
                search_queries=[
                    "機器人 上游材料 稀土磁材 電磁鋼 特殊鋼 工程塑膠",
                    "robotics upstream materials 稀土磁材 electrical steel 工程塑膠 carbon fiber Taiwan",
                ],
                source_intents=["industry_news", "capacity_supply", "material_supply", "international_context"],
            )
        ]

    @staticmethod
    def _ai_upstream_material_candidates() -> list[CandidateCompany]:
        return [
            CandidateCompany(ticker="2383", name="台光電", segment="高速 CCL / 低損耗材料", rationale="AI 伺服器高速板材", evidence_keywords=["CCL", "低損耗材料", "AI 伺服器"]),
            CandidateCompany(ticker="6213", name="聯茂", segment="高速 CCL", rationale="高速材料需求提升", evidence_keywords=["CCL", "高速材料", "資料中心"]),
            CandidateCompany(ticker="1815", name="富喬", segment="玻纖布", rationale="PCB 上游玻纖材料", evidence_keywords=["玻纖布", "PCB", "AI 伺服器"]),
            CandidateCompany(ticker="8358", name="金居", segment="銅箔", rationale="高階 PCB 上游銅箔", evidence_keywords=["銅箔", "PCB", "AI 伺服器"]),
            CandidateCompany(ticker="6488", name="環球晶", segment="矽晶圓", rationale="半導體上游晶圓材料", evidence_keywords=["矽晶圓", "半導體材料", "AI 晶片"]),
        ]

    @staticmethod
    def _robotics_upstream_material_candidates() -> list[CandidateCompany]:
        return [
            CandidateCompany(ticker="2002", name="中鋼", segment="電磁鋼 / 特殊鋼材", rationale="馬達與結構材料上游", evidence_keywords=["電磁鋼", "特殊鋼", "機器人"]),
            CandidateCompany(ticker="5009", name="榮剛", segment="特殊合金鋼", rationale="齒輪與關節用鋼材", evidence_keywords=["特殊鋼", "合金鋼", "精密機械"]),
            CandidateCompany(ticker="1303", name="南亞", segment="工程塑膠 / 電子材料", rationale="輕量化與絕緣材料", evidence_keywords=["工程塑膠", "電子材料", "複合材料"]),
            CandidateCompany(ticker="6235", name="華孚", segment="鎂鋁合金機構件", rationale="輕量化金屬機構件", evidence_keywords=["鎂鋁合金", "機構件", "輕量化"]),
        ]

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
            (
                "material_supply",
                [
                    "材料",
                    "原料",
                    "矽晶圓",
                    "化學品",
                    "特用氣體",
                    "光阻",
                    "ccl",
                    "銅箔",
                    "玻纖",
                    "磁材",
                    "特殊鋼",
                    "工程塑膠",
                    "carbon fiber",
                    "silicon wafer",
                    "copper foil",
                ],
            ),
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
        return topic_discovery_prompts.topic_discovery_prompt(topic)

    @staticmethod
    def _repair_prompt(topic: str, plan: TopicDiscoveryPlan, quality: DiscoveryPlanQuality) -> str:
        return topic_discovery_prompts.topic_discovery_repair_prompt(topic, plan, quality)
