from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.time import today_taipei
from app.data_sources.company_filings import (
    CompanyFilingFetcher,
    REQUIRED_CORE_DOCUMENT_TYPES,
    filing_quality_score,
    filing_source_tier,
)
from app.data_sources.market import MarketDataClient, MarketFetchError
from app.data_sources.news import NewsFetcher, NewsSourceStore
from app.db.status import db_status
from app.db.session import init_db, session_scope
from app.models.schemas import ReportRequest, ReportResponse
from app.rag.vector_store import VectorStore
from app.services.candidate_audit import (
    candidate_audit_summary,
    dedupe_reason_fragments,
    render_candidate_audit_markdown,
)
from app.services.candidate_confidence import is_low_formal_confidence
from app.services.company_data_audit import audit_company_data, audit_report_company_data
from app.services.entity_mapping import EntityMapper
from app.services.followup_actions import (
    FollowUpActionPlanner,
    TRACKING_FRESHNESS_THRESHOLDS,
    company_filing_document_types_from_reason,
    execute_follow_up_actions,
    render_follow_up_actions_markdown,
    split_fresh_tracking_actions,
    summarize_follow_up_execution,
)
from app.services.ingestion import (
    IngestionPipeline,
    company_filing_attempt_result,
    company_filing_gap_summary,
    company_filing_next_actions,
    company_filing_ticker_result,
)
from app.services.persistence import (
    AnalysisRunRepository,
    CompanyFilingRepository,
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    NewsRepository,
    ReportRepository,
    ValuationMetricRepository,
)
from app.services.report_generator import ReportExecutionError, ReportGenerator, report_execution_summary
from app.services.report_quality import (
    attach_quality_gate_to_report,
    build_quality_gate_for_request,
    build_report_quality_gate,
    parse_quality_gate_from_markdown,
    summarize_document_source_quality,
    summarize_llm_status,
)
from app.services.llm_client import LLMClient
from app.services.schedule_config import ScheduleConfig, ScheduleConfigStore
from app.services.service_status import service_status
from app.services.source_relevance import SourceRelevanceAnalyzer
from app.services.topic_discovery import TopicDiscoveryPlan, TopicDiscoveryService
from app.services.whitelist import SupplyChainWhitelist
from app.tasks.celery_app import celery_app
from app.tasks.tasks import generate_report_task


LOGGER = logging.getLogger(__name__)


def serialize_run(run) -> dict:
    return {
        "id": run.id,
        "source": run.source,
        "status": run.status,
        "payload": run.payload_json,
        "report_id": run.report_id,
        "output_path": run.output_path,
        "error": run.error,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def latest_follow_up_run_for_report(repository: AnalysisRunRepository, report_id: int) -> dict | None:
    latest = getattr(repository, "latest", None)
    if not callable(latest):
        return None
    for run in latest(100):
        payload = parse_run_payload(run.payload_json)
        if run.source == "follow_up_api" and payload.get("source_report_id") == report_id:
            return {
                **serialize_run(run),
                "summary": payload.get("summary") or {},
                "planned_actions": payload.get("planned_actions") or [],
                "rerun_report": payload.get("rerun_report"),
            }
    return None


def sufficient_company_filing_tickers(tickers: list[str]) -> set[str]:
    if not tickers:
        return set()
    with session_scope() as session:
        documents = CompanyFilingRepository(session).latest_by_tickers(tickers, limit_per_ticker=8)
    high_quality_types_by_ticker: dict[str, set[str]] = {ticker: set() for ticker in tickers}
    company_names = {company.ticker: company.name for company in SupplyChainWhitelist().companies()}
    for document in documents:
        if filing_quality_score(document, document.ticker, company_names.get(document.ticker, "")) >= 70:
            high_quality_types_by_ticker.setdefault(document.ticker, set()).add(document.document_type)
    return {
        ticker
        for ticker in tickers
        if all(document_type in high_quality_types_by_ticker.get(ticker, set()) for document_type in REQUIRED_CORE_DOCUMENT_TYPES)
    }


def count_sufficient_company_filings(tickers: list[str]) -> int:
    return len(sufficient_company_filing_tickers(tickers))


def summarize_candidate_support_payload(candidates: list[dict]) -> dict:
    total = len(candidates)
    supported = sum(1 for candidate in candidates if candidate.get("status") == "evidence_supported")
    weak = sum(1 for candidate in candidates if candidate.get("status") == "weak_evidence")
    unsupported = sum(1 for candidate in candidates if candidate.get("status") == "needs_evidence")
    unavailable = sum(1 for candidate in candidates if candidate.get("status") == "evidence_unavailable")
    limited = sum(1 for candidate in candidates if candidate.get("status") == "evidence_limited")
    supported_scores = [
        int(candidate.get("evidence_confidence_score") or 0)
        for candidate in candidates
        if candidate.get("status") == "evidence_supported"
    ]
    supported_ratio = supported / total if total else 0
    return {
        "total": total,
        "supported": supported,
        "weak": weak,
        "unsupported": unsupported,
        "unavailable": unavailable,
        "limited": limited,
        "supported_ratio": supported_ratio,
        "exploration_supported_ratio": supported_ratio,
        "formal_supported_ratio": 1.0 if supported else 0,
        "formal_confidence_avg": round(sum(supported_scores) / len(supported_scores), 1) if supported_scores else None,
        "formal_confidence_min": min(supported_scores) if supported_scores else None,
        "formal_low_confidence_count": sum(1 for score in supported_scores if is_low_formal_confidence(score)),
    }


def apply_company_filing_gate_to_candidate_payload(candidates: list[dict]) -> list[dict]:
    supported_tickers = [
        str(candidate.get("ticker") or "")
        for candidate in candidates
        if candidate.get("status") == "evidence_supported"
    ]
    sufficient_tickers = sufficient_company_filing_tickers(supported_tickers)
    gated = []
    for candidate in candidates:
        row = dict(candidate)
        ticker = str(row.get("ticker") or "")
        if row.get("status") == "evidence_supported" and ticker not in sufficient_tickers:
            reason = row.get("validation_reason") or "通過新聞與市場證據門檻"
            row["status"] = "weak_evidence"
            row["promotion_eligible"] = False
            row["evidence_confidence_score"] = min(int(row.get("evidence_confidence_score") or 0), 74)
            row["evidence_confidence_label"] = "中"
            row["validation_reason"] = (
                f"{reason}；系統尚未取得或解析到可用官方年報/法說文字，先降回候選觀察；"
                "這是資料管線缺口，不代表公司沒有公開年報。"
            )
            row["next_action"] = "補抓或匯入官方年報、法說會或公司 IR 文字版後再升格為正式分析。"
        gated.append(row)
    return gated


def safe_mark_run_failed(run_id: int, error: str) -> None:
    try:
        with session_scope() as session:
            repository = AnalysisRunRepository(session)
            if repository.get(run_id):
                repository.mark_failed(run_id, error)
    except Exception:
        return


def safe_update_run_success(run_id: int, payload: dict, report_id: int) -> bool:
    with session_scope() as session:
        repository = AnalysisRunRepository(session)
        if repository.get(run_id) is None:
            return False
        repository.update_payload(run_id, payload)
        repository.mark_success(run_id, report_id)
        return True


def request_from_report_record(topic: str, tickers: list[str], run_payload_json: str | None = None) -> ReportRequest:
    payload = parse_run_payload(run_payload_json)
    if payload:
        request_payload = payload.get("request") if isinstance(payload, dict) else None
        if isinstance(request_payload, dict):
            return ReportRequest.model_validate(request_payload)
    return ReportRequest(topic=topic, tickers=tickers)


def parse_run_payload(run_payload_json: str | None) -> dict:
    if not run_payload_json:
        return {}
    try:
        payload = json.loads(run_payload_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def candidate_audit_from_run_payload(payload: dict) -> list[dict]:
    candidates = payload.get("candidate_whitelist") or []
    return candidates if isinstance(candidates, list) else []


def append_candidate_audit_if_missing(markdown: str, candidates: list[dict], promoted_tickers: list[str]) -> str:
    if not candidates or "\n## 候選公司審計" in f"\n{markdown}":
        return markdown
    return (
        markdown.rstrip()
        + "\n\n## 候選公司審計\n"
        + render_candidate_audit_markdown(candidates, promoted_tickers)
    )


def load_report_follow_up_context(report_id: int) -> dict:
    with session_scope() as session:
        report = ReportRepository(session).get(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="report not found")
        run = AnalysisRunRepository(session).get_by_report_id(report_id)
        run_payload_json = run.payload_json if run is not None else None
        try:
            tickers = json.loads(report.tickers_json)
        except json.JSONDecodeError:
            tickers = []
        markdown = report.markdown
        topic = report.topic
        run_payload = parse_run_payload(run_payload_json)
        company_data_audit = audit_company_data(
            session,
            tickers,
            markdown=markdown,
            run_payload=run_payload,
        ) if tickers else {}
    request = request_from_report_record(topic, tickers, run_payload_json)
    candidates = candidate_audit_from_run_payload(run_payload)
    markdown = append_candidate_audit_if_missing(markdown, candidates, request.tickers)
    return {
        "request": request,
        "markdown": markdown,
        "quality_gate": parse_quality_gate_from_markdown(markdown) or {},
        "candidate_whitelist": candidates,
        "company_data_audit": company_data_audit,
        "source_audit": run_payload.get("source_audit") or {},
        "run_payload": run_payload,
    }


def candidate_audit_has_data_gaps(candidates: list[dict] | None) -> bool:
    return any(
        candidate.get("status") in {"weak_evidence", "needs_evidence", "evidence_unavailable"}
        for candidate in (candidates or [])
        if candidate.get("ticker")
    )


def should_require_candidate_audit_follow_up(
    quality_gate: dict,
    company_data_audit: dict,
    candidates: list[dict] | None = None,
) -> bool:
    if company_data_audit and company_data_audit.get("status") != "sufficient":
        return True
    if candidate_audit_has_data_gaps(candidates):
        return True
    if quality_gate.get("status") == "ready":
        return False
    metrics = quality_gate.get("metrics") or {}
    issue_text = "；".join(str(item) for item in [*(quality_gate.get("blockers") or []), *(quality_gate.get("warnings") or [])])
    source_only_gap = (
        bool(issue_text)
        and "主題拆解子題" in issue_text
        and not any(term in issue_text for term in ["缺少候選公司", "正式分析股票", "候選公司證據覆蓋率低於"])
    )
    if (
        source_only_gap
        and int(metrics.get("promoted_count") or 0) > 0
        and float(metrics.get("candidate_supported_ratio") or 0) >= 0.6
        and metrics.get("discovery_plan_status") == "ready"
    ):
        return False
    return True


def plan_quality_from_quality_gate(quality_gate: dict) -> dict | None:
    metrics = quality_gate.get("metrics") or {}
    status = metrics.get("discovery_plan_status")
    score = metrics.get("discovery_plan_score")
    if status is None and score is None:
        return None
    return {
        "status": status,
        "score": score,
    }


def can_rerun_candidate_revalidation_from_existing_evidence(context: dict, actions: list) -> bool:
    return bool(context.get("candidate_whitelist")) and any(
        action.action_type == "rerun_discovery"
        for action in actions
    )


def revalidate_candidate_whitelist(run_payload: dict, fallback_candidates: list[dict], limit: int = 500) -> dict:
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
    topic = ((run_payload.get("request") or {}).get("topic") or run_payload.get("topic") or "").strip()
    queries = candidate_revalidation_queries(plan, topic)
    with session_scope() as session:
        repository = NewsRepository(session)
        documents = collect_revalidation_documents(repository, queries, limit)
        candidate_tickers = [
            candidate.get("ticker")
            for candidate in fallback_candidates
            if candidate.get("ticker")
        ]
        filing_documents = [
            CompanyFilingRepository.to_news_document(document)
            for document in CompanyFilingRepository(session).latest_by_tickers(
                candidate_tickers,
                limit_per_ticker=4,
            )
        ]
    documents = dedupe_documents([*filing_documents, *documents])[:limit]
    candidates = TopicDiscoveryService().validate_candidates(plan, documents)
    candidate_payload = apply_company_filing_gate_to_candidate_payload(
        [candidate.model_dump() for candidate in candidates]
    )
    candidate_payload = mark_unavailable_candidates_after_revalidation(candidate_payload, len(documents))
    candidate_payload = preserve_previous_supported_candidates(candidate_payload, fallback_candidates)
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


def preserve_previous_supported_candidates(current_candidates: list[dict], previous_candidates: list[dict]) -> list[dict]:
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
        current = current_by_ticker.get(ticker)
        if current and current.get("status") == "evidence_supported":
            continue
        restored = dict(previous)
        reason = dedupe_reason_fragments(
            restored.get("validation_reason") or "上一版已通過正式分析門檻"
        )
        restored["validation_reason"] = (
            dedupe_reason_fragments(
                f"{reason}；本次補強重驗證未穩定重建既有正式證據，先保留上一版正式分析，"
                "後續再用更多公司層級來源確認是否調整。"
            )
        )
        restored["next_action"] = restored.get("next_action") or "持續補抓公司層級來源與官方文件，確認是否維持正式分析。"
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


def mark_unavailable_candidates_after_revalidation(candidates: list[dict], document_count: int) -> list[dict]:
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


def candidate_revalidation_queries(plan: TopicDiscoveryPlan, topic: str = "", limit: int = 80) -> list[str]:
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
            queries.append(" ".join(term for term in [topic, subtopic.name, evidence_terms] if term))
    return dedupe_strings(queries, limit)


def collect_revalidation_documents(repository: NewsRepository, queries: list[str], limit: int) -> list:
    documents = []
    per_query_limit = max(10, min(40, limit // max(1, len(queries)))) if queries else limit
    for query in queries:
        documents.extend(repository.search_documents(query, limit=per_query_limit))
        if len(documents) >= limit * 2:
            break
    latest_documents = repository.latest_documents(limit)
    documents = [*documents, *latest_documents]
    return dedupe_documents(documents)[:limit]


def dedupe_documents(documents: list) -> list:
    deduped = {}
    for document in documents:
        key = document.id or document.source.url or document.title
        deduped.setdefault(key, document)
    return list(deduped.values())


def persist_candidate_entity_matches(
    plan: TopicDiscoveryPlan,
    candidates: list,
    documents: list,
) -> dict:
    candidate_lookup = {
        candidate.ticker: candidate
        for candidate in candidates
        if getattr(candidate, "evidence_count", 0) > 0
    }
    if not candidate_lookup or not documents:
        return {"updated_documents": 0, "matches_added": 0}

    service = TopicDiscoveryService()
    updated_documents = 0
    matches_added = 0
    with session_scope() as session:
        repository = NewsRepository(session)
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


async def prepare_follow_up_report_context(
    context: dict,
    request: ReportRequest,
    actions: list,
) -> dict:
    candidates = context.get("candidate_whitelist") or []
    should_revalidate = bool(candidates) and any(
        action.action_type in {"ingest_news", "rerun_discovery"} and action.purpose == "required"
        for action in actions
    )
    if should_revalidate:
        revalidation = revalidate_candidate_whitelist(context.get("run_payload") or {}, candidates)
        if not revalidation["promoted_tickers"] and request.tickers:
            candidate_payload = candidates
            promoted_tickers = request.tickers
            revalidation = {
                **revalidation,
                "candidate_whitelist": candidates,
                "promoted_tickers": request.tickers,
                "changed": False,
                "status_changes": [],
                "no_longer_promoted": [],
                "revalidation_status": "kept_previous_promotions",
                "revalidation_reason": "本次補強資料未能穩定重建候選證據，保留上一版正式分析清單並由資料品質門檻控管。",
            }
        else:
            candidate_payload = revalidation["candidate_whitelist"] or candidates
            promoted_tickers = revalidation["promoted_tickers"] or request.tickers
    else:
        revalidation = {
            "candidate_whitelist": candidates,
            "promoted_tickers": request.tickers,
            "newly_promoted": [],
            "no_longer_promoted": [],
            "status_changes": [],
            "changed": False,
        }
        candidate_payload = candidates
        promoted_tickers = request.tickers

    rerun_request = request.model_copy(update={"tickers": promoted_tickers})
    if revalidation.get("changed") and promoted_tickers:
        await refresh_market_data_for_report(rerun_request)
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(candidate_payload) if candidate_payload else None
    return {
        "request": rerun_request,
        "whitelist": whitelist,
        "candidate_whitelist": candidate_payload,
        "candidate_revalidation": revalidation,
    }


async def refresh_market_data_for_report(request: ReportRequest) -> dict:
    today = today_taipei()
    pipeline = IngestionPipeline()
    tickers = request.tickers
    return {
        "market": await pipeline.refresh_market(
            tickers,
            today - timedelta(days=max(request.lookback_days, 240)),
            today,
            filter_allowed=False,
        ),
        "monthly_revenue": await pipeline.refresh_monthly_revenue(
            tickers,
            today - timedelta(days=450),
            today,
            filter_allowed=False,
        ),
        "financial_metrics": await pipeline.refresh_financial_metrics(
            tickers,
            today - timedelta(days=365 * 6),
            today,
            filter_allowed=False,
        ),
        "valuations": await pipeline.refresh_valuations(
            tickers,
            today - timedelta(days=max(request.lookback_days, 30)),
            today,
            filter_allowed=False,
        ),
    }


def filter_follow_up_actions(actions: list, purpose: str) -> list:
    if purpose == "all":
        return actions
    selected = [action for action in actions if action.purpose == purpose]
    if selected and not any(action.action_type == "rerun_analysis" for action in selected):
        rerun = next((action for action in actions if action.action_type == "rerun_analysis"), None)
        if rerun is not None:
            selected.append(rerun)
    return selected


def follow_up_action_summary(actions: list) -> dict:
    required_count = sum(1 for action in actions if action.purpose == "required")
    tracking_count = sum(1 for action in actions if action.purpose == "tracking")
    return {
        "required_count": required_count,
        "tracking_count": tracking_count,
        "total_count": len(actions),
    }


def follow_up_plan_next_actions(actions: list) -> list[dict]:
    rows = []
    for action in actions:
        target = follow_up_plan_action_target(action)
        if target is None:
            continue
        rows.append(
            {
                "action": action.action_type,
                "tickers": list(action.tickers),
                "target": target,
                "priority": action.priority,
                "purpose": action.purpose,
                "reason": action.reason,
                "next_step": follow_up_plan_action_next_step(action),
                "completion_criteria": follow_up_plan_action_completion_criteria(action),
                "completion_checks": follow_up_plan_action_completion_checks(action),
            }
        )
    return rows


def follow_up_plan_action_target(action) -> str | None:
    if action.action_type == "ingest_company_filings":
        document_types = company_filing_document_types_from_reason(action.reason) or []
        return "、".join(document_types) if document_types else "公司公開文件"
    targets = {
        "ingest_news": "新聞/研究/產業證據",
        "refresh_market": "股價與量能",
        "refresh_monthly_revenue": "月營收",
        "refresh_financial_metrics": "五年財務資料",
        "refresh_valuations": "估值資料",
        "rerun_discovery": "AI 主題拆解與候選白名單",
        "rerun_analysis": "完整投資報告",
    }
    return targets.get(action.action_type)


def follow_up_plan_action_next_step(action) -> str:
    steps = {
        "ingest_news": "依股票與主題補抓設定回看區間內的多來源資料，補足公司層級證據。",
        "ingest_company_filings": "先自動搜尋官方/MOPS/IR 文件；若仍不足，系統會列出需人工匯入的文件。",
        "refresh_market": "刷新近 120 天股價、量能與波動資料，用於目前情境降值分與進出場檢查。",
        "refresh_monthly_revenue": "補齊近月營收序列，用於成長加速或轉弱判斷。",
        "refresh_financial_metrics": "補齊多年財報指標，用於財務體質、利潤率與負債檢查。",
        "refresh_valuations": "刷新本益比、股價淨值比與殖利率，用於同業估值比較。",
        "rerun_discovery": "重新拆解主題與候選公司，確認白名單是否需調整。",
        "rerun_analysis": "在補資料後重新產生報告；若仍有關鍵缺口，系統會先暫停重跑。",
    }
    return steps.get(action.action_type, "依任務設定補齊資料後再評估是否重跑報告。")


def follow_up_plan_action_completion_criteria(action) -> str:
    criteria = {
        "ingest_news": "每檔至少補到 2 個以上來源或足以支撐/排除產業鏈關聯的回看區間內證據。",
        "ingest_company_filings": "每檔至少有必要類型的高品質官方文件；若仍缺件，列入人工匯入清單。",
        "refresh_market": "目標股票近 120 天內有可用股價與量能資料。",
        "refresh_monthly_revenue": "目標股票至少取得近 12 個月月營收資料。",
        "refresh_financial_metrics": "目標股票取得足以做 5 年趨勢判斷的財務期數。",
        "refresh_valuations": "目標股票取得最新本益比、股價淨值比或可比較估值資料。",
        "rerun_discovery": "主題拆解、候選白名單與排除原因重新產出並通過基本品質檢查。",
        "rerun_analysis": "補強後無關鍵 blocker，才重新產生完整投資報告。",
    }
    return criteria.get(action.action_type, "補強結果可被資料審計或品質閘門確認。")


def follow_up_plan_action_completion_checks(action) -> list[dict]:
    if action.action_type == "ingest_company_filings":
        document_types = company_filing_document_types_from_reason(action.reason) or []
        return [
            {
                "check": "company_filing_quality",
                "required_document_types": document_types,
                "min_quality_score": 70,
                "min_documents_per_ticker": 1,
            }
        ]
    checks = {
        "ingest_news": [
            {"check": "company_evidence_sources", "min_sources_per_ticker": 2},
        ],
        "refresh_market": [
            {"check": "market_history_coverage", "min_days": 120},
        ],
        "refresh_monthly_revenue": [
            {"check": "monthly_revenue_coverage", "min_months": 12},
        ],
        "refresh_financial_metrics": [
            {"check": "financial_metric_coverage", "min_years": 5},
        ],
        "refresh_valuations": [
            {"check": "valuation_availability", "required_fields": ["pe_ratio", "pb_ratio"]},
        ],
        "rerun_discovery": [
            {"check": "candidate_revalidation_ready"},
        ],
        "rerun_analysis": [
            {"check": "quality_gate_no_blockers"},
        ],
    }
    return checks.get(action.action_type, [{"check": "manual_review"}])


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="台股 AI 產業鏈 RAG 分析系統",
    version="0.1.0",
    lifespan=lifespan,
)


class ManualNewsIngest(BaseModel):
    title: str
    text: str
    publisher: str = "manual"
    published_at: Optional[date] = None
    url: Optional[str] = None


class ManualCompanyFilingIngest(BaseModel):
    ticker: str
    title: str
    text: str
    company_name: str = ""
    document_type: str = "company_disclosure"
    publisher: str = "manual company filing"
    published_at: Optional[date] = None
    url: Optional[str] = None


class CompanyFilingUrlIngest(BaseModel):
    ticker: str
    url: str
    company_name: str = ""
    document_type: str = "company_disclosure"
    publisher: Optional[str] = None
    published_at: Optional[date] = None


class MarketRefreshRequest(BaseModel):
    tickers: list[str] = []
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class FeedFetchRequest(BaseModel):
    url: Optional[str] = None
    publisher: Optional[str] = None
    limit: int = 10
    enabled_sources_only: bool = True
    topic: Optional[str] = None


class MaintenanceCleanupRequest(BaseModel):
    failed_runs: bool = False
    orphan_report_refs: bool = False
    stale_running_before: Optional[datetime] = None
    runs_before: Optional[datetime] = None
    reports_before: Optional[datetime] = None


class FollowUpRunRequest(BaseModel):
    rerun_report: bool = True
    news_limit: int = 30
    purpose: Literal["all", "required", "tracking"] = "all"
    record_noop: bool = False
    force_refresh: bool = False


class TopicDiscoveryRequest(BaseModel):
    topic: str = "AI 產業鏈"
    limit_per_query: int = 5
    lookback_days: int = 14
    evidence_limit: int = 40
    analysis_mode: Literal["fast", "standard", "deep"] = "standard"
    deep_analysis: bool = False
    include_international: bool = True
    investor_capital: int = 1_000_000
    beginner_mode: bool = True
    investor_profile: str = "beginner"
    max_position_pct: float = 0.10
    cash_reserve_pct: float = 0.30


def merge_latest_by_ticker(tickers: list[str], fetched_items: list, cached_items: list, date_attr: str) -> list:
    merged = {}
    for item in [*cached_items, *fetched_items]:
        ticker = getattr(item, "ticker", "")
        if ticker not in tickers:
            continue
        current = merged.get(ticker)
        if current is None:
            merged[ticker] = item
            continue
        item_date = getattr(item, date_attr, None)
        current_date = getattr(current, date_attr, None)
        if current_date is None or (item_date is not None and item_date >= current_date):
            merged[ticker] = item
    return [merged[ticker] for ticker in tickers if ticker in merged]


def merge_financial_metric_history(fetched_metrics: list, cached_metrics: list) -> list:
    merged = {}
    for metric in [*cached_metrics, *fetched_metrics]:
        key = (
            getattr(metric, "ticker", ""),
            getattr(metric, "report_date", None),
            getattr(metric, "statement_type", ""),
            getattr(metric, "metric", ""),
        )
        merged[key] = metric
    return list(merged.values())


def discovery_analysis_mode(payload: TopicDiscoveryRequest) -> str:
    return "deep" if payload.deep_analysis else payload.analysis_mode


def is_deep_discovery(payload: TopicDiscoveryRequest) -> bool:
    return discovery_analysis_mode(payload) == "deep"


def discovery_fetch_settings(payload: TopicDiscoveryRequest) -> tuple[int, int, int]:
    limit_per_query = max(payload.limit_per_query, 8)
    evidence_limit = max(payload.evidence_limit, 80)
    mode = discovery_analysis_mode(payload)
    max_queries = 24 if mode == "fast" else 36
    if mode == "deep":
        limit_per_query = max(limit_per_query, 20)
        evidence_limit = max(evidence_limit, 180)
        max_queries = 24
    return limit_per_query, evidence_limit, max_queries


def discovery_effective_lookback_days(payload: TopicDiscoveryRequest) -> int:
    mode = discovery_analysis_mode(payload)
    if mode == "deep":
        return max(payload.lookback_days, 120)
    if mode == "standard":
        return max(payload.lookback_days, 60)
    return payload.lookback_days


def discovery_document_limit(payload: TopicDiscoveryRequest, evidence_limit: int) -> int:
    mode = discovery_analysis_mode(payload)
    if mode == "deep":
        return max(1000, evidence_limit * 5)
    if mode == "standard":
        return max(600, evidence_limit * 4)
    return max(300, evidence_limit * 3)


def discovery_market_history_days(payload: TopicDiscoveryRequest) -> int:
    return max(payload.lookback_days, 720) if is_deep_discovery(payload) else max(payload.lookback_days, 240)


def discovery_valuation_history_days(payload: TopicDiscoveryRequest) -> int:
    return max(payload.lookback_days, 180) if is_deep_discovery(payload) else max(payload.lookback_days, 30)


def should_revalidate_candidate_filings(candidates: list[dict], min_supported_ratio: float = 0.6) -> bool:
    if not candidates:
        return False
    supported = sum(1 for candidate in candidates if candidate.get("status") == "evidence_supported")
    return (supported / len(candidates)) < min_supported_ratio


def candidate_filing_revalidation_tickers(candidates: list[dict], payload: TopicDiscoveryRequest) -> list[str]:
    limit = 20 if is_deep_discovery(payload) else 12
    prioritized = [
        str(candidate.get("ticker"))
        for candidate in candidates
        if candidate.get("ticker") and candidate.get("status") != "evidence_supported"
    ]
    fallback = [str(candidate.get("ticker")) for candidate in candidates if candidate.get("ticker")]
    return list(dict.fromkeys([*prioritized, *fallback]))[:limit]


def market_timeout_errors(tickers: list[str], dataset: str, exc: Exception) -> list[MarketFetchError]:
    message = f"{dataset} fetch timed out or failed: {str(exc) or exc.__class__.__name__}"
    return [MarketFetchError(ticker=ticker, dataset=dataset, error=message) for ticker in tickers]


def company_filing_timeout_result(tickers: list[str], exc: Exception, source: str) -> dict:
    errors = [
        {
            "ticker": ticker,
            "company_name": "",
            "source": source,
            "error": str(exc) or exc.__class__.__name__,
            "category": "retryable_source_error",
        }
        for ticker in tickers
    ]
    per_ticker_results = [
        company_filing_ticker_result(
            ticker,
            "",
            [],
            ("annual_report",),
            [error],
            [company_filing_attempt_result(source, [], [error])],
        )
        for ticker, error in zip(tickers, errors)
    ]
    return {
        "requested_tickers": tickers,
        "stored_count": 0,
        "items": [],
        "errors": errors,
        "per_ticker_results": per_ticker_results,
        "missing_tickers": list(tickers),
        "gap_summary": company_filing_gap_summary(per_ticker_results),
        "next_actions": company_filing_next_actions(per_ticker_results),
        "source": f"{source} timed out",
    }


def summarize_ingestion_stage(results: list[dict]) -> dict:
    stored_count = 0
    error_count = 0
    sample_titles = []
    for result in results:
        stored_count += int(result.get("count") or 0)
        error_count += len(result.get("errors") or [])
        for item in result.get("items") or []:
            title = item.get("title") if isinstance(item, dict) else None
            if title and title not in sample_titles:
                sample_titles.append(title)
            if len(sample_titles) >= 8:
                break
    return {
        "source_runs": len(results),
        "stored_count": stored_count,
        "error_count": error_count,
        "sample_titles": sample_titles,
        "source_category_counts": summarize_source_categories(results),
        "source_intent_counts": summarize_source_intents(results),
        "source_selection": summarize_source_selection(results),
    }


def summarize_source_categories(results: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for result in results:
        for category, count in (result.get("source_category_counts") or {}).items():
            counts[str(category)] = counts.get(str(category), 0) + int(count or 0)
    return counts


def summarize_source_intents(results: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for result in results:
        for source_result in result.get("source_results") or []:
            stored_count = int(source_result.get("stored_count") or 0)
            for intent in source_result.get("source_intents") or []:
                counts[str(intent)] = counts.get(str(intent), 0) + stored_count
    return counts


def summarize_source_selection(results: list[dict]) -> dict:
    selected = []
    skipped = []
    for result in results:
        selection = result.get("source_selection") or {}
        selected.extend(selection.get("selected") or [])
        skipped.extend(selection.get("skipped") or [])
    return {
        "selected_count": len(selected),
        "skipped_count": len(skipped),
        "selected_sample": selected[:12],
        "skipped_sample": skipped[:12],
    }


def build_source_audit(
    payload: TopicDiscoveryRequest,
    urls: list[str],
    fixed_source_ingestion: dict,
    dynamic_query_ingestion: list[dict],
    limit_per_query: int,
    evidence_limit: int,
    max_queries: int,
    query_metadata: list[dict] | None = None,
) -> dict:
    dynamic_summary = summarize_ingestion_stage(dynamic_query_ingestion)
    fixed_summary = summarize_ingestion_stage([fixed_source_ingestion])
    query_metadata = query_metadata or []
    query_type_counts: dict[str, int] = {}
    query_intent_counts: dict[str, int] = {}
    for item in query_metadata:
        source_type = str(item.get("source_type") or "unknown")
        query_type_counts[source_type] = query_type_counts.get(source_type, 0) + 1
        source_intent = str(item.get("source_intent") or "unknown")
        query_intent_counts[source_intent] = query_intent_counts.get(source_intent, 0) + 1
    query_type_labels = {
        source_type: query_type_label(source_type)
        for source_type in query_type_counts
    }
    query_intent_labels = {
        source_intent: query_intent_label(source_intent)
        for source_intent in query_intent_counts
    }
    return {
        "topic": payload.topic,
        "lookback_days": payload.lookback_days,
        "effective_lookback_days": discovery_effective_lookback_days(payload),
        "analysis_mode": discovery_analysis_mode(payload),
        "deep_analysis": payload.deep_analysis,
        "include_international": payload.include_international,
        "limit_per_query": limit_per_query,
        "evidence_limit": evidence_limit,
        "max_queries": max_queries,
        "fixed_sources": fixed_summary,
        "dynamic_queries": dynamic_summary,
        "dynamic_query_count": len(urls),
        "dynamic_query_sample": urls[:10],
        "query_type_counts": query_type_counts,
        "query_intent_counts": query_intent_counts,
        "query_intent_labels": query_intent_labels,
        "query_type_labels": query_type_labels,
        "query_metadata_sample": query_metadata[:10],
        "total_stored_count": fixed_summary["stored_count"] + dynamic_summary["stored_count"],
        "total_error_count": fixed_summary["error_count"] + dynamic_summary["error_count"],
    }


def query_type_label(source_type: str) -> dict:
    labels = {
        "research_task": ("研究任務", "由拆解任務的目的、必查證據與風險焦點產生。"),
        "subtopic": ("子題查詢", "由 AI 原始子題搜尋 query 產生。"),
        "subtopic_international": ("子題國際查詢", "由子題 query 延伸的國際市場搜尋。"),
        "candidate": ("候選公司查詢", "用於驗證候選公司與主題證據是否同時存在。"),
        "candidate_international": ("候選公司國際查詢", "用於查核台股候選公司在國際供應鏈中的證據。"),
        "coverage_gap": ("缺口補強查詢", "系統依拆解品質缺口自動補上的搜尋。"),
        "query_quality_gap": ("查詢品質補強", "系統依籠統、未對齊或缺國際資料的 query 自動補上的搜尋。"),
        "international_context": ("國際背景查詢", "系統固定加入的國際供應鏈背景搜尋。"),
        "supplemental": ("補抓查詢", "第一次抓取後因證據不足自動追加的搜尋。"),
        "unknown": ("未分類查詢", "尚未分類的查詢來源。"),
    }
    label, description = labels.get(source_type, labels["unknown"])
    return {"label": label, "description": description}


def query_intent_label(source_intent: str) -> dict:
    labels = {
        "industry_news": ("產業新聞", "追蹤需求、供給、競爭與產業變化。"),
        "company_disclosure": ("公司公開資訊", "追蹤法說、年報、重大訊息與公司層級證據。"),
        "financial_metrics": ("財務資料", "追蹤營收、獲利、毛利、現金流與 ROE。"),
        "valuation": ("估值資料", "追蹤本益比、股價、同業估值與評價合理性。"),
        "capacity_supply": ("產能供給", "追蹤產能、良率、交期與供應鏈瓶頸。"),
        "regulatory_policy": ("政策法規", "追蹤出口管制、地緣政治、法規與政策變化。"),
        "international_context": ("國際脈絡", "追蹤海外需求、國際供應鏈與全球市場訊號。"),
        "early_signal": ("早期訊號", "追蹤報導較少、月營收或產能訊號正在轉強的長尾線索。"),
        "unknown": ("未分類意圖", "尚未分類的資料需求。"),
    }
    label, description = labels.get(source_intent, labels["unknown"])
    return {"label": label, "description": description}


def summarize_candidate_support(candidates) -> dict:
    total = len(candidates)
    supported = sum(1 for candidate in candidates if candidate.status == "evidence_supported")
    weak = sum(1 for candidate in candidates if candidate.status == "weak_evidence")
    unsupported = sum(1 for candidate in candidates if candidate.status == "needs_evidence")
    unavailable = sum(1 for candidate in candidates if candidate.status == "evidence_unavailable")
    limited = sum(1 for candidate in candidates if candidate.status == "evidence_limited")
    supported_scores = [
        int(candidate.evidence_confidence_score or 0)
        for candidate in candidates
        if candidate.status == "evidence_supported"
    ]
    exploration_supported_ratio = supported / total if total else 0
    return {
        "total": total,
        "supported": supported,
        "weak": weak,
        "unsupported": unsupported,
        "unavailable": unavailable,
        "limited": limited,
        "supported_ratio": exploration_supported_ratio,
        "exploration_supported_ratio": exploration_supported_ratio,
        "formal_supported_ratio": 1.0 if supported else 0,
        "formal_confidence_avg": round(sum(supported_scores) / len(supported_scores), 1) if supported_scores else None,
        "formal_confidence_min": min(supported_scores) if supported_scores else None,
        "formal_low_confidence_count": sum(1 for score in supported_scores if is_low_formal_confidence(score)),
    }


def should_supplement_discovery_sources(source_audit: dict, candidate_support: dict) -> bool:
    plan_quality = source_audit.get("plan_quality") or {}
    query_quality = plan_quality.get("query_quality") or {}
    if plan_quality and plan_quality.get("status") != "ready":
        return True
    if int(query_quality.get("generic_query_count") or 0) > 0:
        return True
    source_relevance = source_audit.get("source_relevance") or {}
    if int(source_relevance.get("missing_subtopic_count") or 0) > 0:
        return True
    if candidate_support["total"] == 0:
        return source_audit["dynamic_queries"]["stored_count"] < 8
    if candidate_support["supported_ratio"] < 0.6:
        return True
    return source_audit["dynamic_queries"]["stored_count"] < 12


def discovery_query_budget(max_queries: int, analysis_mode: str = "standard", deep_analysis: bool = False) -> dict:
    mode = "deep" if deep_analysis else analysis_mode
    settings = {
        "fast": {"initial_floor": 8, "initial_ratio": 0.65, "rounds": 1, "batch": 6, "no_gain_stop": 1},
        "standard": {"initial_floor": 12, "initial_ratio": 0.55, "rounds": 3, "batch": 10, "no_gain_stop": 2},
        "deep": {"initial_floor": 10, "initial_ratio": 0.55, "rounds": 2, "batch": 4, "no_gain_stop": 1},
    }.get(mode, {})
    initial_queries = max(settings.get("initial_floor", 12), int(max_queries * settings.get("initial_ratio", 0.55)))
    return {
        "initial_queries": min(max_queries, initial_queries),
        "supplemental_queries": max(0, max_queries - initial_queries),
        "supplemental_rounds": settings.get("rounds", 3),
        "supplemental_batch_size": settings.get("batch", 10),
        "no_gain_stop_rounds": settings.get("no_gain_stop", 2),
        "analysis_mode": mode,
    }


def should_escalate_discovery_budget(
    source_audit: dict,
    candidate_support: dict,
    current_budget: dict,
) -> bool:
    if current_budget.get("escalated"):
        return False
    if current_budget.get("analysis_mode") == "deep":
        return False
    plan_quality = source_audit.get("plan_quality") or {}
    source_relevance = source_audit.get("source_relevance") or {}
    if plan_quality.get("status") == "insufficient":
        return True
    if int(source_relevance.get("missing_subtopic_count") or 0) >= 2:
        return True
    if int(source_relevance.get("weak_subtopic_count") or 0) >= 3:
        return True
    if int(candidate_support.get("total") or 0) > 0 and float(candidate_support.get("supported_ratio") or 0) < 0.35:
        return True
    return False


def escalate_discovery_budget(budget: dict, max_queries: int) -> dict:
    supplemental_rounds = max(int(budget.get("supplemental_rounds") or 0), 5)
    supplemental_batch_size = max(int(budget.get("supplemental_batch_size") or 0), 12)
    initial_queries = int(budget.get("initial_queries") or 0)
    return {
        **budget,
        "analysis_mode": f"{budget.get('analysis_mode', 'standard')}_auto_escalated",
        "supplemental_rounds": supplemental_rounds,
        "supplemental_batch_size": supplemental_batch_size,
        "supplemental_queries": max(0, max_queries - initial_queries),
        "no_gain_stop_rounds": max(int(budget.get("no_gain_stop_rounds") or 0), 2),
        "escalated": True,
        "escalation_reason": "plan_or_source_coverage_gap",
    }


def source_selection_context(topic: str, plan: TopicDiscoveryPlan | None = None) -> str:
    terms = [topic]
    if plan:
        for subtopic in plan.subtopics:
            terms.extend(
                [
                    subtopic.name,
                    subtopic.objective,
                    " ".join(subtopic.required_evidence[:3]),
                    " ".join(subtopic.risk_focus[:3]),
                    " ".join(subtopic.source_intents[:3]),
                ]
            )
        for candidate in plan.candidate_companies:
            terms.extend([candidate.name, candidate.segment, " ".join(candidate.evidence_keywords[:4])])
    return " ".join(term for term in terms if term)


async def ingest_dynamic_news_urls(
    urls: list[str],
    limit_per_query: int,
    start_date: date,
    end_date: date,
) -> list[dict]:
    if not urls:
        return []

    fetch_limit = limit_per_query * 4
    semaphore = asyncio.Semaphore(6)
    fetcher = NewsFetcher()

    async def fetch_one(url: str) -> dict:
        async with semaphore:
            documents = []
            errors = []
            try:
                fetched = await asyncio.wait_for(
                    fetcher.fetch_feed(url, publisher=None, limit=fetch_limit),
                    timeout=10,
                )
                documents = IngestionPipeline._filter_documents(
                    fetched,
                    start_date,
                    end_date,
                    quality_filter=True,
                )[:limit_per_query]
            except Exception as exc:
                errors.append({"source": url, "error": str(exc) or exc.__class__.__name__})
            return {"url": url, "documents": documents, "errors": errors}

    fetched_results = await asyncio.gather(*(fetch_one(url) for url in urls))
    all_documents = IngestionPipeline._dedupe_documents(
        [
            document
            for result in fetched_results
            for document in result["documents"]
        ]
    )
    matches_by_id = {}
    if all_documents:
        mapper = EntityMapper()
        VectorStore().upsert_documents(all_documents)
        with session_scope() as session:
            repository = NewsRepository(session)
            for document in all_documents:
                matches = mapper.match_document(document)
                matches_payload = [match.model_dump(mode="json") for match in matches]
                repository.upsert_document(document, matches_payload)
                matches_by_id[document.id] = matches_payload

    ingestion_results = []
    for result in fetched_results:
        documents = IngestionPipeline._dedupe_documents(result["documents"])
        ingested = [
            {
                "id": document.id,
                "title": document.title,
                "publisher": document.source.publisher,
                "published_at": document.source.published_at.isoformat()
                if document.source.published_at
                else None,
                "entity_matches": matches_by_id.get(document.id, []),
            }
            for document in documents
        ]
        ingestion_results.append(
            {
                "count": len(ingested),
                "items": ingested,
                "errors": result["errors"],
                "source_results": [],
                "source_category_counts": {},
                "source_selection": {
                    "mode": "single_url",
                    "selected_count": 1,
                    "available_count": 1,
                },
            }
        )
    return ingestion_results


async def run_topic_discovery_ingestion(
    payload: TopicDiscoveryRequest,
    service: TopicDiscoveryService,
    plan: TopicDiscoveryPlan,
    limit_per_query: int,
    evidence_limit: int,
    max_queries: int,
    document_limit: int,
) -> dict:
    budget = discovery_query_budget(
        max_queries,
        analysis_mode=discovery_analysis_mode(payload),
        deep_analysis=payload.deep_analysis,
    )
    plan_quality = service.evaluate_plan_quality(plan)
    query_metadata = service.google_news_urls(
        plan,
        include_international=payload.include_international,
        max_urls=budget["initial_queries"],
        topic=payload.topic,
        include_metadata=True,
    )
    urls = [item["url"] for item in query_metadata]
    end_date = today_taipei()
    lookback_days = discovery_effective_lookback_days(payload)
    start_date = end_date - timedelta(days=lookback_days)
    fixed_source_ingestion = await IngestionPipeline().ingest_feeds(
        enabled_sources_only=True,
        topic=source_selection_context(payload.topic, plan),
        limit=limit_per_query,
        start_date=start_date,
        end_date=end_date,
    )
    dynamic_query_ingestion = await ingest_dynamic_news_urls(
        urls,
        limit_per_query,
        start_date,
        end_date,
    )
    remediation_rounds = []
    no_gain_rounds = 0
    remediation_stop_reason = "coverage_sufficient"
    candidates = []
    candidate_support = {"total": 0, "supported": 0, "weak": 0, "unsupported": 0, "supported_ratio": 0}
    source_audit = build_source_audit(
        payload,
        urls,
        fixed_source_ingestion,
        dynamic_query_ingestion,
        limit_per_query,
        evidence_limit,
        max_queries,
        query_metadata,
    )
    source_audit["plan_quality"] = plan_quality.model_dump()

    for round_index in range(budget["supplemental_rounds"] + 1):
        with session_scope() as session:
            documents = NewsRepository(session).latest_documents(limit=max(document_limit, evidence_limit))
        documents = IngestionPipeline._filter_documents(
            documents,
            start_date,
            end_date,
            quality_filter=True,
        )
        candidates = service.validate_candidates(plan, documents)
        source_relevance = SourceRelevanceAnalyzer(service).analyze(plan, documents, limit=document_limit)
        dynamic_entity_backfill = persist_candidate_entity_matches(plan, candidates, documents)
        candidate_support = summarize_candidate_support(candidates)
        source_audit = build_source_audit(
            payload,
            urls,
            fixed_source_ingestion,
            dynamic_query_ingestion,
            limit_per_query,
            evidence_limit,
            max_queries,
            query_metadata,
        )
        source_audit["plan_quality"] = plan_quality.model_dump()
        source_audit["source_relevance"] = source_relevance
        if should_escalate_discovery_budget(source_audit, candidate_support, budget):
            budget = escalate_discovery_budget(budget, max_queries)
        if not should_supplement_discovery_sources(source_audit, candidate_support):
            remediation_stop_reason = "coverage_sufficient"
            break
        remaining_queries = max_queries - len(urls)
        if remaining_queries <= 0 or round_index >= budget["supplemental_rounds"]:
            remediation_stop_reason = "query_budget_exhausted"
            break
        supplemental_metadata = service.supplemental_google_news_query_metadata(
            plan,
            candidates,
            include_international=payload.include_international,
            max_urls=min(remaining_queries, budget["supplemental_batch_size"]),
            existing_urls=urls,
            missing_subtopics=service.missing_subtopic_names(source_relevance),
        )
        supplemental_urls = [item["url"] for item in supplemental_metadata]
        if not supplemental_urls:
            remediation_stop_reason = "no_supplemental_queries"
            break
        supplemental_ingestion = await ingest_dynamic_news_urls(
            supplemental_urls,
            limit_per_query,
            start_date,
            end_date,
        )
        supplemental_summary = summarize_ingestion_stage(supplemental_ingestion)
        if supplemental_summary["stored_count"] <= 0:
            no_gain_rounds += 1
        else:
            no_gain_rounds = 0
        urls.extend(supplemental_urls)
        query_metadata.extend(supplemental_metadata)
        dynamic_query_ingestion.extend(supplemental_ingestion)
        remediation_rounds.append(
            {
                "round": round_index + 1,
                "query_count": len(supplemental_urls),
                "stored_count": supplemental_summary["stored_count"],
                "reason": "low_candidate_or_source_coverage",
                "no_gain_rounds": no_gain_rounds,
            }
        )
        if no_gain_rounds >= int(budget.get("no_gain_stop_rounds") or 2):
            remediation_stop_reason = "no_new_sources"
            break

    source_audit = build_source_audit(
        payload,
        urls,
        fixed_source_ingestion,
        dynamic_query_ingestion,
        limit_per_query,
        evidence_limit,
        max_queries,
        query_metadata,
    )
    source_audit["plan_quality"] = service.evaluate_plan_quality(plan).model_dump()
    source_audit["candidate_support"] = candidate_support
    source_audit["source_relevance"] = source_relevance
    source_audit["remediation"] = {
        "supplemented": bool(remediation_rounds),
        "reason": remediation_stop_reason,
        "rounds": remediation_rounds,
        "supplemental_query_count": sum(round_item["query_count"] for round_item in remediation_rounds),
        "supplemental_stored_count": sum(round_item["stored_count"] for round_item in remediation_rounds),
        "stopped_by_no_gain": bool(
            remediation_rounds
            and remediation_rounds[-1].get("no_gain_rounds", 0) >= int(budget.get("no_gain_stop_rounds") or 2)
        ),
    }
    source_audit["query_budget"] = budget
    source_audit["dynamic_entity_backfill"] = dynamic_entity_backfill
    return {
        "urls": urls,
        "start_date": start_date,
        "end_date": end_date,
        "documents": documents,
        "candidates": candidates,
        "fixed_source_ingestion": fixed_source_ingestion,
        "dynamic_query_ingestion": dynamic_query_ingestion,
        "ingestion_results": [fixed_source_ingestion, *dynamic_query_ingestion],
        "source_audit": source_audit,
    }


async def discover_topic_with_timeout(service: TopicDiscoveryService, topic: str, timeout: int = 75) -> dict:
    fallback_plan = TopicDiscoveryService._fallback_plan(topic)
    fallback_quality = service.evaluate_plan_quality(fallback_plan)
    try:
        discovery = await asyncio.wait_for(asyncio.to_thread(service.discover, topic), timeout=timeout)
    except Exception as exc:
        return {
            "topic": topic,
            "fallback": True,
            "message": f"AI topic discovery timed out or failed; deterministic fallback was applied: {exc}",
            "plan": fallback_plan.model_dump(),
            "plan_quality": fallback_quality.model_dump(),
            "initial_plan_quality": service.evaluate_plan_quality(TopicDiscoveryPlan()).model_dump(),
            "repair_attempted": False,
            "repair_applied": False,
            "fallback_plan_applied": True,
        }

    plan = TopicDiscoveryPlan.model_validate(discovery.get("plan") or {})
    plan_quality = service.evaluate_plan_quality(plan)
    if plan_quality.status == "ready":
        return discovery

    if fallback_quality.score > plan_quality.score:
        return {
            **discovery,
            "fallback": True,
            "message": "AI topic discovery was incomplete; deterministic fallback provided broader coverage.",
            "plan": fallback_plan.model_dump(),
            "plan_quality": fallback_quality.model_dump(),
            "fallback_plan_applied": True,
        }
    return discovery


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/db/status")
def database_status() -> dict:
    return db_status()


@app.get("/services/status")
def services_status() -> dict:
    return service_status()


@app.get("/whitelist")
def whitelist() -> dict:
    return SupplyChainWhitelist().raw


@app.get("/llm/status")
def llm_status() -> dict:
    settings = get_settings()
    return {
        "primary_model": settings.primary_llm_model,
        "local_model": settings.local_llm_model,
        "gemini_key_count": len(settings.gemini_api_keys),
        "enabled": len(settings.gemini_api_keys) > 0,
        "retry_policy": {
            "max_retries_per_key": max(0, int(settings.llm_max_retries_per_key)),
            "base_retry_delay_seconds": max(0.0, float(settings.llm_base_retry_delay_seconds)),
            "max_retry_delay_seconds": max(0.0, float(settings.llm_max_retry_delay_seconds)),
        },
    }


@app.post("/discovery/topic-plan")
def discovery_topic_plan(payload: TopicDiscoveryRequest) -> dict:
    return TopicDiscoveryService().discover(payload.topic)


@app.post("/discovery/ingest")
async def discovery_ingest(payload: TopicDiscoveryRequest) -> dict:
    service = TopicDiscoveryService()
    discovery = await discover_topic_with_timeout(service, payload.topic)
    plan = TopicDiscoveryPlan.model_validate(discovery["plan"])
    limit_per_query, evidence_limit, max_queries = discovery_fetch_settings(payload)
    discovery_ingestion = await run_topic_discovery_ingestion(
        payload,
        service,
        plan,
        limit_per_query,
        evidence_limit,
        max_queries,
        document_limit=discovery_document_limit(payload, evidence_limit),
    )
    return {
        "discovery": discovery,
        "queries": discovery_ingestion["urls"],
        "ingestion": discovery_ingestion["ingestion_results"],
        "fixed_source_ingestion": discovery_ingestion["fixed_source_ingestion"],
        "dynamic_query_ingestion": discovery_ingestion["dynamic_query_ingestion"],
        "source_audit": discovery_ingestion["source_audit"],
        "candidate_whitelist": [
            candidate.model_dump() for candidate in discovery_ingestion["candidates"]
        ],
    }


@app.post("/discovery/candidate-whitelist")
def discovery_candidate_whitelist(payload: TopicDiscoveryRequest) -> dict:
    service = TopicDiscoveryService()
    discovery = service.discover(payload.topic)
    plan = TopicDiscoveryPlan.model_validate(discovery["plan"])
    end_date = today_taipei()
    start_date = end_date - timedelta(days=payload.lookback_days)
    with session_scope() as session:
        documents = NewsRepository(session).latest_documents(limit=max(200, payload.evidence_limit))
    documents = IngestionPipeline._filter_documents(documents, start_date, end_date, quality_filter=True)
    candidates = service.validate_candidates(plan, documents)
    return {
        "discovery": discovery,
        "plan_quality": service.evaluate_plan_quality(plan).model_dump(),
        "candidate_whitelist": [candidate.model_dump() for candidate in candidates],
    }


@app.post("/llm/test")
def llm_test() -> dict:
    result = LLMClient().healthcheck()
    return {
        "ok": not result.fallback,
        "model": result.model,
        "key_index": result.key_index,
        "fallback": result.fallback,
        "message": result.text[:200],
    }


@app.post("/ingest/manual")
def ingest_manual(payload: ManualNewsIngest) -> dict:
    document = NewsFetcher.from_manual_text(
        title=payload.title,
        text=payload.text,
        publisher=payload.publisher,
        published_at=payload.published_at,
        url=payload.url,
    )
    VectorStore().upsert_documents([document])
    matches = EntityMapper().match_document(document)
    with session_scope() as session:
        NewsRepository(session).upsert_document(
            document,
            [match.model_dump(mode="json") for match in matches],
        )
    return {"document_id": document.id, "entity_matches": [match.model_dump() for match in matches]}


@app.post("/company-filings/manual")
def ingest_company_filing_manual(payload: ManualCompanyFilingIngest) -> dict:
    document = CompanyFilingFetcher.from_manual_text(
        ticker=payload.ticker,
        company_name=payload.company_name,
        document_type=payload.document_type,
        title=payload.title,
        text=payload.text,
        publisher=payload.publisher,
        published_at=payload.published_at,
        url=payload.url,
    )
    return persist_company_filing_document(document)


@app.post("/company-filings/from-url")
async def ingest_company_filing_from_url(payload: CompanyFilingUrlIngest) -> dict:
    try:
        document = await CompanyFilingFetcher().fetch_url_document(
            url=payload.url,
            ticker=payload.ticker,
            company_name=payload.company_name,
            document_type=payload.document_type,
            publisher=payload.publisher,
            published_at=payload.published_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return persist_company_filing_document(document)


def persist_company_filing_document(document) -> dict:
    news_document = CompanyFilingRepository.to_news_document(document)
    VectorStore().upsert_documents([news_document])
    with session_scope() as session:
        CompanyFilingRepository(session).upsert_document(document)
    return {
        "document_id": document.id,
        "ticker": document.ticker,
        "document_type": document.document_type,
        "source_tier": filing_source_tier(document),
        "quality_score": filing_quality_score(document, document.ticker, document.company_name or ""),
    }


@app.post("/company-filings/fetch")
async def fetch_company_filings(payload: MarketRefreshRequest) -> dict:
    return await IngestionPipeline().ingest_company_filings(
        payload.tickers,
        limit_per_query=3,
        filter_allowed=bool(payload.tickers),
    )


@app.get("/company-filings")
def list_company_filings(tickers: str = "", limit_per_ticker: int = 5) -> list[dict]:
    requested = [ticker.strip() for ticker in tickers.split(",") if ticker.strip()]
    allowed = EntityMapper().filter_allowed_tickers(requested or sorted(EntityMapper().whitelist.allowed_tickers()))
    with session_scope() as session:
        documents = CompanyFilingRepository(session).latest_by_tickers(
            allowed,
            limit_per_ticker=max(1, min(limit_per_ticker, 20)),
        )
        return [
            {
                "id": document.id,
                "ticker": document.ticker,
                "company_name": document.company_name,
                "document_type": document.document_type,
                "title": document.title,
                "publisher": document.source.publisher,
                "source_tier": filing_source_tier(document),
                "quality_score": filing_quality_score(
                    document,
                    document.ticker,
                    document.company_name or "",
                ),
                "published_at": document.source.published_at.isoformat()
                if document.source.published_at
                else None,
                "url": document.source.url,
            }
            for document in documents
        ]


@app.post("/reports/generate", response_model=ReportResponse)
def generate_report(request: ReportRequest) -> ReportResponse:
    with session_scope() as session:
        run = AnalysisRunRepository(session).start("api_sync", request.model_dump(mode="json"))
        run_id = run.id
    try:
        generator = ReportGenerator()
        response = generator.generate(request)
        quality_gate = build_quality_gate_for_request(
            request,
            documents=generator.last_evidence_documents,
            llm_result=getattr(generator, "last_llm_result", None),
            company_filing_sufficient_count=count_sufficient_company_filings(request.tickers),
        )
        response = attach_quality_gate_to_report(response, quality_gate)
        with session_scope() as session:
            report = ReportRepository(session).create(request, response)
            AnalysisRunRepository(session).update_payload(
                run_id,
                {
                    "request": request.model_dump(mode="json"),
                    "quality_gate": quality_gate,
                    "evidence_count": len(generator.last_evidence_documents),
                    "report_execution": report_execution_summary(generator),
                },
            )
            AnalysisRunRepository(session).mark_success(run_id, report.id)
        return response
    except ReportExecutionError as exc:
        with session_scope() as session:
            AnalysisRunRepository(session).mark_failed(run_id, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        with session_scope() as session:
            AnalysisRunRepository(session).mark_failed(run_id, str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/reports")
def list_reports(limit: int = 20) -> list[dict]:
    with session_scope() as session:
        reports = ReportRepository(session).latest(limit)
        return [
            {
                "id": report.id,
                "title": report.title,
                "topic": report.topic,
                "generated_at": report.generated_at.isoformat(),
            }
            for report in reports
        ]


@app.get("/reports/{report_id}")
def get_report(report_id: int) -> dict:
    with session_scope() as session:
        report = ReportRepository(session).get(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="report not found")
        run_repository = AnalysisRunRepository(session)
        run = run_repository.get_by_report_id(report_id)
        run_payload = parse_run_payload(run.payload_json if run is not None else None)
        candidates = candidate_audit_from_run_payload(run_payload)
        auto_follow_up = latest_follow_up_run_for_report(run_repository, report_id)
        try:
            promoted_tickers = json.loads(report.tickers_json)
        except json.JSONDecodeError:
            promoted_tickers = []
        return {
            "id": report.id,
            "title": report.title,
            "topic": report.topic,
            "generated_at": report.generated_at.isoformat(),
            "markdown": append_candidate_audit_if_missing(report.markdown, candidates, promoted_tickers),
            "quality_gate": parse_quality_gate_from_markdown(report.markdown),
            "auto_follow_up": auto_follow_up,
            "candidate_whitelist": candidates,
            "candidate_audit": {
                "summary": candidate_audit_summary(candidates, promoted_tickers),
                "markdown": render_candidate_audit_markdown(candidates, promoted_tickers) if candidates else "",
            },
        }


@app.get("/reports/{report_id}/candidate-audit")
def get_report_candidate_audit(report_id: int) -> dict:
    with session_scope() as session:
        report = ReportRepository(session).get(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="report not found")
        run = AnalysisRunRepository(session).get_by_report_id(report_id)
        run_payload = parse_run_payload(run.payload_json if run is not None else None)
        candidates = candidate_audit_from_run_payload(run_payload)
        try:
            promoted_tickers = json.loads(report.tickers_json)
        except json.JSONDecodeError:
            promoted_tickers = []
    return {
        "report_id": report_id,
        "promoted_tickers": promoted_tickers,
        "summary": candidate_audit_summary(candidates, promoted_tickers),
        "candidate_whitelist": candidates,
        "markdown": render_candidate_audit_markdown(candidates, promoted_tickers),
    }


@app.get("/reports/{report_id}/company-data-audit")
def get_report_company_data_audit(report_id: int) -> dict:
    with session_scope() as session:
        try:
            return audit_report_company_data(session, report_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/reports/{report_id}/follow-up/plan")
def get_report_follow_up_plan(report_id: int) -> dict:
    context = load_report_follow_up_context(report_id)
    request = context["request"]
    markdown = context["markdown"]
    quality_gate = context["quality_gate"]
    company_data_audit = context["company_data_audit"]
    source_audit = context["source_audit"]
    candidate_audit_required = should_require_candidate_audit_follow_up(
        quality_gate,
        company_data_audit,
        context.get("candidate_whitelist") or [],
    )
    planner = FollowUpActionPlanner()
    candidate_actions = planner.plan(
        request,
        quality_gate=quality_gate,
        source_audit=source_audit,
        markdown=markdown,
        company_data_audit=company_data_audit,
        candidate_audit_required=candidate_audit_required,
        apply_freshness=False,
    )
    actions, skipped_details = split_fresh_tracking_actions(candidate_actions, request)
    skipped_action_payloads = [{key: value for key, value in detail.items() if key != "freshness"} for detail in skipped_details]
    return {
        "report_id": report_id,
        "request": request.model_dump(mode="json"),
        "quality_gate_status": quality_gate.get("status"),
        "summary": follow_up_action_summary(actions),
        "freshness": {
            "skipped_count": len(skipped_details),
            "skipped_actions": skipped_action_payloads,
            "skipped_details": skipped_details,
            "thresholds": TRACKING_FRESHNESS_THRESHOLDS,
            "message": "部分追蹤更新因資料仍在新鮮範圍內而略過。" if skipped_details else None,
        },
        "actions": [action.to_dict() for action in actions],
        "next_actions": follow_up_plan_next_actions(actions),
        "markdown_preview": render_follow_up_actions_markdown(actions),
    }


async def maybe_auto_start_required_follow_up(report_id: int, run_in_background: bool = True) -> dict:
    settings = get_settings()
    if not settings.auto_follow_up_enabled:
        return {"status": "disabled", "reason": "AUTO_FOLLOW_UP_ENABLED=false"}

    plan = get_report_follow_up_plan(report_id)
    required_count = int((plan.get("summary") or {}).get("required_count") or 0)
    if required_count <= 0:
        return {
            "status": "not_needed",
            "reason": "quality_gate_ready" if plan.get("quality_gate_status") == "ready" else "no_required_data_gap",
            "plan": {
                "summary": plan.get("summary") or {},
                "next_actions": plan.get("next_actions") or [],
            },
        }

    payload = FollowUpRunRequest(
        rerun_report=True,
        news_limit=settings.auto_follow_up_news_limit,
        purpose="required",
        record_noop=True,
    )
    if run_in_background:
        asyncio.create_task(run_required_follow_up_background(report_id, payload))
        return {
            "status": "queued",
            "source_report_id": report_id,
            "summary": {
                "selected": plan.get("summary") or {},
            },
            "actions": plan.get("actions") or [],
            "next_actions": plan.get("next_actions") or [],
        }

    try:
        result = await run_report_follow_up(report_id, payload)
    except Exception as exc:
        return {
            "status": "failed",
            "reason": str(exc),
            "plan": {
                "summary": plan.get("summary") or {},
                "next_actions": plan.get("next_actions") or [],
            },
        }

    return {
        "status": "started",
        "source_report_id": report_id,
        "run_id": result.get("run_id"),
        "summary": result.get("summary") or {},
        "freshness": result.get("freshness") or {},
        "actions": result.get("actions") or [],
        "rerun_report": result.get("rerun_report"),
        "results": result.get("results") or {},
    }


async def run_required_follow_up_background(report_id: int, payload: FollowUpRunRequest) -> None:
    try:
        await run_report_follow_up(report_id, payload)
    except Exception:
        LOGGER.exception("auto follow-up failed for report %s", report_id)


@app.post("/reports/{report_id}/follow-up/auto-start")
async def auto_start_report_follow_up(report_id: int) -> dict:
    return await maybe_auto_start_required_follow_up(report_id)


@app.post("/reports/{report_id}/follow-up/run")
async def run_report_follow_up(report_id: int, payload: Optional[FollowUpRunRequest] = None) -> dict:
    payload = payload or FollowUpRunRequest()
    context = load_report_follow_up_context(report_id)
    request = context["request"]
    markdown = context["markdown"]
    quality_gate = context["quality_gate"]
    company_data_audit = context["company_data_audit"]
    source_audit = context["source_audit"]
    candidate_audit_required = should_require_candidate_audit_follow_up(
        quality_gate,
        company_data_audit,
        context.get("candidate_whitelist") or [],
    )
    planner = FollowUpActionPlanner()
    candidate_actions = planner.plan(
        request,
        quality_gate=quality_gate,
        source_audit=source_audit,
        markdown=markdown,
        company_data_audit=company_data_audit,
        candidate_audit_required=candidate_audit_required,
        apply_freshness=False,
    )
    fresh_actions, skipped_details = split_fresh_tracking_actions(candidate_actions, request)
    skipped_action_payloads = [{key: value for key, value in detail.items() if key != "freshness"} for detail in skipped_details]
    all_actions = candidate_actions if payload.force_refresh else fresh_actions
    actions = filter_follow_up_actions(all_actions, payload.purpose)
    available_summary = follow_up_action_summary(all_actions)
    selected_summary = follow_up_action_summary(actions)
    if not actions and not payload.record_noop:
        return {
            "report_id": report_id,
            "run_id": None,
            "status": "no_action_required",
            "purpose": payload.purpose,
            "summary": {
                "available": available_summary,
                "selected": selected_summary,
            },
            "freshness": {
                "skipped_count": len(skipped_details),
                "skipped_actions": skipped_action_payloads,
                "skipped_details": skipped_details,
                "thresholds": TRACKING_FRESHNESS_THRESHOLDS,
            },
            "available_actions": [action.to_dict() for action in all_actions],
            "actions": [],
            "results": {},
        }
    with session_scope() as session:
        run = AnalysisRunRepository(session).start(
            "follow_up_api",
            {
                "source_report_id": report_id,
                "request": request.model_dump(mode="json"),
                "quality_gate_before": quality_gate,
                "company_data_audit_before": company_data_audit,
                "candidate_audit_required": candidate_audit_required,
                "available_actions": [action.to_dict() for action in all_actions],
                "freshness": {
                    "skipped_count": len(skipped_details),
                    "skipped_actions": skipped_action_payloads,
                    "skipped_details": skipped_details,
                    "thresholds": TRACKING_FRESHNESS_THRESHOLDS,
                },
                "planned_actions": [action.to_dict() for action in actions],
                "rerun_report": payload.rerun_report,
                "purpose": payload.purpose,
                "force_refresh": payload.force_refresh,
            },
        )
        run_id = run.id
    if not actions:
        with session_scope() as session:
            AnalysisRunRepository(session).update_payload(
                run_id,
                {
                    "source_report_id": report_id,
                    "request": request.model_dump(mode="json"),
                    "quality_gate_before": quality_gate,
                    "company_data_audit_before": company_data_audit,
                    "candidate_audit_required": candidate_audit_required,
                    "available_actions": [action.to_dict() for action in all_actions],
                    "planned_actions": [],
                    "purpose": payload.purpose,
                    "force_refresh": payload.force_refresh,
                    "summary": {
                        "available": available_summary,
                        "selected": selected_summary,
                    },
                    "freshness": {
                        "skipped_count": len(skipped_details),
                        "skipped_actions": skipped_action_payloads,
                        "skipped_details": skipped_details,
                        "thresholds": TRACKING_FRESHNESS_THRESHOLDS,
                    },
                    "status": "no_action_required",
                },
            )
            AnalysisRunRepository(session).mark_success(run_id, report_id)
        return {
            "report_id": report_id,
            "run_id": run_id,
            "status": "no_action_required",
            "purpose": payload.purpose,
            "summary": {
                "available": available_summary,
                "selected": selected_summary,
            },
            "freshness": {
                "skipped_count": len(skipped_details),
                "skipped_actions": skipped_action_payloads,
                "skipped_details": skipped_details,
                "thresholds": TRACKING_FRESHNESS_THRESHOLDS,
            },
            "actions": [],
            "results": {},
        }
    try:
        execution = await execute_follow_up_actions(actions, request, news_limit=payload.news_limit)
    except Exception as exc:
        safe_mark_run_failed(run_id, str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    execution_summary = execution.get("execution_summary") or {}
    if "completion" not in execution_summary:
        execution_summary = summarize_follow_up_execution(execution)
    response_payload = {
        "report_id": report_id,
        "run_id": run_id,
        "status": "executed",
        "purpose": payload.purpose,
        "force_refresh": payload.force_refresh,
        "summary": {
            "available": available_summary,
            "selected": selected_summary,
            "execution": execution_summary,
        },
        "freshness": {
            "skipped_count": len(skipped_details),
            "skipped_actions": skipped_action_payloads,
            "skipped_details": skipped_details,
            "thresholds": TRACKING_FRESHNESS_THRESHOLDS,
        },
        "actions": [action.to_dict() for action in actions],
        "results": execution["results"],
        "rerun_report": None,
    }
    can_revalidate_from_existing = can_rerun_candidate_revalidation_from_existing_evidence(context, actions)
    if can_revalidate_from_existing and execution_summary.get("rerun_blocked"):
        execution_summary = {
            **execution_summary,
            "rerun_blocked": False,
            "rerun_blockers": [],
            "rerun_blocker_actions": [],
            "revalidation_from_existing_evidence": True,
        }
        response_payload["summary"]["execution"] = execution_summary
    if payload.rerun_report and execution_summary.get("rerun_blocked") and not can_revalidate_from_existing:
        response_payload["rerun_report"] = {
            "status": "skipped",
            "reason": "補資料後仍有關鍵缺口，先不重新產生報告。",
            "blockers": execution_summary.get("rerun_blockers", []),
            "next_actions": execution_summary.get("rerun_blocker_actions", []),
        }
    elif payload.rerun_report:
        rerun_context = await prepare_follow_up_report_context(context, request, actions)
        rerun_request = rerun_context["request"]
        whitelist = rerun_context["whitelist"]
        generator = ReportGenerator(whitelist=whitelist) if whitelist else ReportGenerator()
        try:
            response = generator.generate(rerun_request)
        except ReportExecutionError as exc:
            safe_mark_run_failed(run_id, str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        candidate_revalidation = rerun_context["candidate_revalidation"]
        rerun_candidate_support = summarize_candidate_support_payload(
            candidate_revalidation.get("candidate_whitelist") or []
        )
        refreshed_quality_gate = build_quality_gate_for_request(
            rerun_request,
            documents=generator.last_evidence_documents,
            llm_result=getattr(generator, "last_llm_result", None),
            company_filing_sufficient_count=count_sufficient_company_filings(rerun_request.tickers),
            candidate_support=rerun_candidate_support,
            plan_quality=(
                (context.get("run_payload") or {}).get("plan_quality")
                or ((context.get("run_payload") or {}).get("discovery") or {}).get("plan_quality")
                or plan_quality_from_quality_gate(context.get("quality_gate") or {})
            ),
        )
        response = attach_quality_gate_to_report(response, refreshed_quality_gate)
        with session_scope() as session:
            new_report = ReportRepository(session).create(rerun_request, response)
            new_report_id = new_report.id
        response_payload["rerun_report"] = {
            "report_id": new_report_id,
            "request": rerun_request.model_dump(mode="json"),
            "quality_gate": refreshed_quality_gate,
            "report_execution": report_execution_summary(generator),
            "candidate_revalidation": candidate_revalidation,
            "follow_up_section": render_follow_up_actions_markdown(
                FollowUpActionPlanner().plan(
                    rerun_request,
                    quality_gate=refreshed_quality_gate,
                    markdown=response.markdown,
                    candidate_audit_required=should_require_candidate_audit_follow_up(
                        refreshed_quality_gate,
                        {"status": "sufficient"},
                        candidate_revalidation.get("candidate_whitelist") or [],
                    ),
                )
            ),
        }
    persisted_request = (response_payload["rerun_report"] or {}).get("request") or request.model_dump(mode="json")
    persisted_candidates = (
        (response_payload["rerun_report"] or {})
        .get("candidate_revalidation", {})
        .get("candidate_whitelist")
        or context.get("candidate_whitelist")
    )
    with session_scope() as session:
        AnalysisRunRepository(session).update_payload(
            run_id,
            {
                "source_report_id": report_id,
                "request": persisted_request,
                "quality_gate_before": quality_gate,
                "available_actions": [action.to_dict() for action in all_actions],
                "freshness": response_payload["freshness"],
                "planned_actions": [action.to_dict() for action in actions],
                "execution": execution,
                "rerun_report": response_payload["rerun_report"],
                "candidate_whitelist": persisted_candidates,
                "purpose": payload.purpose,
                "force_refresh": payload.force_refresh,
                "summary": response_payload["summary"],
            },
        )
        AnalysisRunRepository(session).mark_success(
            run_id,
            (response_payload["rerun_report"] or {}).get("report_id") or report_id,
        )
    return response_payload


@app.delete("/reports/{report_id}")
def delete_report(report_id: int) -> dict:
    with session_scope() as session:
        deleted = ReportRepository(session).delete(report_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="report not found")
        return {"deleted": True, "id": report_id}


@app.get("/news")
def list_news(limit: int = 20) -> list[dict]:
    with session_scope() as session:
        documents = NewsRepository(session).latest_documents(limit)
        return [
            {
                "id": document.id,
                "title": document.title,
                "publisher": document.source.publisher,
                "published_at": document.source.published_at.isoformat()
                if document.source.published_at
                else None,
                "url": document.source.url,
            }
            for document in documents
        ]


@app.get("/news/sources")
def list_news_sources() -> list[dict]:
    return [source.model_dump(mode="json") for source in NewsSourceStore().load()]


@app.post("/news/fetch")
async def fetch_news(payload: FeedFetchRequest) -> dict:
    return await IngestionPipeline().ingest_feeds(
        url=payload.url,
        publisher=payload.publisher,
        limit=payload.limit,
        enabled_sources_only=payload.enabled_sources_only,
        topic=payload.topic,
    )


@app.post("/market/refresh")
async def refresh_market(payload: MarketRefreshRequest) -> dict:
    end_date = payload.end_date or today_taipei()
    start_date = payload.start_date or end_date - timedelta(days=14)
    return await IngestionPipeline().refresh_market(payload.tickers, start_date, end_date)


@app.post("/market/refresh_fundamentals")
async def refresh_fundamentals(payload: MarketRefreshRequest) -> dict:
    end_date = payload.end_date or today_taipei()
    start_date = payload.start_date or end_date - timedelta(days=365 * 6)
    pipeline = IngestionPipeline()
    financial_metrics = await pipeline.refresh_financial_metrics(payload.tickers, start_date, end_date)
    valuations = await pipeline.refresh_valuations(
        payload.tickers,
        end_date - timedelta(days=30),
        end_date,
    )
    return {
        "financial_metrics": financial_metrics,
        "valuations": valuations,
    }


@app.get("/market/snapshots")
def market_snapshots(tickers: str = "") -> list[dict]:
    mapper = EntityMapper()
    requested = [ticker.strip() for ticker in tickers.split(",") if ticker.strip()]
    allowed = mapper.filter_allowed_tickers(requested or sorted(mapper.whitelist.allowed_tickers()))
    with session_scope() as session:
        snapshots = MarketRepository(session).latest_by_tickers(allowed)
        return [snapshot.model_dump(mode="json") for snapshot in snapshots]


@app.get("/schedule")
def get_schedule() -> dict:
    return ScheduleConfigStore().load().model_dump(mode="json")


@app.put("/schedule")
def update_schedule(config: ScheduleConfig) -> dict:
    saved = ScheduleConfigStore().save(config)
    return saved.model_dump(mode="json")


@app.get("/runs")
def list_runs(limit: int = 20) -> list[dict]:
    with session_scope() as session:
        runs = AnalysisRunRepository(session).latest(limit)
        return [serialize_run(run) for run in runs]


@app.get("/runs/{run_id}")
def get_run(run_id: int) -> dict:
    with session_scope() as session:
        run = AnalysisRunRepository(session).get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return serialize_run(run)


@app.delete("/runs/{run_id}")
def delete_run(run_id: int) -> dict:
    with session_scope() as session:
        deleted = AnalysisRunRepository(session).delete(run_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="run not found")
        return {"deleted": True, "id": run_id}


@app.post("/maintenance/cleanup")
def maintenance_cleanup(payload: MaintenanceCleanupRequest) -> dict:
    with session_scope() as session:
        result = {
            "failed_runs_deleted": 0,
            "orphan_report_refs_cleared": 0,
            "stale_running_marked_failed": 0,
            "old_runs_deleted": 0,
            "old_reports_deleted": 0,
        }
        runs = AnalysisRunRepository(session)
        reports = ReportRepository(session)
        if payload.failed_runs:
            result["failed_runs_deleted"] = runs.delete_failed()
        if payload.orphan_report_refs:
            result["orphan_report_refs_cleared"] = runs.clear_orphan_report_refs()
        if payload.stale_running_before:
            result["stale_running_marked_failed"] = runs.mark_stale_running_failed(
                payload.stale_running_before,
                "marked failed by maintenance cleanup",
            )
        if payload.runs_before:
            result["old_runs_deleted"] = runs.delete_before(payload.runs_before)
        if payload.reports_before:
            result["old_reports_deleted"] = reports.delete_before(payload.reports_before)
        return result


@app.post("/pipeline/run")
async def run_pipeline(request: ReportRequest) -> dict:
    with session_scope() as session:
        run = AnalysisRunRepository(session).start("pipeline_api", request.model_dump(mode="json"))
        run_id = run.id
    try:
        ingestion_summary = await IngestionPipeline().pre_report_refresh(request)
        generator = ReportGenerator()
        response = generator.generate(request)
        quality_gate = build_quality_gate_for_request(
            request,
            documents=generator.last_evidence_documents,
            source_count=max(
                (ingestion_summary.get("news") or {}).get("count", 0),
                len(generator.last_evidence_documents),
            ),
            llm_result=getattr(generator, "last_llm_result", None),
        )
        response = attach_quality_gate_to_report(response, quality_gate)
        with session_scope() as session:
            report = ReportRepository(session).create(request, response)
            report_id = report.id
        run_record_updated = safe_update_run_success(
            run_id,
            {
                "request": request.model_dump(mode="json"),
                "ingestion": ingestion_summary,
                "quality_gate": quality_gate,
                "report_execution": report_execution_summary(generator),
            },
            report_id,
        )
        auto_follow_up = await maybe_auto_start_required_follow_up(report_id)
        return {
            "run_id": run_id,
            "run_record_updated": run_record_updated,
            "report_id": report_id,
            "active_report_id": ((auto_follow_up.get("rerun_report") or {}).get("report_id") or report_id),
            "auto_follow_up": auto_follow_up,
            "ingestion": ingestion_summary,
            "quality_gate": quality_gate,
            "report": response.model_dump(mode="json"),
        }
    except ReportExecutionError as exc:
        safe_mark_run_failed(run_id, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        safe_mark_run_failed(run_id, str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/pipeline/run_discovered")
async def run_discovered_pipeline(payload: TopicDiscoveryRequest) -> dict:
    with session_scope() as session:
        run = AnalysisRunRepository(session).start("pipeline_ai_discovery", payload.model_dump(mode="json"))
        run_id = run.id
    try:
        service = TopicDiscoveryService()
        discovery = await discover_topic_with_timeout(service, payload.topic)
        plan = TopicDiscoveryPlan.model_validate(discovery["plan"])
        limit_per_query, evidence_limit, max_queries = discovery_fetch_settings(payload)
        discovery_ingestion = await run_topic_discovery_ingestion(
            payload,
            service,
            plan,
            limit_per_query,
            evidence_limit,
            max_queries,
            document_limit=discovery_document_limit(payload, evidence_limit),
        )
        urls = discovery_ingestion["urls"]
        end_date = discovery_ingestion["end_date"]
        documents = discovery_ingestion["documents"]
        fixed_source_ingestion = discovery_ingestion["fixed_source_ingestion"]
        dynamic_query_ingestion = discovery_ingestion["dynamic_query_ingestion"]
        ingestion_results = discovery_ingestion["ingestion_results"]
        source_audit = discovery_ingestion["source_audit"]
        candidate_payload = [
            candidate.model_dump() for candidate in discovery_ingestion["candidates"]
        ]
        candidate_filing_ingestion = None
        if should_revalidate_candidate_filings(candidate_payload):
            candidate_tickers = candidate_filing_revalidation_tickers(candidate_payload, payload)
            candidate_filing_ingestion = company_filing_timeout_result(
                candidate_tickers,
                RuntimeError("skipped during synchronous deep analysis; queued as follow-up"),
                "candidate MOPS annual report discovery",
            )
            with session_scope() as session:
                candidate_filing_documents = [
                    CompanyFilingRepository.to_news_document(document)
                    for document in CompanyFilingRepository(session).latest_by_tickers(
                        candidate_tickers,
                        limit_per_ticker=2,
                    )
                ]
            if candidate_filing_documents:
                documents = dedupe_documents([*documents, *candidate_filing_documents])
                revalidated_candidates = service.validate_candidates(plan, documents)
                candidate_payload = [candidate.model_dump() for candidate in revalidated_candidates]
                source_audit["candidate_support"] = summarize_candidate_support(revalidated_candidates)
                source_audit["candidate_filing_revalidation"] = {
                    "attempted": True,
                    "stored_count": candidate_filing_ingestion.get("stored_count", 0),
                    "document_count": len(candidate_filing_documents),
                    "promoted_after_revalidation": [
                        candidate["ticker"]
                        for candidate in candidate_payload
                        if candidate["status"] == "evidence_supported"
                    ],
                    "requested_tickers": candidate_tickers,
                }
        candidate_payload = apply_company_filing_gate_to_candidate_payload(candidate_payload)
        source_audit["candidate_support"] = summarize_candidate_support_payload(candidate_payload)
        promoted_tickers = [
            candidate["ticker"]
            for candidate in candidate_payload
            if candidate["status"] == "evidence_supported"
        ]
        dynamic_whitelist = SupplyChainWhitelist.from_candidate_whitelist(candidate_payload)
        if promoted_tickers:
            company_filing_ingestion = company_filing_timeout_result(
                promoted_tickers,
                RuntimeError("skipped during synchronous deep analysis; queued as follow-up"),
                "promoted MOPS annual report discovery",
            )
        else:
            company_filing_ingestion = {
                "requested_tickers": [],
                "stored_count": 0,
                "per_ticker_results": [],
                "gap_summary": {"blocked_tickers": [], "retryable_tickers": []},
                "errors": [],
                "source": "Company filing discovery skipped: no promoted candidates",
            }
        with session_scope() as session:
            company_filing_documents = [
                CompanyFilingRepository.to_news_document(document)
                for document in CompanyFilingRepository(session).latest_by_tickers(
                    promoted_tickers,
                    limit_per_ticker=4,
                )
            ]
        documents = dedupe_documents([*documents, *company_filing_documents])

        market_client = MarketDataClient()
        market_start_date = end_date - timedelta(days=discovery_market_history_days(payload))
        valuation_start_date = end_date - timedelta(days=discovery_valuation_history_days(payload))
        try:
            price_histories, market_errors = await asyncio.wait_for(
                market_client.get_price_histories_with_errors(
                    promoted_tickers,
                    market_start_date,
                    end_date,
                ),
                timeout=60,
            )
        except Exception as exc:
            price_histories = {}
            market_errors = market_timeout_errors(promoted_tickers, "TaiwanStockPrice", exc)
        snapshots = [
            sorted(history, key=lambda snapshot: snapshot.trade_date)[-1]
            for history in price_histories.values()
            if history
        ]
        price_history_snapshots = [snapshot for history in price_histories.values() for snapshot in history]
        try:
            monthly_revenues, monthly_revenue_errors = await asyncio.wait_for(
                market_client.get_monthly_revenue_histories_with_errors(
                    promoted_tickers,
                    end_date - timedelta(days=450),
                    end_date,
                ),
                timeout=60,
            )
        except Exception as exc:
            monthly_revenues = []
            monthly_revenue_errors = market_timeout_errors(
                promoted_tickers,
                "TaiwanStockMonthRevenue",
                exc,
            )
        try:
            financial_metrics, financial_metric_errors = await asyncio.wait_for(
                market_client.get_financial_metrics_histories_with_errors(
                    promoted_tickers,
                    end_date - timedelta(days=365 * 6),
                    end_date,
                ),
                timeout=90,
            )
        except Exception as exc:
            financial_metrics = []
            financial_metric_errors = market_timeout_errors(
                promoted_tickers,
                "FinMindFinancialStatements",
                exc,
            )
        try:
            valuations, valuation_errors = await asyncio.wait_for(
                market_client.get_latest_valuations_with_errors(
                    promoted_tickers,
                    valuation_start_date,
                    end_date,
                ),
                timeout=45,
            )
        except Exception as exc:
            valuations = []
            valuation_errors = market_timeout_errors(promoted_tickers, "TaiwanStockPER", exc)
        with session_scope() as session:
            market_repository = MarketRepository(session)
            monthly_repository = MonthlyRevenueRepository(session)
            financial_repository = FinancialMetricRepository(session)
            valuation_repository = ValuationMetricRepository(session)
            market_repository.upsert_snapshots(price_history_snapshots)
            monthly_repository.upsert_revenues(monthly_revenues)
            financial_repository.upsert_metrics(financial_metrics)
            valuation_repository.upsert_valuations(valuations)
            snapshots = merge_latest_by_ticker(
                promoted_tickers,
                snapshots,
                market_repository.latest_by_tickers(promoted_tickers),
                "trade_date",
            )
            financial_metrics = merge_financial_metric_history(
                financial_metrics,
                financial_repository.by_tickers(promoted_tickers),
            )
            valuations = merge_latest_by_ticker(
                promoted_tickers,
                valuations,
                valuation_repository.latest_by_tickers(promoted_tickers),
                "trade_date",
            )
            latest_monthly_revenues = monthly_repository.latest_by_tickers(promoted_tickers)
        market_tickers = {snapshot.ticker for snapshot in snapshots}
        monthly_tickers = {revenue.ticker for revenue in latest_monthly_revenues}
        valuation_tickers = {valuation.ticker for valuation in valuations}
        leading_signal_count = sum(
            1
            for ticker in promoted_tickers
            if ticker in market_tickers or ticker in monthly_tickers or ticker in valuation_tickers
        )
        request = ReportRequest(
            topic=payload.topic,
            tickers=promoted_tickers,
            lookback_days=discovery_effective_lookback_days(payload),
            evidence_limit=evidence_limit,
            investor_capital=payload.investor_capital,
            beginner_mode=payload.beginner_mode,
            investor_profile=payload.investor_profile,
            max_position_pct=payload.max_position_pct,
            cash_reserve_pct=payload.cash_reserve_pct,
        )
        generator = ReportGenerator(whitelist=dynamic_whitelist)
        response = generator.generate(request, documents=documents)
        company_filing_sufficient_count = count_sufficient_company_filings(promoted_tickers)
        quality_gate = build_report_quality_gate(
            source_audit,
            promoted_tickers,
            market_count=len(snapshots),
            monthly_revenue_count=len(latest_monthly_revenues),
            financial_metrics_count=len(financial_metrics),
            valuation_count=len(valuations),
            investor_capital=payload.investor_capital,
            cash_reserve_pct=payload.cash_reserve_pct,
            source_quality=summarize_document_source_quality(documents, discovery_effective_lookback_days(payload)),
            plan_quality=source_audit.get("plan_quality"),
            leading_signal_count=leading_signal_count,
            llm_status=summarize_llm_status(generator.last_llm_result),
            company_filing_sufficient_count=company_filing_sufficient_count,
        )
        response = attach_quality_gate_to_report(response, quality_gate)
        with session_scope() as session:
            report = ReportRepository(session).create(request, response)
            report_id = report.id
        run_payload = {
            "request": request.model_dump(mode="json"),
            "discovery": discovery,
            "queries": urls,
            "ingestion": ingestion_results,
            "fixed_source_ingestion": fixed_source_ingestion,
            "dynamic_query_ingestion": dynamic_query_ingestion,
            "candidate_filing_ingestion": candidate_filing_ingestion,
            "company_filing_ingestion": company_filing_ingestion,
            "source_audit": source_audit,
            "candidate_whitelist": candidate_payload,
            "market": [snapshot.model_dump(mode="json") for snapshot in snapshots],
            "market_history_days": discovery_market_history_days(payload),
            "market_history_count": len(price_history_snapshots),
            "market_errors": [error.model_dump() for error in market_errors],
            "monthly_revenue": [
                revenue.model_dump(mode="json") for revenue in monthly_revenues
            ],
            "monthly_revenue_errors": [
                error.model_dump() for error in monthly_revenue_errors
            ],
            "latest_monthly_revenue": [
                revenue.model_dump(mode="json") for revenue in latest_monthly_revenues
            ],
            "financial_metrics_count": len(financial_metrics),
            "financial_metric_errors": [
                error.model_dump() for error in financial_metric_errors
            ],
            "valuations": [valuation.model_dump(mode="json") for valuation in valuations],
            "valuation_history_days": discovery_valuation_history_days(payload),
            "valuation_errors": [error.model_dump() for error in valuation_errors],
            "quality_gate": quality_gate,
            "report_execution": report_execution_summary(generator),
        }
        run_record_updated = safe_update_run_success(run_id, run_payload, report_id)
        auto_follow_up = await maybe_auto_start_required_follow_up(report_id)
        return {
            "run_id": run_id,
            "run_record_updated": run_record_updated,
            "report_id": report_id,
            "active_report_id": ((auto_follow_up.get("rerun_report") or {}).get("report_id") or report_id),
            "auto_follow_up": auto_follow_up,
            "discovery": discovery,
            "queries": urls,
            "fixed_source_ingestion": fixed_source_ingestion,
            "dynamic_query_ingestion": dynamic_query_ingestion,
            "candidate_filing_ingestion": candidate_filing_ingestion,
            "company_filing_ingestion": company_filing_ingestion,
            "source_audit": source_audit,
            "candidate_whitelist": candidate_payload,
            "promoted_tickers": promoted_tickers,
            "market": [snapshot.model_dump(mode="json") for snapshot in snapshots],
            "market_history_count": len(price_history_snapshots),
            "market_errors": [error.model_dump() for error in market_errors],
            "monthly_revenue": [revenue.model_dump(mode="json") for revenue in monthly_revenues],
            "monthly_revenue_errors": [
                error.model_dump() for error in monthly_revenue_errors
            ],
            "latest_monthly_revenue": [
                revenue.model_dump(mode="json") for revenue in latest_monthly_revenues
            ],
            "financial_metrics_count": len(financial_metrics),
            "financial_metric_errors": [
                error.model_dump() for error in financial_metric_errors
            ],
            "valuations": [valuation.model_dump(mode="json") for valuation in valuations],
            "valuation_errors": [error.model_dump() for error in valuation_errors],
            "quality_gate": quality_gate,
            "report_execution": report_execution_summary(generator),
            "report": response.model_dump(mode="json"),
        }
    except ReportExecutionError as exc:
        safe_mark_run_failed(run_id, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        safe_mark_run_failed(run_id, str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/reports/generate_async")
def generate_report_async(request: ReportRequest) -> dict:
    mapper = EntityMapper()
    filtered_tickers = mapper.filter_allowed_tickers(request.tickers)
    dropped_tickers = [ticker for ticker in request.tickers if ticker not in set(filtered_tickers)]
    if dropped_tickers:
        raise HTTPException(
            status_code=400,
            detail=(
                "async report generation received tickers outside the static whitelist: "
                + ", ".join(dropped_tickers)
            ),
        )
    if not filtered_tickers:
        raise HTTPException(
            status_code=400,
            detail="async report generation requires at least one whitelisted ticker",
        )
    task = generate_report_task.delay(request.model_dump(mode="json"))
    return {"task_id": task.id, "status": "queued"}


@app.get("/tasks/{task_id}")
def get_task_status(task_id: str) -> dict:
    result = celery_app.AsyncResult(task_id)
    response = {
        "task_id": task_id,
        "status": result.status,
        "ready": result.ready(),
        "successful": result.successful() if result.ready() else False,
    }
    if result.ready():
        if result.successful():
            response["result"] = result.result
        else:
            response["error"] = str(result.result)
    with session_scope() as session:
        run = AnalysisRunRepository(session).get_by_celery_task_id(task_id)
        if run is not None:
            response["run"] = serialize_run(run)
    return response


@app.get("/tasks/{task_id}/run")
def get_run_by_task_id(task_id: str) -> dict:
    with session_scope() as session:
        run = AnalysisRunRepository(session).get_by_celery_task_id(task_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found for task")
        return serialize_run(run)
