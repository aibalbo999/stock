from __future__ import annotations

from app.services import topic_discovery_quality, topic_discovery_queries
from app.services.topic_discovery_models import CandidateCompany, DiscoverySubtopic, TopicDiscoveryPlan


def enrich_plan(plan: TopicDiscoveryPlan, topic: str | None = None) -> TopicDiscoveryPlan:
    plan = plan.model_copy(deep=True)
    plan = ensure_upstream_material_layer(plan, topic=topic)
    for subtopic in plan.subtopics:
        if not subtopic.source_intents:
            subtopic.source_intents = infer_source_intents(subtopic)
    return plan


def ensure_upstream_material_layer(plan: TopicDiscoveryPlan, topic: str | None = None) -> TopicDiscoveryPlan:
    if not topic:
        return plan
    if not topic_discovery_quality.requires_upstream_material_coverage(plan, topic=topic):
        return plan
    if topic_discovery_quality.has_upstream_material_coverage(plan):
        return plan

    if topic_discovery_quality.is_robotics_plan(plan, topic=topic):
        material_subtopics = robotics_upstream_material_subtopics()
        material_candidates = robotics_upstream_material_candidates()
    else:
        material_subtopics = ai_upstream_material_subtopics()
        material_candidates = ai_upstream_material_candidates()

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


def ai_upstream_material_subtopics() -> list[DiscoverySubtopic]:
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


def robotics_upstream_material_subtopics() -> list[DiscoverySubtopic]:
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


def ai_upstream_material_candidates() -> list[CandidateCompany]:
    return [
        CandidateCompany(ticker="2383", name="台光電", segment="高速 CCL / 低損耗材料", rationale="AI 伺服器高速板材", evidence_keywords=["CCL", "低損耗材料", "AI 伺服器"]),
        CandidateCompany(ticker="6213", name="聯茂", segment="高速 CCL", rationale="高速材料需求提升", evidence_keywords=["CCL", "高速材料", "資料中心"]),
        CandidateCompany(ticker="1815", name="富喬", segment="玻纖布", rationale="PCB 上游玻纖材料", evidence_keywords=["玻纖布", "PCB", "AI 伺服器"]),
        CandidateCompany(ticker="8358", name="金居", segment="銅箔", rationale="高階 PCB 上游銅箔", evidence_keywords=["銅箔", "PCB", "AI 伺服器"]),
        CandidateCompany(ticker="6488", name="環球晶", segment="矽晶圓", rationale="半導體上游晶圓材料", evidence_keywords=["矽晶圓", "半導體材料", "AI 晶片"]),
    ]


def robotics_upstream_material_candidates() -> list[CandidateCompany]:
    return [
        CandidateCompany(ticker="2002", name="中鋼", segment="電磁鋼 / 特殊鋼材", rationale="馬達與結構材料上游", evidence_keywords=["電磁鋼", "特殊鋼", "機器人"]),
        CandidateCompany(ticker="5009", name="榮剛", segment="特殊合金鋼", rationale="齒輪與關節用鋼材", evidence_keywords=["特殊鋼", "合金鋼", "精密機械"]),
        CandidateCompany(ticker="1303", name="南亞", segment="工程塑膠 / 電子材料", rationale="輕量化與絕緣材料", evidence_keywords=["工程塑膠", "電子材料", "複合材料"]),
        CandidateCompany(ticker="6235", name="華孚", segment="鎂鋁合金機構件", rationale="輕量化金屬機構件", evidence_keywords=["鎂鋁合金", "機構件", "輕量化"]),
    ]


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
        topic_discovery_queries.query_language(query) in {"en", "mixed"} for query in subtopic.search_queries
    ):
        intents.append("international_context")
    return list(dict.fromkeys(intents))[:6]
