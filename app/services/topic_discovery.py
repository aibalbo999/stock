from __future__ import annotations

import json
import re

from pydantic import ValidationError

from app.models.schemas import NewsDocument
from app.services import (
    topic_discovery_candidates,
    topic_discovery_enrichment,
    topic_discovery_prompts,
    topic_discovery_quality,
    topic_discovery_queries,
)
from app.services.llm_client import LLMClient
from app.services.topic_discovery_models import (
    CandidateCompany as CandidateCompany,
    DiscoveryPlanQuality as DiscoveryPlanQuality,
    DiscoverySubtopic as DiscoverySubtopic,
    TopicDiscoveryPlan as TopicDiscoveryPlan,
    ValidatedCandidate as ValidatedCandidate,
)
from app.services.whitelist import SupplyChainWhitelist


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
        return topic_discovery_quality.is_memory_plan(plan)

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
        return topic_discovery_quality.evaluate_plan_quality(plan)

    @staticmethod
    def _requires_broad_candidate_pool(plan: TopicDiscoveryPlan) -> bool:
        return topic_discovery_quality.requires_broad_candidate_pool(plan)

    @staticmethod
    def _plan_theme_coverage(plan: TopicDiscoveryPlan) -> dict[str, bool]:
        return topic_discovery_quality.plan_theme_coverage(plan)

    @staticmethod
    def _keyword_in_text(text: str, keyword: str) -> bool:
        return topic_discovery_quality.keyword_in_text(text, keyword)

    @staticmethod
    def _requires_upstream_material_coverage(plan: TopicDiscoveryPlan, topic: str | None = None) -> bool:
        return topic_discovery_quality.requires_upstream_material_coverage(plan, topic=topic)

    @staticmethod
    def _is_generic_exploration_plan(plan: TopicDiscoveryPlan) -> bool:
        return topic_discovery_quality.is_generic_exploration_plan(plan)

    @staticmethod
    def _has_upstream_material_coverage(plan: TopicDiscoveryPlan) -> bool:
        return topic_discovery_quality.has_upstream_material_coverage(plan)

    @staticmethod
    def _plan_search_text(plan: TopicDiscoveryPlan) -> str:
        return topic_discovery_quality.plan_search_text(plan)

    @staticmethod
    def _plan_query_quality(plan: TopicDiscoveryPlan) -> dict:
        return topic_discovery_quality.plan_query_quality(plan)

    @staticmethod
    def _query_aligns_subtopic(query: str, subtopic: DiscoverySubtopic) -> bool:
        return topic_discovery_queries.query_aligns_subtopic(query, subtopic)

    @staticmethod
    def _research_terms(subtopic: DiscoverySubtopic) -> list[str]:
        return topic_discovery_queries.research_terms(subtopic)

    @staticmethod
    def _meaningful_tokens(text: str) -> list[str]:
        return topic_discovery_queries.meaningful_tokens(text)

    @staticmethod
    def _is_generic_query(query: str) -> bool:
        return topic_discovery_queries.is_generic_query(query)

    @staticmethod
    def _is_noise_term(term: str) -> bool:
        return topic_discovery_queries.is_noise_term(term)

    def google_news_urls(
        self,
        plan: TopicDiscoveryPlan,
        include_international: bool = True,
        max_urls: int | None = None,
        topic: str | None = None,
        include_metadata: bool = False,
    ) -> list[str] | list[dict]:
        return topic_discovery_queries.google_news_urls(
            plan,
            include_international=include_international,
            max_urls=max_urls,
            topic=topic,
            include_metadata=include_metadata,
            evaluate_plan_quality=self.evaluate_plan_quality,
            infer_source_intents=self.infer_source_intents,
        )

    @staticmethod
    def _query_item(
        query: str,
        source_type: str,
        hypothesis: str,
        evidence_type: str,
        source_intent: str,
    ) -> dict:
        return topic_discovery_queries.query_item(query, source_type, hypothesis, evidence_type, source_intent)

    @staticmethod
    def _subtopic_hypothesis(subtopic: DiscoverySubtopic) -> str:
        return topic_discovery_queries.subtopic_hypothesis(subtopic)

    @staticmethod
    def _evidence_type(required_evidence: list[str], risk_focus: list[str]) -> str:
        return topic_discovery_queries.evidence_type(required_evidence, risk_focus)

    @staticmethod
    def _primary_source_intent(subtopic: DiscoverySubtopic) -> str:
        return topic_discovery_queries.primary_source_intent(
            subtopic,
            infer_source_intents=TopicDiscoveryService.infer_source_intents,
        )

    @staticmethod
    def _query_language(query: str) -> str:
        return topic_discovery_queries.query_language(query)

    @staticmethod
    def coverage_gap_queries(topic: str, quality: DiscoveryPlanQuality) -> list[str]:
        return topic_discovery_queries.coverage_gap_queries(topic, quality)

    @staticmethod
    def query_quality_gap_queries(topic: str, plan: TopicDiscoveryPlan, quality: DiscoveryPlanQuality) -> list[str]:
        return topic_discovery_queries.query_quality_gap_queries(topic, plan, quality)

    def supplemental_google_news_urls(
        self,
        plan: TopicDiscoveryPlan,
        validated_candidates: list[ValidatedCandidate],
        include_international: bool = True,
        max_urls: int | None = None,
        existing_urls: list[str] | None = None,
    ) -> list[str]:
        return topic_discovery_queries.supplemental_google_news_urls(
            plan,
            validated_candidates,
            include_international=include_international,
            max_urls=max_urls,
            existing_urls=existing_urls,
        )

    def supplemental_google_news_query_metadata(
        self,
        plan: TopicDiscoveryPlan,
        validated_candidates: list[ValidatedCandidate],
        include_international: bool = True,
        max_urls: int | None = None,
        existing_urls: list[str] | None = None,
        missing_subtopics: list[str] | None = None,
    ) -> list[dict]:
        return topic_discovery_queries.supplemental_google_news_query_metadata(
            plan,
            validated_candidates,
            include_international=include_international,
            max_urls=max_urls,
            existing_urls=existing_urls,
            missing_subtopics=missing_subtopics,
        )

    @staticmethod
    def _candidate_query_items(candidate: CandidateCompany, include_international: bool = True) -> list[dict]:
        return topic_discovery_queries.candidate_query_items(
            candidate,
            include_international=include_international,
        )

    @staticmethod
    def _supplemental_candidate_query_items(
        candidate: CandidateCompany,
        include_international: bool = True,
    ) -> list[dict]:
        return topic_discovery_queries.supplemental_candidate_query_items(
            candidate,
            include_international=include_international,
        )

    @staticmethod
    def _round_robin_query_groups(groups: list[list[dict]]) -> list[dict]:
        return topic_discovery_queries.round_robin_query_groups(groups)

    @staticmethod
    def _dedupe_query_items(items: list[dict]) -> list[dict]:
        return topic_discovery_queries.dedupe_query_items(items)

    @staticmethod
    def _dedupe_query_metadata(
        items: list[dict],
        max_urls: int | None = None,
        existing_urls: list[str] | None = None,
    ) -> list[dict]:
        return topic_discovery_queries.dedupe_query_metadata(
            items,
            max_urls=max_urls,
            existing_urls=existing_urls,
        )

    @staticmethod
    def missing_subtopic_names(source_relevance: dict) -> list[str]:
        return topic_discovery_queries.missing_subtopic_names(source_relevance)

    @staticmethod
    def _google_news_urls_from_queries(
        queries: list[str],
        max_urls: int | None = None,
        existing_urls: list[str] | None = None,
    ) -> list[str]:
        return topic_discovery_queries.google_news_urls_from_queries(
            queries,
            max_urls=max_urls,
            existing_urls=existing_urls,
        )

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
        return topic_discovery_queries.google_news_metadata_from_queries(
            queries,
            source_type,
            hypothesis,
            evidence_type,
            source_intent=source_intent,
            max_urls=max_urls,
            existing_urls=existing_urls,
        )

    @staticmethod
    def _international_context_queries() -> list[str]:
        return topic_discovery_queries.international_context_queries()

    def validate_candidates(
        self,
        plan: TopicDiscoveryPlan,
        documents: list[NewsDocument],
    ) -> list[ValidatedCandidate]:
        return topic_discovery_candidates.validate_candidates(plan, documents)

    @staticmethod
    def _candidate_entity_terms(candidate: CandidateCompany) -> list[str]:
        return topic_discovery_candidates.candidate_entity_terms(candidate)

    @staticmethod
    def _candidate_context_terms(candidate: CandidateCompany, plan: TopicDiscoveryPlan | None = None) -> list[str]:
        return topic_discovery_candidates.candidate_context_terms(candidate, plan)

    @staticmethod
    def _is_robotics_plan(plan: TopicDiscoveryPlan, topic: str | None = None) -> bool:
        return topic_discovery_quality.is_robotics_plan(plan, topic=topic)

    @staticmethod
    def _plan_or_candidate_mentions_robotics(candidate: CandidateCompany, plan: TopicDiscoveryPlan | None = None) -> bool:
        return topic_discovery_candidates.plan_or_candidate_mentions_robotics(candidate, plan)

    @staticmethod
    def _context_phrases(text: str) -> list[str]:
        return topic_discovery_candidates.context_phrases(text)

    @staticmethod
    def _has_entity_and_context(haystack: str, entity_terms: list[str], context_terms: list[str]) -> bool:
        return topic_discovery_candidates.has_entity_and_context(haystack, entity_terms, context_terms)

    @staticmethod
    def _has_entity_and_context_nearby(
        haystack: str,
        entity_terms: list[str],
        context_terms: list[str],
        window: int = 900,
    ) -> bool:
        return topic_discovery_candidates.has_entity_and_context_nearby(
            haystack,
            entity_terms,
            context_terms,
            window=window,
        )

    @staticmethod
    def _document_supports_candidate(
        document: NewsDocument,
        entity_terms: list[str],
        context_terms: list[str],
        relax_context_for_entity_match: bool = False,
    ) -> bool:
        return topic_discovery_candidates.document_supports_candidate(
            document,
            entity_terms,
            context_terms,
            relax_context_for_entity_match=relax_context_for_entity_match,
        )

    @staticmethod
    def _document_entity_metadata_match(document: NewsDocument, entity_terms: list[str]) -> bool | None:
        return topic_discovery_candidates.document_entity_metadata_match(document, entity_terms)

    @staticmethod
    def _has_context_term(normalized_haystack: str, context_terms: list[str]) -> bool:
        return topic_discovery_candidates.has_context_term(normalized_haystack, context_terms)

    @staticmethod
    def _term_positions(haystack: str, terms: list[str]) -> list[int]:
        return topic_discovery_candidates.term_positions(haystack, terms)

    @staticmethod
    def _contains_entity_term(haystack: str, term: str) -> bool:
        return topic_discovery_candidates.contains_entity_term(haystack, term)

    @staticmethod
    def _looks_like_unrelated_release_document(document: NewsDocument) -> bool:
        return topic_discovery_candidates.looks_like_unrelated_release_document(document)

    @staticmethod
    def _evidence_source_count(documents: list[NewsDocument]) -> int:
        return topic_discovery_candidates.evidence_source_count(documents)

    @staticmethod
    def _candidate_evidence_sources(documents: list[NewsDocument], limit: int = 5) -> list[dict]:
        return topic_discovery_candidates.candidate_evidence_sources(documents, limit=limit)

    @staticmethod
    def _candidate_evidence_confidence(documents: list[NewsDocument], source_count: int) -> dict:
        return topic_discovery_candidates.candidate_evidence_confidence(documents, source_count)

    @staticmethod
    def _cap_confidence_by_source_credibility(score: int, credibility: dict) -> int:
        return topic_discovery_candidates.cap_confidence_by_source_credibility(score, credibility)

    @staticmethod
    def _source_credibility_label(weight: float) -> str:
        return topic_discovery_candidates.source_credibility_label(weight)

    @staticmethod
    def _recency_score(latest_date) -> int:
        return topic_discovery_candidates.recency_score_for_latest_date(latest_date)

    @staticmethod
    def _confidence_label(score: int) -> str:
        return topic_discovery_candidates.confidence_label(score)

    @staticmethod
    def _candidate_status(
        evidence_count: int,
        source_count: int,
        confidence_score: int = 0,
        evidence_stale: bool = False,
    ) -> str:
        return topic_discovery_candidates.candidate_status(
            evidence_count,
            source_count,
            confidence_score=confidence_score,
            evidence_stale=evidence_stale,
        )

    @staticmethod
    def _candidate_validation_reason(
        evidence_count: int,
        source_count: int,
        confidence_score: int = 0,
        latest_evidence_date: str | None = None,
        evidence_age_days: int | None = None,
        evidence_stale: bool = False,
    ) -> str:
        return topic_discovery_candidates.candidate_validation_reason(
            evidence_count,
            source_count,
            confidence_score=confidence_score,
            latest_evidence_date=latest_evidence_date,
            evidence_age_days=evidence_age_days,
            evidence_stale=evidence_stale,
        )

    @staticmethod
    def _candidate_next_action(
        evidence_count: int,
        source_count: int,
        confidence_score: int = 0,
        evidence_stale: bool = False,
    ) -> str:
        return topic_discovery_candidates.candidate_next_action(
            evidence_count,
            source_count,
            confidence_score=confidence_score,
            evidence_stale=evidence_stale,
        )

    @staticmethod
    def parse_plan(raw_text: str) -> TopicDiscoveryPlan:
        json_text = TopicDiscoveryService._extract_json(raw_text)
        try:
            return TopicDiscoveryService.enrich_plan(TopicDiscoveryPlan.model_validate_json(json_text))
        except (ValidationError, ValueError) as exc:
            raise ValueError("invalid topic discovery json") from exc

    @staticmethod
    def enrich_plan(plan: TopicDiscoveryPlan, topic: str | None = None) -> TopicDiscoveryPlan:
        return topic_discovery_enrichment.enrich_plan(plan, topic=topic)

    @staticmethod
    def _ensure_upstream_material_layer(plan: TopicDiscoveryPlan, topic: str | None = None) -> TopicDiscoveryPlan:
        return topic_discovery_enrichment.ensure_upstream_material_layer(plan, topic=topic)

    @staticmethod
    def _ai_upstream_material_subtopics() -> list[DiscoverySubtopic]:
        return topic_discovery_enrichment.ai_upstream_material_subtopics()

    @staticmethod
    def _robotics_upstream_material_subtopics() -> list[DiscoverySubtopic]:
        return topic_discovery_enrichment.robotics_upstream_material_subtopics()

    @staticmethod
    def _ai_upstream_material_candidates() -> list[CandidateCompany]:
        return topic_discovery_enrichment.ai_upstream_material_candidates()

    @staticmethod
    def _robotics_upstream_material_candidates() -> list[CandidateCompany]:
        return topic_discovery_enrichment.robotics_upstream_material_candidates()

    @staticmethod
    def infer_source_intents(subtopic: DiscoverySubtopic) -> list[str]:
        return topic_discovery_enrichment.infer_source_intents(subtopic)

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
