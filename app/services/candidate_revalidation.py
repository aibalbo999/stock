from __future__ import annotations

from collections.abc import Callable

from app.data_sources.company_filing_discovery import (
    REQUIRED_CORE_DOCUMENT_TYPES,
    filing_quality_score,
)
from app.db.session import session_scope
from app.models.schemas import NewsDocument
from app.services.candidate_audit import (
    STALE_CANDIDATE_EVIDENCE_DAYS,
    candidate_evidence_age_days,
    dedupe_reason_fragments,
)
from app.services.company_filing_repository import CompanyFilingRepository
from app.services.news_repository import NewsRepository
from app.services.source_quality import (
    filter_formal_evidence_documents,
    is_formal_evidence_source,
)
from app.services.topic_discovery import TopicDiscoveryService
from app.services.topic_discovery_models import TopicDiscoveryPlan
from app.services.whitelist import SupplyChainWhitelist


class CandidateRevalidationService:
    def __init__(
        self,
        session_scope_factory: Callable = session_scope,
        news_repository_cls=NewsRepository,
        company_filing_repository_cls=CompanyFilingRepository,
        topic_discovery_service_cls=TopicDiscoveryService,
        whitelist_cls=SupplyChainWhitelist,
    ) -> None:
        self.session_scope_factory = session_scope_factory
        self.news_repository_cls = news_repository_cls
        self.company_filing_repository_cls = company_filing_repository_cls
        self.topic_discovery_service_cls = topic_discovery_service_cls
        self.whitelist_cls = whitelist_cls

    def sufficient_company_filing_tickers(self, tickers: list[str]) -> set[str]:
        if not tickers:
            return set()
        with self.session_scope_factory() as session:
            documents = self.company_filing_repository_cls(session).latest_by_tickers(
                tickers,
                limit_per_ticker=8,
            )
        high_quality_types_by_ticker: dict[str, set[str]] = {ticker: set() for ticker in tickers}
        company_names = {
            company.ticker: company.name for company in self.whitelist_cls().companies()
        }
        for document in documents:
            if (
                filing_quality_score(
                    document, document.ticker, company_names.get(document.ticker, "")
                )
                >= 70
            ):
                high_quality_types_by_ticker.setdefault(document.ticker, set()).add(
                    document.document_type
                )
        return {
            ticker
            for ticker in tickers
            if all(
                document_type in high_quality_types_by_ticker.get(ticker, set())
                for document_type in REQUIRED_CORE_DOCUMENT_TYPES
            )
        }

    def apply_company_filing_gate_to_candidate_payload(self, candidates: list[dict]) -> list[dict]:
        return apply_company_filing_gate_to_candidate_payload(
            candidates,
            sufficient_tickers_provider=self.sufficient_company_filing_tickers,
        )

    def revalidate_candidate_whitelist(
        self,
        run_payload: dict,
        fallback_candidates: list[dict],
        limit: int = 500,
    ) -> dict:
        if not fallback_candidates:
            return {
                "candidate_whitelist": [],
                "promoted_tickers": [],
                "newly_promoted": [],
                "no_longer_promoted": [],
                "status_changes": [],
                "changed": False,
            }
        plan_payload = (run_payload.get("discovery") or {}).get("plan") or {
            "subtopics": [],
            "candidate_companies": fallback_candidates,
        }
        plan = TopicDiscoveryPlan.model_validate(plan_payload)
        topic = (
            (run_payload.get("request") or {}).get("topic") or run_payload.get("topic") or ""
        ).strip()
        queries = candidate_revalidation_queries(plan, topic)
        with self.session_scope_factory() as session:
            repository = self.news_repository_cls(session)
            documents = collect_revalidation_documents(repository, queries, limit)
            candidate_tickers = [
                candidate.get("ticker")
                for candidate in fallback_candidates
                if candidate.get("ticker")
            ]
            filing_documents = [
                self.company_filing_repository_cls.to_news_document(document)
                for document in self.company_filing_repository_cls(session).latest_by_tickers(
                    candidate_tickers,
                    limit_per_ticker=4,
                )
            ]
        documents = dedupe_documents([*filing_documents, *documents])[:limit]
        candidates = self.topic_discovery_service_cls().validate_candidates(plan, documents)
        candidate_payload = self.apply_company_filing_gate_to_candidate_payload(
            [candidate.model_dump() for candidate in candidates]
        )
        candidate_payload = mark_unavailable_candidates_after_revalidation(
            candidate_payload, len(documents)
        )
        candidate_payload = preserve_previous_supported_candidates(
            candidate_payload, fallback_candidates
        )
        candidate_payload = sanitize_candidate_low_quality_sources(candidate_payload)
        promoted_tickers = [
            candidate["ticker"]
            for candidate in candidate_payload
            if candidate["status"] == "evidence_supported"
        ]
        previous_promoted = {
            candidate.get("ticker")
            for candidate in fallback_candidates
            if candidate.get("status") == "evidence_supported"
        }
        previous_statuses = {
            candidate.get("ticker"): candidate.get("status")
            for candidate in fallback_candidates
            if candidate.get("ticker")
        }
        current_statuses = {
            candidate.get("ticker"): candidate.get("status")
            for candidate in candidate_payload
            if candidate.get("ticker")
        }
        promoted_set = set(promoted_tickers)
        newly_promoted = sorted(promoted_set - previous_promoted)
        no_longer_promoted = sorted(previous_promoted - promoted_set)
        status_changes = [
            {
                "ticker": ticker,
                "previous_status": previous_statuses.get(ticker),
                "current_status": current_status,
            }
            for ticker, current_status in sorted(current_statuses.items())
            if previous_statuses.get(ticker) != current_status
        ]
        return {
            "candidate_whitelist": candidate_payload,
            "promoted_tickers": promoted_tickers,
            "document_query_count": len(queries),
            "document_count": len(documents),
            "company_filing_document_count": len(filing_documents),
            "newly_promoted": newly_promoted,
            "no_longer_promoted": no_longer_promoted,
            "status_changes": status_changes,
            "changed": bool(newly_promoted or no_longer_promoted or status_changes),
        }

    def persist_candidate_entity_matches(
        self,
        plan: TopicDiscoveryPlan,
        candidates: list,
        documents: list[NewsDocument],
    ) -> dict:
        candidate_lookup = {
            candidate.ticker: candidate
            for candidate in candidates
            if getattr(candidate, "evidence_count", 0) > 0
        }
        if not candidate_lookup or not documents:
            return {"updated_documents": 0, "matches_added": 0}

        service = self.topic_discovery_service_cls()
        updated_documents = 0
        matches_added = 0
        with self.session_scope_factory() as session:
            repository = self.news_repository_cls(session)
            for document in documents:
                dynamic_matches = []
                for plan_candidate in plan.candidate_companies:
                    candidate = candidate_lookup.get(plan_candidate.ticker)
                    if candidate is None:
                        continue
                    if not service._document_supports_candidate(
                        document,
                        service._candidate_entity_terms(plan_candidate),
                        service._candidate_context_terms(plan_candidate),
                    ):
                        continue
                    dynamic_matches.append(
                        {
                            "ticker": plan_candidate.ticker,
                            "name": plan_candidate.name,
                            "segment_id": f"dynamic_{plan_candidate.ticker}",
                            "segment_name": plan_candidate.segment,
                            "matched_alias": plan_candidate.name,
                        }
                    )
                if dynamic_matches:
                    repository.upsert_document_merging_matches(document, dynamic_matches)
                    updated_documents += 1
                    matches_added += len(dynamic_matches)
        return {"updated_documents": updated_documents, "matches_added": matches_added}


def apply_company_filing_gate_to_candidate_payload(
    candidates: list[dict],
    sufficient_tickers_provider: Callable[[list[str]], set[str]] | None = None,
) -> list[dict]:
    candidates = sanitize_candidate_low_quality_sources(candidates)
    supported_tickers = [
        str(candidate.get("ticker") or "")
        for candidate in candidates
        if candidate.get("status") == "evidence_supported"
    ]
    sufficient_tickers = (
        sufficient_tickers_provider(supported_tickers)
        if sufficient_tickers_provider
        else CandidateRevalidationService().sufficient_company_filing_tickers(supported_tickers)
    )
    gated = []
    for candidate in candidates:
        row = dict(candidate)
        ticker = str(row.get("ticker") or "")
        if (
            row.get("status") == "evidence_supported"
            and ticker not in sufficient_tickers
            and not _candidate_can_skip_company_filing_gate(row)
        ):
            reason = row.get("validation_reason") or "通過新聞與市場證據門檻"
            row["status"] = "weak_evidence"
            row["promotion_eligible"] = False
            row["evidence_confidence_score"] = min(
                int(row.get("evidence_confidence_score") or 0), 74
            )
            row["evidence_confidence_label"] = "中"
            row["validation_reason"] = (
                f"{reason}；系統尚未取得或解析到可用官方年報/法說文字，先降回候選觀察；"
                "這是資料管線缺口，不代表公司沒有公開年報。"
            )
            row["next_action"] = "補抓或匯入官方年報、法說會或公司 IR 文字版後再升格為正式分析。"
        gated.append(row)
    return gated


def _candidate_can_skip_company_filing_gate(candidate: dict) -> bool:
    segment = str(candidate.get("segment") or "")
    name = str(candidate.get("name") or "")
    ticker = str(candidate.get("ticker") or "")
    memory_markers = ("記憶體", "DRAM", "NAND", "NOR Flash", "SSD", "Flash")
    if not any(marker.lower() in f"{segment} {name}".lower() for marker in memory_markers):
        return False
    if int(candidate.get("evidence_count") or 0) < 2:
        return False
    if int(candidate.get("evidence_source_count") or 0) < 2:
        return False
    if int(candidate.get("evidence_confidence_score") or 0) < 74:
        return False
    return ticker in {"2408", "2344", "8299", "2451", "3260", "4967", "2337", "8150"}


def sanitize_candidate_low_quality_sources(candidates: list[dict]) -> list[dict]:
    sanitized = []
    for candidate in candidates:
        row = dict(candidate)
        raw_sources = row.get("evidence_sources") or []
        evidence_sources = raw_sources if isinstance(raw_sources, list) else []
        formal_sources = [
            source for source in evidence_sources if _candidate_source_is_formal(source)
        ]
        removed_count = len(evidence_sources) - len(formal_sources)
        raw_titles = row.get("evidence_titles") or []
        evidence_titles = raw_titles if isinstance(raw_titles, list) else []
        formal_titles = [
            title for title in evidence_titles if is_formal_evidence_source(title=title, text=title)
        ]
        removed_title_count = len(evidence_titles) - len(formal_titles)
        if removed_title_count:
            row["evidence_titles"] = formal_titles
        if removed_count:
            row["evidence_sources"] = formal_sources
            row["low_quality_source_removed_count"] = (
                int(row.get("low_quality_source_removed_count") or 0) + removed_count
            )
            existing_evidence_count = int(row.get("evidence_count") or 0)
            if existing_evidence_count <= len(evidence_sources):
                row["evidence_count"] = min(existing_evidence_count, len(formal_sources))
            formal_source_count = len(
                {
                    str(source.get("publisher") or source.get("url") or source.get("title") or "")
                    for source in formal_sources
                    if isinstance(source, dict)
                }
            )
            existing_source_count = int(row.get("evidence_source_count") or 0)
            if existing_source_count <= len(evidence_sources):
                row["evidence_source_count"] = min(existing_source_count, formal_source_count)
            if row.get("status") == "evidence_supported" and (
                int(row.get("evidence_count") or 0) < 2
                or int(row.get("evidence_source_count") or 0) < 2
            ):
                row["status"] = "weak_evidence"
                row["promotion_eligible"] = False
                row["evidence_confidence_score"] = min(
                    int(row.get("evidence_confidence_score") or 0), 74
                )
                row["evidence_confidence_label"] = "中"
                reason = row.get("validation_reason") or "原始候選證據含低品質來源"
                row["validation_reason"] = dedupe_reason_fragments(
                    f"{reason}；剔除投資網誌、社群或散戶論壇來源後，正式證據不足 2 篇或 2 個來源，"
                    "先降回候選觀察，不得進入配置。"
                )
                row["next_action"] = "補抓公司公告、法說會、年報或主流財經新聞後再重新升格。"
            else:
                reason = row.get("validation_reason") or ""
                row["validation_reason"] = dedupe_reason_fragments(
                    f"{reason}；已剔除投資網誌、社群或散戶論壇來源，不列入信心與配置評估。"
                )
        elif removed_title_count:
            row["low_quality_source_removed_count"] = (
                int(row.get("low_quality_source_removed_count") or 0) + removed_title_count
            )
            reason = row.get("validation_reason") or ""
            row["validation_reason"] = dedupe_reason_fragments(
                f"{reason}；已剔除投資網誌、社群或散戶論壇標題，不列入信心與配置評估。"
            )
        sanitized.append(row)
    return sanitized


def _candidate_source_is_formal(source: object) -> bool:
    if not isinstance(source, dict):
        return is_formal_evidence_source(text=str(source))
    return is_formal_evidence_source(
        title=source.get("title"),
        publisher=source.get("publisher"),
        url=source.get("url"),
        source_title=source.get("source_title"),
        text=source.get("text"),
    )


def preserve_previous_supported_candidates(
    current_candidates: list[dict],
    previous_candidates: list[dict],
) -> list[dict]:
    current_by_ticker = {
        candidate.get("ticker"): dict(candidate)
        for candidate in current_candidates
        if candidate.get("ticker")
    }
    previous_supported = {
        candidate.get("ticker"): candidate
        for candidate in previous_candidates
        if candidate.get("ticker") and candidate.get("status") == "evidence_supported"
    }
    for ticker, previous in previous_supported.items():
        age_days = candidate_evidence_age_days(previous)
        if age_days is not None and age_days > STALE_CANDIDATE_EVIDENCE_DAYS:
            continue
        current = current_by_ticker.get(ticker)
        if current and current.get("status") == "evidence_supported":
            continue
        restored = dict(previous)
        reason = dedupe_reason_fragments(
            restored.get("validation_reason") or "上一版已通過正式分析門檻"
        )
        restored["validation_reason"] = dedupe_reason_fragments(
            f"{reason}；本次補強重驗證未穩定重建既有正式證據，先保留上一版正式分析，"
            "後續再用更多公司層級來源確認是否調整。"
        )
        restored["next_action"] = (
            restored.get("next_action") or "持續補抓公司層級來源與官方文件，確認是否維持正式分析。"
        )
        current_by_ticker[ticker] = restored
    ordered = []
    seen = set()
    for candidate in current_candidates:
        ticker = candidate.get("ticker")
        if ticker in current_by_ticker and ticker not in seen:
            ordered.append(current_by_ticker[ticker])
            seen.add(ticker)
    for ticker, candidate in current_by_ticker.items():
        if ticker not in seen:
            ordered.append(candidate)
    return ordered


def mark_unavailable_candidates_after_revalidation(
    candidates: list[dict], document_count: int
) -> list[dict]:
    if document_count < 200:
        return candidates
    updated = []
    for candidate in candidates:
        row = dict(candidate)
        status = row.get("status")
        evidence_count = int(row.get("evidence_count") or 0)
        if status == "needs_evidence" and evidence_count <= 0:
            row["status"] = "evidence_unavailable"
            row["promotion_eligible"] = False
            row["validation_reason"] = (
                f"已自動補查 {document_count} 份近期與公司層級資料，仍找不到公司實體與主題上下文同時成立的公開來源；"
                "暫時排除正式分析，避免用題材聯想替代證據。"
            )
            row["next_action"] = "等公司公告、法說會、年報或可信新聞出現直接證據後再重新納入候選。"
        elif status == "weak_evidence":
            row["status"] = "evidence_limited"
            row["promotion_eligible"] = False
            row["validation_reason"] = (
                f"已自動補查 {document_count} 份近期與公司層級資料，仍未達正式分析門檻；"
                f"目前只有 {evidence_count} 篇、{int(row.get('evidence_source_count') or 0)} 個來源，"
                "或缺少足夠近期/官方佐證，先列為補查完成但未升格。"
            )
            row["next_action"] = "後續只有在新增公司公告、法說會、年報或多來源新聞時才重新評估。"
        updated.append(row)
    return updated


def candidate_revalidation_queries(
    plan: TopicDiscoveryPlan, topic: str = "", limit: int = 80
) -> list[str]:
    queries = []
    for candidate in plan.candidate_companies:
        keywords = " ".join(candidate.evidence_keywords[:4])
        base_terms = " ".join(
            term
            for term in [topic, candidate.ticker, candidate.name, candidate.segment, keywords]
            if term
        )
        if base_terms:
            queries.append(base_terms)
        if candidate.name and candidate.segment:
            queries.append(f"{candidate.name} {candidate.segment}")
        if candidate.ticker and topic:
            queries.append(f"{candidate.ticker} {topic}")
    for subtopic in plan.subtopics:
        evidence_terms = " ".join(subtopic.required_evidence[:2])
        if subtopic.name or evidence_terms:
            queries.append(
                " ".join(term for term in [topic, subtopic.name, evidence_terms] if term)
            )
    return dedupe_strings(queries, limit)


def collect_revalidation_documents(
    repository: NewsRepository, queries: list[str], limit: int
) -> list:
    documents = []
    per_query_limit = max(10, min(40, limit // max(1, len(queries)))) if queries else limit
    for query in queries:
        documents.extend(repository.search_documents(query, limit=per_query_limit))
        if len(documents) >= limit * 2:
            break
    latest_documents = repository.latest_documents(limit)
    documents = [*documents, *latest_documents]
    return filter_formal_evidence_documents(dedupe_documents(documents))[:limit]


def dedupe_documents(documents: list) -> list:
    deduped = {}
    for document in documents:
        key = document.id or document.source.url or document.title
        deduped.setdefault(key, document)
    return list(deduped.values())


def dedupe_strings(values: list[str], limit: int) -> list[str]:
    deduped = []
    seen = set()
    for value in values:
        normalized = " ".join(str(value).split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
        if len(deduped) >= limit:
            break
    return deduped
