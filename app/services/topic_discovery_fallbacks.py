from __future__ import annotations

import re

from app.services import (
    topic_discovery_ai_fallback,
    topic_discovery_enrichment,
    topic_discovery_memory_fallback,
    topic_discovery_quality,
    topic_discovery_robotics_fallback,
)
from app.services.topic_discovery_models import (
    CandidateCompany,
    DiscoverySubtopic,
    TopicDiscoveryPlan,
)
from app.services.whitelist import SupplyChainWhitelist


def fallback_plan(topic: str) -> TopicDiscoveryPlan:
    if is_robotics_topic(topic):
        return topic_discovery_robotics_fallback.robotics_fallback_plan(topic)
    if is_memory_topic(topic):
        return topic_discovery_memory_fallback.memory_fallback_plan(topic)
    if "AI" not in topic.upper() and "人工智慧" not in topic:
        return generic_exploration_plan(topic)
    return topic_discovery_ai_fallback.ai_fallback_plan()


def generic_exploration_plan(topic: str) -> TopicDiscoveryPlan:
    anchor_candidates = generic_anchor_candidates(topic)
    return topic_discovery_enrichment.enrich_plan(
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
                    search_queries=[
                        f"{topic} 需求 訂單 出貨 市場規模",
                        f"{topic} 需求 demand 訂單 order 出貨 shipment",
                    ],
                    source_intents=["industry_news", "international_context", "early_signal"],
                ),
                DiscoverySubtopic(
                    name=f"{topic} 供給與瓶頸",
                    rationale="找出供給端或產能端的約束",
                    objective="查核產能、良率、交期或供應瓶頸是否限制成長",
                    required_evidence=["產能", "良率", "交期", "瓶頸"],
                    risk_focus=["產能不足", "良率問題", "供給過剩"],
                    search_queries=[
                        f"{topic} 產能 良率 交期 瓶頸",
                        f"{topic} 產能 capacity 良率 yield 交期 lead time",
                    ],
                    source_intents=["capacity_supply", "industry_news", "international_context"],
                ),
                DiscoverySubtopic(
                    name=f"{topic} 財務與估值",
                    rationale="先判斷市場是否已經過度反映",
                    objective="比較月營收、毛利率、本益比與現金流是否匹配成長假設",
                    required_evidence=["月營收", "毛利率", "本益比", "現金流"],
                    risk_focus=["估值過高", "獲利下滑", "現金流惡化"],
                    search_queries=[
                        f"{topic} 月營收 毛利率 本益比 現金流",
                        f"{topic} 月營收 revenue 毛利率 margin 本益比 valuation",
                    ],
                    source_intents=["financial_metrics", "valuation", "company_disclosure"],
                ),
                DiscoverySubtopic(
                    name=f"{topic} 上游材料與設備",
                    rationale="確認上游原料、材料或設備是否會成為新瓶頸",
                    objective="追蹤材料、零組件、設備與供應商是否能支持主題成長",
                    required_evidence=["材料", "設備", "供應商", "原料"],
                    risk_focus=["材料漲價", "供應受限", "設備交期"],
                    search_queries=[
                        f"{topic} 材料 設備 供應商 原料",
                        f"{topic} 材料 materials 設備 equipment 供應商 supplier",
                    ],
                    source_intents=["material_supply", "capacity_supply", "company_disclosure"],
                ),
                DiscoverySubtopic(
                    name=f"{topic} 風險與外部變數",
                    rationale="把政策、國際與執行風險先攤開",
                    objective="評估政策、法規、地緣與市場情緒對主題的影響",
                    required_evidence=["政策", "法規", "國際", "風險"],
                    risk_focus=["政策變動", "地緣政治", "外部需求放緩"],
                    search_queries=[
                        f"{topic} 政策 法規 國際 風險",
                        f"{topic} 政策 policy 法規 regulation 國際 global",
                    ],
                    source_intents=["regulatory_policy", "international_context", "industry_news"],
                ),
                DiscoverySubtopic(
                    name=f"{topic} 候選驗證與收斂",
                    rationale="先用候選驗證把主題落到公司層級",
                    objective="找出能被新聞、公司文件與財務資料共同驗證的候選公司",
                    required_evidence=["公司文件", "新聞", "月營收", "財務資料"],
                    risk_focus=["錯誤歸因", "過度題材化", "證據不足"],
                    search_queries=[
                        f"{topic} 公司文件 月營收 財務 資料",
                        f"{topic} 公司文件 company disclosure 月營收 revenue 財務 financial",
                    ],
                    source_intents=["company_disclosure", "financial_metrics", "industry_news"],
                ),
            ],
            candidate_companies=anchor_candidates,
        )
    )


def generic_anchor_candidates(topic: str) -> list[CandidateCompany]:
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
    ranked = [
        candidate for _, candidate in sorted(scored, key=lambda item: (-item[0], item[1].ticker))
    ]
    if ranked:
        return ranked[: max(6, min(12, len(ranked)))]
    return []


def memory_fallback_plan(topic: str) -> TopicDiscoveryPlan:
    return topic_discovery_memory_fallback.memory_fallback_plan(topic)


def is_robotics_topic(topic: str) -> bool:
    normalized = topic.lower()
    return any(
        term in normalized for term in ["機器人", "robot", "robotics", "humanoid", "協作機器人"]
    )


def is_memory_topic(topic: str) -> bool:
    normalized = topic.lower()
    return any(term in normalized for term in ["記憶體", "memory", "dram", "nand", "flash", "ssd"])


def is_memory_plan(plan: TopicDiscoveryPlan) -> bool:
    return topic_discovery_quality.is_memory_plan(plan)


def robotics_fallback_plan(topic: str) -> TopicDiscoveryPlan:
    return topic_discovery_robotics_fallback.robotics_fallback_plan(topic)
