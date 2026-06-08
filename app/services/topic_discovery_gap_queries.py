from __future__ import annotations

from app.services.topic_discovery_models import DiscoveryPlanQuality, TopicDiscoveryPlan


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


def query_quality_gap_queries(
    topic: str, plan: TopicDiscoveryPlan, quality: DiscoveryPlanQuality
) -> list[str]:
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
