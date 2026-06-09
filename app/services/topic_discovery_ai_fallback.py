from __future__ import annotations

from app.services import topic_discovery_enrichment
from app.services.topic_discovery_models import (
    CandidateCompany,
    DiscoverySubtopic,
    TopicDiscoveryPlan,
)


def ai_fallback_plan() -> TopicDiscoveryPlan:
    return topic_discovery_enrichment.enrich_plan(
        TopicDiscoveryPlan(
            subtopics=[
                DiscoverySubtopic(
                    name="AI 伺服器需求",
                    rationale="雲端資本支出",
                    objective="確認 CSP 資本支出、AI 伺服器出貨與台廠訂單是否成長",
                    required_evidence=["CSP 資本支出", "AI 伺服器出貨", "月營收"],
                    risk_focus=["需求下修", "砍單", "客戶集中"],
                    search_queries=[
                        "AI 伺服器 出貨 月營收 台廠",
                        "cloud capex AI server 出貨 月營收",
                    ],
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
                    search_queries=[
                        "AI 伺服器 液冷訂單 散熱滲透率 電源規格",
                        "AI data center liquid cooling 電源規格",
                    ],
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
                    search_queries=[
                        "台股 AI 供應鏈 月營收 本益比 估值",
                        "Taiwan AI valuation revenue margin 本益比",
                    ],
                ),
                DiscoverySubtopic(
                    name="地緣政治與電力",
                    rationale="外部限制",
                    objective="評估出口管制、缺電與資料中心電網限制對供應鏈的影響",
                    required_evidence=["出口管制", "缺電", "電網負荷"],
                    risk_focus=["美國晶片管制", "地緣政治", "電力瓶頸"],
                    search_queries=[
                        "AI 晶片 出口管制 台灣 供應鏈 缺電",
                        "US export controls AI chips 電網負荷",
                    ],
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


__all__ = ["ai_fallback_plan"]
