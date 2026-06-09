from __future__ import annotations

from app.services import topic_discovery_enrichment
from app.services.topic_discovery_models import (
    CandidateCompany,
    DiscoverySubtopic,
    TopicDiscoveryPlan,
)


def memory_fallback_plan(topic: str) -> TopicDiscoveryPlan:
    return topic_discovery_enrichment.enrich_plan(
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


__all__ = ["memory_fallback_plan"]
