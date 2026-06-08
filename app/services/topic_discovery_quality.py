from __future__ import annotations

import re

from app.services import topic_discovery_queries
from app.services.topic_discovery_models import DiscoveryPlanQuality, TopicDiscoveryPlan


def evaluate_plan_quality(plan: TopicDiscoveryPlan) -> DiscoveryPlanQuality:
    missing = []
    query_quality = plan_query_quality(plan)
    if not plan.subtopics:
        missing.append("缺少研究子題")
    if not plan.candidate_companies:
        missing.append("缺少候選公司")
    if requires_broad_candidate_pool(plan) and len(plan.candidate_companies) < 15:
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

    coverage = plan_theme_coverage(plan)
    if requires_upstream_material_coverage(plan) and not is_generic_exploration_plan(plan):
        coverage["上游材料"] = has_upstream_material_coverage(plan)
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


def requires_broad_candidate_pool(plan: TopicDiscoveryPlan) -> bool:
    if is_generic_exploration_plan(plan):
        return False
    if is_memory_plan(plan):
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


def plan_theme_coverage(plan: TopicDiscoveryPlan) -> dict[str, bool]:
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
        theme: any(keyword_in_text(joined, keyword) for keyword in keywords)
        for theme, keywords in themes.items()
    }


def keyword_in_text(text: str, keyword: str) -> bool:
    normalized = keyword.lower()
    if normalized in {"pe", "pb"}:
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", text))
    return normalized in text


def requires_upstream_material_coverage(plan: TopicDiscoveryPlan, topic: str | None = None) -> bool:
    if is_generic_exploration_plan(plan):
        return False
    text = " ".join([topic or "", plan_search_text(plan)]).lower()
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


def is_generic_exploration_plan(plan: TopicDiscoveryPlan) -> bool:
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


def has_upstream_material_coverage(plan: TopicDiscoveryPlan) -> bool:
    text = plan_search_text(plan)
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
    groups = ai_material_groups if not is_robotics_plan(plan) else robotics_material_groups
    covered_groups = sum(1 for group in groups if any(term in text for term in group))
    return covered_groups >= 2


def plan_search_text(plan: TopicDiscoveryPlan) -> str:
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


def plan_query_quality(plan: TopicDiscoveryPlan) -> dict:
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
            language = topic_discovery_queries.query_language(query)
            languages.append(language)
            if topic_discovery_queries.is_generic_query(query):
                generic_queries.append(query)
                generic_query_count += 1
                continue
            if language in {"en", "mixed"}:
                international_query_count += 1
            if topic_discovery_queries.query_aligns_subtopic(query, subtopic):
                aligned_queries += 1
            else:
                unaligned_queries.append(query)
        subtopic_quality[label] = {
            "query_count": len(subtopic.search_queries),
            "languages": languages,
            "has_international_query": any(
                topic_discovery_queries.query_language(query) in {"en", "mixed"}
                and not topic_discovery_queries.is_generic_query(query)
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


def is_memory_plan(plan: TopicDiscoveryPlan) -> bool:
    text = plan_search_text(plan)
    return any(term in text for term in ["記憶體", "memory", "dram", "nand", "flash", "ssd"])


def is_robotics_plan(plan: TopicDiscoveryPlan, topic: str | None = None) -> bool:
    text = " ".join([topic or "", plan_search_text(plan)]).lower()
    return "機器人" in text or any(
        term in text for term in ["robot", "robotics", "humanoid", "servo", "automation", "agv"]
    )
