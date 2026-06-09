from __future__ import annotations

import re

from app.services import (
    topic_discovery_ai_fallback,
    topic_discovery_enrichment,
    topic_discovery_quality,
)
from app.services.topic_discovery_models import (
    CandidateCompany,
    DiscoverySubtopic,
    TopicDiscoveryPlan,
)
from app.services.whitelist import SupplyChainWhitelist


def fallback_plan(topic: str) -> TopicDiscoveryPlan:
    if is_robotics_topic(topic):
        return robotics_fallback_plan(topic)
    if is_memory_topic(topic):
        return memory_fallback_plan(topic)
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
