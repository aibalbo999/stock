from __future__ import annotations

import re
from collections.abc import Callable

from app.services import topic_discovery_candidate_queries, topic_discovery_news_queries
from app.services.topic_discovery_models import (
    CandidateCompany,
    DiscoveryPlanQuality,
    DiscoverySubtopic,
    TopicDiscoveryPlan,
    ValidatedCandidate,
)

PlanQualityEvaluator = Callable[[TopicDiscoveryPlan], DiscoveryPlanQuality]
SourceIntentInferer = Callable[[DiscoverySubtopic], list[str]]


def query_aligns_subtopic(query: str, subtopic: DiscoverySubtopic) -> bool:
    query_text = query.lower()
    terms = research_terms(subtopic)
    if any(term.lower() in query_text for term in terms):
        return True
    query_tokens = set(meaningful_tokens(query_text))
    term_tokens = set()
    for term in terms:
        term_tokens.update(meaningful_tokens(term))
    return bool(query_tokens & term_tokens)


def research_terms(subtopic: DiscoverySubtopic) -> list[str]:
    raw_terms = [
        subtopic.name,
        *subtopic.required_evidence,
        *subtopic.risk_focus,
        *meaningful_tokens(subtopic.objective),
        *meaningful_tokens(subtopic.rationale),
    ]
    return [
        term
        for term in dict.fromkeys(term.strip() for term in raw_terms)
        if term and not is_noise_term(term)
    ]


def meaningful_tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[A-Za-z][A-Za-z0-9+\-/]{1,}|\d{2,}|[\u4e00-\u9fff]{2,}", text)
        if not is_noise_term(token)
    ]


def is_generic_query(query: str) -> bool:
    tokens = meaningful_tokens(query)
    if len(tokens) <= 1:
        return True
    signal_tokens = [token for token in tokens if not is_noise_term(token)]
    return len(signal_tokens) <= 1


def is_noise_term(term: str) -> bool:
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
    plan: TopicDiscoveryPlan,
    include_international: bool = True,
    max_urls: int | None = None,
    topic: str | None = None,
    include_metadata: bool = False,
    *,
    evaluate_plan_quality: PlanQualityEvaluator,
    infer_source_intents: SourceIntentInferer,
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
                query_item(
                    task_terms.strip(),
                    "research_task",
                    subtopic_hypothesis(subtopic),
                    evidence_type(subtopic.required_evidence, subtopic.risk_focus),
                    primary_source_intent(subtopic, infer_source_intents=infer_source_intents),
                )
            )
        for query_index, query in enumerate(subtopic.search_queries):
            item = query_item(
                query,
                "subtopic",
                subtopic_hypothesis(subtopic),
                evidence_type(subtopic.required_evidence, subtopic.risk_focus),
                primary_source_intent(subtopic, infer_source_intents=infer_source_intents),
            )
            if query_index == 0:
                subtopic_primary_queries.append(item)
            else:
                subtopic_extra_queries.append(item)
            if include_international:
                international_item = (
                    query_item(
                        f"{query} global market",
                        "subtopic_international",
                        subtopic_hypothesis(subtopic),
                        evidence_type(subtopic.required_evidence, subtopic.risk_focus),
                        "international_context",
                    )
                )
                if query_index == 0:
                    subtopic_primary_queries.append(international_item)
                else:
                    subtopic_extra_queries.append(international_item)
    queries.extend(subtopic_primary_queries)
    queries.extend(
        round_robin_query_groups(
            [
                candidate_query_items(candidate, include_international=include_international)
                for candidate in plan.candidate_companies
            ]
        )
    )
    queries.extend(subtopic_extra_queries)
    if topic:
        plan_quality = evaluate_plan_quality(plan)
        queries.extend(
            query_item(
                query,
                "query_quality_gap",
                f"補強「{topic}」中過於籠統、未對齊或缺國際資料的搜尋 query。",
                "查詢品質補強",
                "industry_news",
            )
            for query in query_quality_gap_queries(topic, plan, plan_quality)
        )
        queries.extend(
            query_item(
                query,
                "coverage_gap",
                f"補齊「{topic}」研究拆解品質缺口。",
                "品質缺口補強",
                "industry_news",
            )
            for query in coverage_gap_queries(topic, plan_quality)
        )
    if include_international:
        queries.extend(
            query_item(
                query,
                "international_context",
                "補充國際市場、雲端資本支出與供應鏈背景，避免只看台灣新聞。",
                "國際背景",
                "international_context",
            )
            for query in international_context_queries()
        )
    for item in queries:
        query = item["query"]
        normalized = query.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        url = topic_discovery_news_queries.google_news_url(normalized)
        urls.append(url)
        metadata.append({**item, "url": url, "query": normalized, "language": query_language(normalized)})
        if max_urls and len(urls) >= max_urls:
            break
    return metadata if include_metadata else urls


def query_item(
    query: str,
    source_type: str,
    hypothesis: str,
    evidence_type: str,
    source_intent: str,
) -> dict:
    return topic_discovery_news_queries.query_item(
        query, source_type, hypothesis, evidence_type, source_intent
    )


def subtopic_hypothesis(subtopic: DiscoverySubtopic) -> str:
    objective = subtopic.objective.strip()
    if objective:
        return objective
    return f"驗證「{subtopic.name}」是否影響本主題的投資機會或風險。"


def evidence_type(required_evidence: list[str], risk_focus: list[str]) -> str:
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


def primary_source_intent(
    subtopic: DiscoverySubtopic,
    *,
    infer_source_intents: SourceIntentInferer | None = None,
) -> str:
    if subtopic.source_intents:
        return subtopic.source_intents[0]
    if infer_source_intents is None:
        return "industry_news"
    return infer_source_intents(subtopic)[0]


def query_language(query: str) -> str:
    return topic_discovery_news_queries.query_language(query)


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
    plan: TopicDiscoveryPlan,
    validated_candidates: list[ValidatedCandidate],
    include_international: bool = True,
    max_urls: int | None = None,
    existing_urls: list[str] | None = None,
) -> list[str]:
    return [
        item["url"]
        for item in supplemental_google_news_query_metadata(
            plan,
            validated_candidates,
            include_international=include_international,
            max_urls=max_urls,
            existing_urls=existing_urls,
        )
    ]


def supplemental_google_news_query_metadata(
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
        round_robin_query_groups(
            [
                supplemental_candidate_query_items(
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
        google_news_metadata_from_queries(
            queries,
            source_type="supplemental",
            hypothesis=topic_discovery_candidate_queries.SUPPLEMENTAL_HYPOTHESIS,
            evidence_type="補抓資料源",
            source_intent="company_disclosure",
            max_urls=None,
            existing_urls=[],
        )
    )
    return dedupe_query_metadata(
        query_items,
        max_urls=max_urls,
        existing_urls=existing_urls or [],
    )


def candidate_query_items(candidate: CandidateCompany, include_international: bool = True) -> list[dict]:
    return topic_discovery_candidate_queries.candidate_query_items(
        candidate,
        include_international=include_international,
    )


def supplemental_candidate_query_items(
    candidate: CandidateCompany,
    include_international: bool = True,
) -> list[dict]:
    return topic_discovery_candidate_queries.supplemental_candidate_query_items(
        candidate,
        include_international=include_international,
    )


def round_robin_query_groups(groups: list[list[dict]]) -> list[dict]:
    return topic_discovery_candidate_queries.round_robin_query_groups(groups)


def dedupe_query_items(items: list[dict]) -> list[dict]:
    return topic_discovery_news_queries.dedupe_query_items(items)


def dedupe_query_metadata(
    items: list[dict],
    max_urls: int | None = None,
    existing_urls: list[str] | None = None,
) -> list[dict]:
    return topic_discovery_news_queries.dedupe_query_metadata(
        items,
        max_urls=max_urls,
        existing_urls=existing_urls,
    )


def missing_subtopic_names(source_relevance: dict) -> list[str]:
    readiness = source_relevance.get("subtopic_readiness") or {}
    return [
        name
        for name, detail in readiness.items()
        if isinstance(detail, dict) and detail.get("status") == "missing"
    ]


def google_news_urls_from_queries(
    queries: list[str],
    max_urls: int | None = None,
    existing_urls: list[str] | None = None,
) -> list[str]:
    return topic_discovery_news_queries.google_news_urls_from_queries(
        queries,
        max_urls=max_urls,
        existing_urls=existing_urls,
    )


def google_news_metadata_from_queries(
    queries: list[str],
    source_type: str,
    hypothesis: str,
    evidence_type: str,
    source_intent: str = "industry_news",
    max_urls: int | None = None,
    existing_urls: list[str] | None = None,
) -> list[dict]:
    return topic_discovery_news_queries.google_news_metadata_from_queries(
        queries,
        source_type,
        hypothesis,
        evidence_type,
        source_intent=source_intent,
        max_urls=max_urls,
        existing_urls=existing_urls,
    )


def international_context_queries() -> list[str]:
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
