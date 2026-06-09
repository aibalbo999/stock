from __future__ import annotations

from app.services import topic_discovery_enrichment
from app.services.topic_discovery_models import (
    CandidateCompany,
    DiscoverySubtopic,
    TopicDiscoveryPlan,
)


def robotics_fallback_plan(topic: str) -> TopicDiscoveryPlan:
    return topic_discovery_enrichment.enrich_plan(
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
                    required_evidence=[
                        "稀土磁材",
                        "電磁鋼",
                        "特殊鋼",
                        "工程塑膠",
                        "碳纖",
                        "鎂鋁合金",
                    ],
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
                CandidateCompany(
                    ticker="2308",
                    name="台達電",
                    segment="伺服驅動與控制系統",
                    rationale="工業自動化、伺服驅動與電源管理完整",
                    evidence_keywords=["伺服馬達", "控制器", "智慧製造"],
                ),
                CandidateCompany(
                    ticker="2359",
                    name="所羅門",
                    segment="AI 3D 視覺軟體",
                    rationale="AI 視覺與機器人辨識題材",
                    evidence_keywords=["AI 視覺", "3D 視覺", "機器人"],
                ),
                CandidateCompany(
                    ticker="2049",
                    name="上銀",
                    segment="滾珠螺桿與線性滑軌",
                    rationale="精密傳動元件與自動化需求相關",
                    evidence_keywords=["滾珠螺桿", "線性滑軌", "機器人"],
                ),
                CandidateCompany(
                    ticker="1590",
                    name="亞德客-KY",
                    segment="氣動與線性傳動",
                    rationale="自動化氣動元件受惠工廠自動化",
                    evidence_keywords=["氣動元件", "自動化", "線性傳動"],
                ),
                CandidateCompany(
                    ticker="2395",
                    name="研華",
                    segment="工業電腦與邊緣運算",
                    rationale="工業電腦、邊緣 AI 與機器人控制應用",
                    evidence_keywords=["工業電腦", "邊緣運算", "機器人"],
                ),
                CandidateCompany(
                    ticker="6235",
                    name="華孚",
                    segment="鎂鋁合金機構件",
                    rationale="輕量化金屬機構件可用於機器人與電動載具",
                    evidence_keywords=["鎂鋁合金", "機構件", "輕量化"],
                ),
                CandidateCompany(
                    ticker="4583",
                    name="大銀微系統",
                    segment="直驅馬達與定位平台",
                    rationale="精密定位平台與直驅元件具機器人關聯",
                    evidence_keywords=["直驅馬達", "定位平台", "精密傳動"],
                ),
                CandidateCompany(
                    ticker="1597",
                    name="直得",
                    segment="微型線性滑軌",
                    rationale="微型線性滑軌可切入精密自動化與機器人",
                    evidence_keywords=["微型線性滑軌", "機器人", "自動化"],
                ),
                CandidateCompany(
                    ticker="3059",
                    name="華晶科",
                    segment="3D 感測相機",
                    rationale="影像與 3D 感測可支援機器視覺",
                    evidence_keywords=["3D 感測", "機器視覺", "鏡頭"],
                ),
                CandidateCompany(
                    ticker="4540",
                    name="盟立",
                    segment="自動化系統整合",
                    rationale="自動化設備與系統整合具機器人導入題材",
                    evidence_keywords=["自動化", "系統整合", "機器人"],
                ),
                CandidateCompany(
                    ticker="6188",
                    name="廣明",
                    segment="協作型機器人",
                    rationale="協作型機器人與自動化設備題材",
                    evidence_keywords=["協作機器人", "自動化", "機器人"],
                ),
                CandidateCompany(
                    ticker="2301",
                    name="光寶科",
                    segment="電源管理系統",
                    rationale="電源與感測模組可用於機器人平台",
                    evidence_keywords=["電源", "感測", "機器人"],
                ),
                CandidateCompany(
                    ticker="1504",
                    name="東元",
                    segment="伺服馬達與 AGV",
                    rationale="馬達、電控與 AGV 自動化應用",
                    evidence_keywords=["伺服馬達", "AGV", "自動化"],
                ),
                CandidateCompany(
                    ticker="3019",
                    name="亞光",
                    segment="光學鏡頭",
                    rationale="光學鏡頭與感測可支援機器視覺",
                    evidence_keywords=["光學鏡頭", "機器視覺", "感測"],
                ),
                CandidateCompany(
                    ticker="3548",
                    name="兆利",
                    segment="精密轉軸與關節機構",
                    rationale="轉軸與精密機構件可對應機器人關節",
                    evidence_keywords=["轉軸", "關節", "機構件"],
                ),
                CandidateCompany(
                    ticker="5443",
                    name="均豪",
                    segment="半導體自動化與機械手臂整合",
                    rationale="自動化設備與機械手臂整合經驗",
                    evidence_keywords=["自動化", "機械手臂", "半導體設備"],
                ),
                CandidateCompany(
                    ticker="8374",
                    name="羅昇",
                    segment="自動化驅動與視覺代理",
                    rationale="代理自動化零組件與視覺控制產品",
                    evidence_keywords=["自動化", "驅動", "機器視覺"],
                ),
                CandidateCompany(
                    ticker="2002",
                    name="中鋼",
                    segment="電磁鋼 / 特殊鋼材",
                    rationale="馬達與結構材料上游",
                    evidence_keywords=["電磁鋼", "特殊鋼", "機器人"],
                ),
                CandidateCompany(
                    ticker="5009",
                    name="榮剛",
                    segment="特殊合金鋼",
                    rationale="齒輪與關節用鋼材",
                    evidence_keywords=["特殊鋼", "合金鋼", "精密機械"],
                ),
                CandidateCompany(
                    ticker="1303",
                    name="南亞",
                    segment="工程塑膠 / 電子材料",
                    rationale="輕量化與絕緣材料",
                    evidence_keywords=["工程塑膠", "電子材料", "複合材料"],
                ),
            ],
        )
    )


__all__ = ["robotics_fallback_plan"]
