from __future__ import annotations

import re
from datetime import date

from app.core.time import today_taipei
from app.models.schemas import NewsDocument
from app.services.candidate_confidence import confidence_level, is_high_confidence
from app.services.entity_mapping import alias_matches_text, alias_positions, company_filing_owner_ticker
from app.services.source_quality import is_formal_evidence_document, summarize_source_credibility
from app.services.topic_discovery_models import CandidateCompany, TopicDiscoveryPlan, ValidatedCandidate
from app.services.topic_discovery_quality import is_memory_plan
from app.services.whitelist import SupplyChainWhitelist

STALE_CANDIDATE_EVIDENCE_DAYS = 180


def validate_candidates(
    plan: TopicDiscoveryPlan,
    documents: list[NewsDocument],
) -> list[ValidatedCandidate]:
    validated: list[ValidatedCandidate] = []
    relax_context_for_entity_match = is_memory_plan(plan)
    for candidate in plan.candidate_companies:
        evidence_documents = []
        entity_terms = candidate_entity_terms(candidate)
        context_terms = candidate_context_terms(candidate, plan)
        for document in documents:
            if not is_formal_evidence_document(document):
                continue
            if document_supports_candidate(
                document,
                entity_terms,
                context_terms,
                relax_context_for_entity_match=relax_context_for_entity_match,
            ):
                evidence_documents.append(document)
        deduped_titles = list(dict.fromkeys(document.title for document in evidence_documents))[:5]
        source_count = evidence_source_count(evidence_documents)
        evidence_sources = candidate_evidence_sources(evidence_documents)
        confidence = candidate_evidence_confidence(evidence_documents, source_count)
        status = candidate_status(
            len(evidence_documents),
            source_count,
            confidence["score"],
            confidence["evidence_stale"],
        )
        validated.append(
            ValidatedCandidate(
                ticker=candidate.ticker,
                name=candidate.name,
                segment=candidate.segment,
                rationale=candidate.rationale,
                evidence_keywords=candidate.evidence_keywords,
                evidence_count=len(evidence_documents),
                evidence_source_count=source_count,
                evidence_titles=deduped_titles,
                evidence_sources=evidence_sources,
                evidence_confidence_score=confidence["score"],
                evidence_confidence_label=confidence["label"],
                source_credibility_score=confidence["source_credibility_score"],
                source_credibility_label=confidence["source_credibility_label"],
                source_credibility_counts=confidence["source_credibility_counts"],
                latest_evidence_date=confidence["latest_evidence_date"],
                evidence_age_days=confidence["evidence_age_days"],
                evidence_stale=confidence["evidence_stale"],
                status=status,
                validation_reason=candidate_validation_reason(
                    len(evidence_documents),
                    source_count,
                    confidence["score"],
                    confidence["latest_evidence_date"],
                    confidence["evidence_age_days"],
                    confidence["evidence_stale"],
                ),
                next_action=candidate_next_action(
                    len(evidence_documents),
                    source_count,
                    confidence["score"],
                    confidence["evidence_stale"],
                ),
                promotion_eligible=status == "evidence_supported",
            )
        )
    return validated


def candidate_entity_terms(candidate: CandidateCompany) -> list[str]:
    terms = [candidate.ticker, candidate.name]
    whitelist = SupplyChainWhitelist()
    for company in whitelist.companies():
        if company.ticker == candidate.ticker or company.name == candidate.name:
            terms.extend(company.aliases)
            terms.append(company.name)
            break
    return list(dict.fromkeys(term for term in terms if term))


def candidate_context_terms(candidate: CandidateCompany, plan: TopicDiscoveryPlan | None = None) -> list[str]:
    terms = []
    terms.extend(candidate.evidence_keywords)
    terms.extend(context_phrases(candidate.segment))
    terms.extend(context_phrases(candidate.rationale))
    for subtopic in (plan.subtopics if plan else []):
        terms.extend(context_phrases(subtopic.name))
        terms.extend(subtopic.required_evidence)
        terms.extend(subtopic.risk_focus)
    terms.extend(
        [
            "AI 伺服器",
            "AI伺服器",
            "資料中心",
            "CoWoS",
            "HBM",
            "先進封裝",
            "液冷",
            "散熱",
            "電源",
            "算力",
            "雲端",
            "CSP",
            "capex",
            "server",
        ]
    )
    if plan_or_candidate_mentions_robotics(candidate, plan):
        terms.extend(
            [
                "機器人",
                "自動化",
                "協作機器人",
                "人形機器人",
                "工業機器人",
                "機器視覺",
                "3D 視覺",
                "感測",
                "伺服",
                "伺服馬達",
                "控制器",
                "減速器",
                "滾珠螺桿",
                "線性滑軌",
                "精密傳動",
                "AGV",
                "robot",
                "robotics",
                "automation",
                "servo",
                "machine vision",
                "motion control",
                "磁材",
                "稀土",
                "電磁鋼",
                "特殊鋼",
                "工程塑膠",
                "碳纖",
                "鎂鋁合金",
                "rare earth",
                "magnet",
                "special steel",
                "engineering plastics",
                "carbon fiber",
            ]
        )
    return list(dict.fromkeys(term.strip() for term in terms if term and term.strip()))


def plan_or_candidate_mentions_robotics(
    candidate: CandidateCompany, plan: TopicDiscoveryPlan | None = None
) -> bool:
    parts = [
        candidate.segment,
        candidate.rationale,
        *candidate.evidence_keywords,
    ]
    if plan:
        for subtopic in plan.subtopics:
            parts.extend(
                [
                    subtopic.name,
                    subtopic.rationale,
                    subtopic.objective,
                    *subtopic.required_evidence,
                    *subtopic.risk_focus,
                ]
            )
    text = " ".join(part for part in parts if part).lower()
    return any(term in text for term in ["機器人", "robot", "robotics", "automation", "自動化", "agv"])


def context_phrases(text: str) -> list[str]:
    if not text:
        return []
    normalized = re.sub(r"[，,。；;：:（）()、/|與及和]+", " ", text)
    parts = [part.strip() for part in normalized.split() if len(part.strip()) >= 2]
    phrases = [text.strip()]
    phrases.extend(parts)
    return phrases


def has_entity_and_context(haystack: str, entity_terms: list[str], context_terms: list[str]) -> bool:
    normalized = haystack.lower()
    has_entity = any(contains_entity_term(normalized, term) for term in entity_terms)
    if not has_entity:
        return False
    if not context_terms:
        return True
    return any(term and term.lower() in normalized for term in context_terms)


def has_entity_and_context_nearby(
    haystack: str,
    entity_terms: list[str],
    context_terms: list[str],
    window: int = 900,
) -> bool:
    normalized = haystack.lower()
    entity_positions = term_positions(normalized, entity_terms)
    if not entity_positions:
        return False
    if not context_terms:
        return True
    context_positions = term_positions(normalized, context_terms)
    if not context_positions:
        return False
    if len(normalized) <= 1500:
        return True
    return any(abs(entity - context) <= window for entity in entity_positions for context in context_positions)


def document_supports_candidate(
    document: NewsDocument,
    entity_terms: list[str],
    context_terms: list[str],
    relax_context_for_entity_match: bool = False,
) -> bool:
    haystack = f"{document.title}\n{document.text}"
    metadata_match = document_entity_metadata_match(document, entity_terms)
    if metadata_match is False:
        return False
    owner_ticker = company_filing_owner_ticker(document)
    if owner_ticker:
        ticker_terms = {term for term in entity_terms if term.isdigit()}
        if ticker_terms and owner_ticker not in ticker_terms:
            return False
    if metadata_match is True:
        normalized = haystack.lower()
        if context_terms and not has_context_term(normalized, context_terms):
            if not relax_context_for_entity_match:
                return False
    else:
        if not has_entity_and_context_nearby(haystack, entity_terms, context_terms):
            return False
    if not looks_like_unrelated_release_document(document):
        return True
    named_terms = [term for term in entity_terms if term and not term.isdigit()]
    normalized = haystack.lower()
    return any(contains_entity_term(normalized, term) for term in named_terms)


def document_entity_metadata_match(document: NewsDocument, entity_terms: list[str]) -> bool | None:
    entity_tickers = {str(ticker) for ticker in document.entity_tickers if str(ticker)}
    ticker_terms = {str(term) for term in entity_terms if str(term).isdigit()}
    if not entity_tickers or not ticker_terms:
        return None
    return bool(entity_tickers & ticker_terms)


def has_context_term(normalized_haystack: str, context_terms: list[str]) -> bool:
    return any(term and term.lower() in normalized_haystack for term in context_terms)


def term_positions(haystack: str, terms: list[str]) -> list[int]:
    positions: list[int] = []
    for term in terms:
        normalized_term = (term or "").lower()
        if not normalized_term:
            continue
        positions.extend(alias_positions(haystack, normalized_term))
    return positions


def contains_entity_term(haystack: str, term: str) -> bool:
    return alias_matches_text(haystack, term) if term else False


def looks_like_unrelated_release_document(document: NewsDocument) -> bool:
    haystack = " ".join(
        [
            document.title,
            document.source.title or "",
            document.source.publisher or "",
            document.source.url or "",
        ]
    ).lower()
    release_markers = (
        "google cloud release notes",
        "release notes",
        "changelog",
        "版本資訊",
        "更新日誌",
    )
    return any(marker in haystack for marker in release_markers)


def evidence_source_count(documents: list[NewsDocument]) -> int:
    sources = {
        (document.source.publisher or document.source.url or document.source.title or document.title).strip()
        for document in documents
        if (document.source.publisher or document.source.url or document.source.title or document.title).strip()
    }
    return len(sources)


def candidate_evidence_sources(documents: list[NewsDocument], limit: int = 5) -> list[dict]:
    sources = []
    seen = set()
    dated_documents = sorted(
        enumerate(documents),
        key=lambda pair: (pair[1].source.published_at or date.min, -pair[0]),
        reverse=True,
    )
    for _, document in dated_documents:
        source_key = (
            document.title,
            document.source.publisher,
            document.source.published_at.isoformat() if document.source.published_at else "",
        )
        if source_key in seen:
            continue
        seen.add(source_key)
        sources.append(
            {
                "title": document.title,
                "publisher": document.source.publisher or document.source.title or "",
                "published_at": document.source.published_at.isoformat() if document.source.published_at else None,
                "url": document.source.url,
            }
        )
        if len(sources) >= limit:
            break
    return sources


def candidate_evidence_confidence(documents: list[NewsDocument], source_count: int) -> dict:
    evidence_count = len(documents)
    dated_documents = [document for document in documents if document.source.published_at]
    latest_date = max((document.source.published_at for document in dated_documents), default=None)
    evidence_age_days = (today_taipei() - latest_date).days if latest_date else None
    evidence_stale = evidence_age_days is not None and evidence_age_days > STALE_CANDIDATE_EVIDENCE_DAYS
    credibility = summarize_source_credibility(documents)
    credibility_weight = float(credibility["average_weight"] or 0)
    evidence_score = min(evidence_count, 3) / 3 * 35
    source_score = min(source_count, 3) / 3 * 35
    timestamp_score = (len(dated_documents) / evidence_count * 10) if evidence_count else 0
    recency_score = recency_score_for_latest_date(latest_date)
    score = int(round(evidence_score + source_score + timestamp_score + recency_score))
    score = cap_confidence_by_source_credibility(score, credibility)
    return {
        "score": min(score, 100),
        "label": confidence_label(score),
        "source_credibility_score": int(round(credibility_weight * 100)),
        "source_credibility_label": source_credibility_label(credibility_weight),
        "source_credibility_counts": credibility["tier_counts"],
        "latest_evidence_date": latest_date.isoformat() if latest_date else None,
        "evidence_age_days": evidence_age_days,
        "evidence_stale": evidence_stale,
    }


def cap_confidence_by_source_credibility(score: int, credibility: dict) -> int:
    high_ratio = credibility.get("high_credibility_ratio")
    low_ratio = credibility.get("low_credibility_ratio")
    average_weight = float(credibility.get("average_weight") or 0)
    high_count = int(credibility.get("high_credibility_count") or 0)
    low_count = int(credibility.get("low_credibility_count") or 0)
    if low_count and high_count < 2:
        return min(score, 74)
    if low_count and low_ratio and low_ratio >= 0.34:
        return min(score, 84)
    if high_ratio == 0 and low_ratio and low_ratio >= 0.5:
        return min(score, 74)
    if high_ratio == 0:
        return min(score, 88)
    if average_weight < 0.65:
        return min(score, 74)
    if average_weight < 0.75:
        return min(score, 84)
    return score


def source_credibility_label(weight: float) -> str:
    if weight >= 0.85:
        return "高"
    if weight >= 0.65:
        return "中"
    if weight > 0:
        return "低"
    return "未分級"


def recency_score_for_latest_date(latest_date: date | None) -> int:
    if latest_date is None:
        return 0
    age_days = (today_taipei() - latest_date).days
    if age_days <= 30:
        return 20
    if age_days <= 90:
        return 12
    if age_days <= 180:
        return 6
    return 0


def confidence_label(score: int) -> str:
    return confidence_level(score)


def candidate_status(
    evidence_count: int,
    source_count: int,
    confidence_score: int = 0,
    evidence_stale: bool = False,
) -> str:
    if evidence_count == 0:
        return "needs_evidence"
    if evidence_stale:
        return "weak_evidence"
    if evidence_count >= 2 and source_count >= 2 and is_high_confidence(confidence_score):
        return "evidence_supported"
    return "weak_evidence"


def candidate_validation_reason(
    evidence_count: int,
    source_count: int,
    confidence_score: int = 0,
    latest_evidence_date: str | None = None,
    evidence_age_days: int | None = None,
    evidence_stale: bool = False,
) -> str:
    stale_note = ""
    if evidence_stale and latest_evidence_date:
        stale_note = (
            f"最新候選來源為 {latest_evidence_date}，距今約 {evidence_age_days} 天，"
            "已超過 180 天新鮮度門檻；"
        )
    if evidence_count >= 2 and source_count >= 2 and is_high_confidence(confidence_score):
        return (
            stale_note
            + "通過候選入選門檻：至少 2 篇公司主題證據、2 個以上來源，且入選支持度達高分；"
            "正式分析可信度仍需另看風險/機會歸因、財報、估值與公司文件。"
        )
    if evidence_count >= 2 and source_count >= 2:
        return (
            stale_note
            + f"弱證據：篇數與來源數達標，但入選支持度只有 {confidence_score} 分，需補近期或有日期來源。"
        )
    if evidence_count > 0:
        return (
            stale_note
            + f"弱證據：目前只有 {evidence_count} 篇、{source_count} 個來源，避免單一來源造成誤判。"
        )
    return "待補證據：尚未找到公司實體與主題上下文同時成立的來源。"


def candidate_next_action(
    evidence_count: int,
    source_count: int,
    confidence_score: int = 0,
    evidence_stale: bool = False,
) -> str:
    if evidence_stale:
        return "優先補抓最近 180 天內官方公告、法說會、月營收與公司新聞後再驗證。"
    if evidence_count >= 2 and source_count >= 2 and is_high_confidence(confidence_score):
        return "納入正式分析。"
    if evidence_count >= 2 and source_count >= 2:
        return "補抓有日期、近期且不同發布者的公司與主題來源後再驗證。"
    if evidence_count > 0:
        return "補抓公司新聞、法說會、月營收與國際供應鏈資料後再驗證。"
    return "用公司名稱、代號、產業位置與主題關鍵字重新補抓來源。"
