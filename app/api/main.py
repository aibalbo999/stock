from __future__ import annotations

import asyncio
import json
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
from app.data_sources.market import MarketDataClient
from app.data_sources.news import NewsFetcher, NewsSourceStore
from app.db.status import db_status
from app.db.session import init_db, session_scope
from app.models.schemas import ReportRequest, ReportResponse
from app.rag.vector_store import VectorStore
from app.services.candidate_audit import candidate_audit_summary, render_candidate_audit_markdown
from app.services.candidate_confidence import is_low_formal_confidence
from app.services.company_data_audit import audit_report_company_data
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
from app.services.ingestion import IngestionPipeline
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
from app.services.report_generator import ReportGenerator
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
from app.services.topic_discovery import TopicDiscoveryPlan, TopicDiscoveryService
from app.services.whitelist import SupplyChainWhitelist
from app.tasks.celery_app import celery_app
from app.tasks.tasks import generate_report_task


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


def count_sufficient_company_filings(tickers: list[str]) -> int:
    if not tickers:
        return 0
    with session_scope() as session:
        documents = CompanyFilingRepository(session).latest_by_tickers(tickers, limit_per_ticker=8)
    high_quality_types_by_ticker: dict[str, set[str]] = {ticker: set() for ticker in tickers}
    company_names = {company.ticker: company.name for company in SupplyChainWhitelist().companies()}
    for document in documents:
        if filing_quality_score(document, document.ticker, company_names.get(document.ticker, "")) >= 70:
            high_quality_types_by_ticker.setdefault(document.ticker, set()).add(document.document_type)
    return sum(
        1
        for ticker in tickers
        if all(document_type in high_quality_types_by_ticker.get(ticker, set()) for document_type in REQUIRED_CORE_DOCUMENT_TYPES)
    )


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
        try:
            company_data_audit = audit_report_company_data(session, report_id)
        except ValueError:
            company_data_audit = {}
    run_payload = parse_run_payload(run_payload_json)
    request = request_from_report_record(topic, tickers, run_payload_json)
    candidates = candidate_audit_from_run_payload(run_payload)
    markdown = append_candidate_audit_if_missing(markdown, candidates, request.tickers)
    return {
        "request": request,
        "markdown": markdown,
        "quality_gate": parse_quality_gate_from_markdown(markdown) or {},
        "candidate_whitelist": candidates,
        "company_data_audit": company_data_audit,
        "run_payload": run_payload,
    }


def should_require_candidate_audit_follow_up(quality_gate: dict, company_data_audit: dict) -> bool:
    if quality_gate.get("status") != "ready":
        return True
    if company_data_audit and company_data_audit.get("status") != "sufficient":
        return True
    return False


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
    candidates = TopicDiscoveryService().validate_candidates(plan, documents)
    candidate_payload = [candidate.model_dump() for candidate in candidates]
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
        "newly_promoted": newly_promoted,
        "no_longer_promoted": no_longer_promoted,
        "status_changes": status_changes,
        "changed": bool(newly_promoted or no_longer_promoted or status_changes),
    }


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
    if not documents:
        documents = repository.latest_documents(limit)
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
            haystack = f"{document.title}\n{document.text}"
            dynamic_matches = []
            for plan_candidate in plan.candidate_companies:
                candidate = candidate_lookup.get(plan_candidate.ticker)
                if candidate is None:
                    continue
                if not service._has_entity_and_context(
                    haystack,
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
        "ingest_news": "依股票與主題補抓近期多來源資料，補足公司層級證據。",
        "ingest_company_filings": "先自動搜尋官方/MOPS/IR 文件；若仍不足，系統會列出需人工匯入的文件。",
        "refresh_market": "刷新近期股價、量能與波動資料，用於降值風險與進出場檢查。",
        "refresh_monthly_revenue": "補齊近月營收序列，用於成長加速或轉弱判斷。",
        "refresh_financial_metrics": "補齊多年財報指標，用於財務體質、利潤率與負債檢查。",
        "refresh_valuations": "刷新本益比、股價淨值比與殖利率，用於同業估值比較。",
        "rerun_discovery": "重新拆解主題與候選公司，確認白名單是否需調整。",
        "rerun_analysis": "在補資料後重新產生報告；若仍有關鍵缺口，系統會先暫停重跑。",
    }
    return steps.get(action.action_type, "依任務設定補齊資料後再評估是否重跑報告。")


def follow_up_plan_action_completion_criteria(action) -> str:
    criteria = {
        "ingest_news": "每檔至少補到 2 個以上來源或足以支撐/排除產業鏈關聯的近期證據。",
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
    deep_analysis: bool = False
    include_international: bool = True
    investor_capital: int = 1_000_000
    beginner_mode: bool = True
    investor_profile: str = "beginner"
    max_position_pct: float = 0.10
    cash_reserve_pct: float = 0.30


def discovery_fetch_settings(payload: TopicDiscoveryRequest) -> tuple[int, int, int]:
    limit_per_query = payload.limit_per_query
    evidence_limit = payload.evidence_limit
    max_queries = 20
    if payload.deep_analysis:
        limit_per_query = max(limit_per_query, 12)
        evidence_limit = max(evidence_limit, 120)
        max_queries = 12
    return limit_per_query, evidence_limit, max_queries


def should_revalidate_candidate_filings(candidates: list[dict], min_supported_ratio: float = 0.6) -> bool:
    if not candidates:
        return False
    supported = sum(1 for candidate in candidates if candidate.get("status") == "evidence_supported")
    return (supported / len(candidates)) < min_supported_ratio


def candidate_filing_revalidation_tickers(candidates: list[dict], payload: TopicDiscoveryRequest) -> list[str]:
    limit = 20 if payload.deep_analysis else 12
    prioritized = [
        str(candidate.get("ticker"))
        for candidate in candidates
        if candidate.get("ticker") and candidate.get("status") != "evidence_supported"
    ]
    fallback = [str(candidate.get("ticker")) for candidate in candidates if candidate.get("ticker")]
    return list(dict.fromkeys([*prioritized, *fallback]))[:limit]


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
    for item in query_metadata:
        source_type = str(item.get("source_type") or "unknown")
        query_type_counts[source_type] = query_type_counts.get(source_type, 0) + 1
    query_type_labels = {
        source_type: query_type_label(source_type)
        for source_type in query_type_counts
    }
    return {
        "topic": payload.topic,
        "lookback_days": payload.lookback_days,
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


def summarize_candidate_support(candidates) -> dict:
    total = len(candidates)
    supported = sum(1 for candidate in candidates if candidate.status == "evidence_supported")
    weak = sum(1 for candidate in candidates if candidate.status == "weak_evidence")
    unsupported = sum(1 for candidate in candidates if candidate.status == "needs_evidence")
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
    if candidate_support["total"] == 0:
        return source_audit["dynamic_queries"]["stored_count"] < 8
    if candidate_support["supported_ratio"] < 0.6:
        return True
    return source_audit["dynamic_queries"]["stored_count"] < 12


def discovery_query_budget(max_queries: int, deep_analysis: bool) -> dict:
    initial_queries = max(8, int(max_queries * 0.65))
    return {
        "initial_queries": min(max_queries, initial_queries),
        "supplemental_queries": max(0, max_queries - initial_queries),
        "supplemental_rounds": 1 if deep_analysis else 1,
        "supplemental_batch_size": 8 if deep_analysis else 6,
    }


async def ingest_dynamic_news_urls(
    urls: list[str],
    limit_per_query: int,
    start_date: date,
    end_date: date,
) -> list[dict]:
    ingestion_results = []
    for url in urls:
        try:
            ingestion_results.append(
                await asyncio.wait_for(
                    IngestionPipeline().ingest_feeds(
                        url=url,
                        publisher=None,
                        limit=limit_per_query,
                        start_date=start_date,
                        end_date=end_date,
                    ),
                    timeout=12,
                )
            )
        except Exception as exc:
            ingestion_results.append(
                {
                    "count": 0,
                    "items": [],
                    "errors": [{"source": url, "error": str(exc) or exc.__class__.__name__}],
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
    budget = discovery_query_budget(max_queries, payload.deep_analysis)
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
    start_date = end_date - timedelta(days=payload.lookback_days)
    fixed_source_ingestion = await IngestionPipeline().ingest_feeds(
        enabled_sources_only=True,
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
        if not should_supplement_discovery_sources(source_audit, candidate_support):
            break
        remaining_queries = max_queries - len(urls)
        if remaining_queries <= 0 or round_index >= budget["supplemental_rounds"]:
            break
        supplemental_metadata = service.supplemental_google_news_query_metadata(
            plan,
            candidates,
            include_international=payload.include_international,
            max_urls=min(remaining_queries, budget["supplemental_batch_size"]),
            existing_urls=urls,
        )
        supplemental_urls = [item["url"] for item in supplemental_metadata]
        if not supplemental_urls:
            break
        supplemental_ingestion = await ingest_dynamic_news_urls(
            supplemental_urls,
            limit_per_query,
            start_date,
            end_date,
        )
        urls.extend(supplemental_urls)
        query_metadata.extend(supplemental_metadata)
        dynamic_query_ingestion.extend(supplemental_ingestion)
        remediation_rounds.append(
            {
                "round": round_index + 1,
                "query_count": len(supplemental_urls),
                "stored_count": summarize_ingestion_stage(supplemental_ingestion)["stored_count"],
                "reason": "low_candidate_or_source_coverage",
            }
        )

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
    source_audit["remediation"] = {
        "supplemented": bool(remediation_rounds),
        "reason": "low_candidate_or_source_coverage" if remediation_rounds else "coverage_sufficient",
        "rounds": remediation_rounds,
        "supplemental_query_count": sum(round_item["query_count"] for round_item in remediation_rounds),
        "supplemental_stored_count": sum(round_item["stored_count"] for round_item in remediation_rounds),
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

    if fallback_quality.ready_score > plan_quality.ready_score:
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
        document_limit=200,
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
                },
            )
            AnalysisRunRepository(session).mark_success(run_id, report.id)
        return response
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
        run = AnalysisRunRepository(session).get_by_report_id(report_id)
        run_payload = parse_run_payload(run.payload_json if run is not None else None)
        candidates = candidate_audit_from_run_payload(run_payload)
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
    candidate_audit_required = should_require_candidate_audit_follow_up(quality_gate, company_data_audit)
    planner = FollowUpActionPlanner()
    candidate_actions = planner.plan(
        request,
        quality_gate=quality_gate,
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


@app.post("/reports/{report_id}/follow-up/run")
async def run_report_follow_up(report_id: int, payload: Optional[FollowUpRunRequest] = None) -> dict:
    payload = payload or FollowUpRunRequest()
    context = load_report_follow_up_context(report_id)
    request = context["request"]
    markdown = context["markdown"]
    quality_gate = context["quality_gate"]
    company_data_audit = context["company_data_audit"]
    candidate_audit_required = should_require_candidate_audit_follow_up(quality_gate, company_data_audit)
    planner = FollowUpActionPlanner()
    candidate_actions = planner.plan(
        request,
        quality_gate=quality_gate,
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
    if payload.rerun_report and execution_summary.get("rerun_blocked"):
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
        response = generator.generate(rerun_request)
        refreshed_quality_gate = build_quality_gate_for_request(
            rerun_request,
            documents=generator.last_evidence_documents,
            llm_result=getattr(generator, "last_llm_result", None),
            company_filing_sufficient_count=count_sufficient_company_filings(rerun_request.tickers),
        )
        response = attach_quality_gate_to_report(response, refreshed_quality_gate)
        with session_scope() as session:
            new_report = ReportRepository(session).create(rerun_request, response)
            new_report_id = new_report.id
        response_payload["rerun_report"] = {
            "report_id": new_report_id,
            "request": rerun_request.model_dump(mode="json"),
            "quality_gate": refreshed_quality_gate,
            "candidate_revalidation": rerun_context["candidate_revalidation"],
            "follow_up_section": render_follow_up_actions_markdown(
                FollowUpActionPlanner().plan(
                    rerun_request,
                    quality_gate=refreshed_quality_gate,
                    markdown=response.markdown,
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
            },
            report_id,
        )
        return {
            "run_id": run_id,
            "run_record_updated": run_record_updated,
            "report_id": report_id,
            "ingestion": ingestion_summary,
            "quality_gate": quality_gate,
            "report": response.model_dump(mode="json"),
        }
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
            document_limit=300,
        )
        urls = discovery_ingestion["urls"]
        start_date = discovery_ingestion["start_date"]
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
            candidate_filing_ingestion = await IngestionPipeline().ingest_mops_annual_reports(
                candidate_tickers,
                filter_allowed=False,
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
        promoted_tickers = [
            candidate["ticker"]
            for candidate in candidate_payload
            if candidate["status"] == "evidence_supported"
        ]
        dynamic_whitelist = SupplyChainWhitelist.from_candidate_whitelist(candidate_payload)
        company_filing_ingestion = (
            await IngestionPipeline().ingest_mops_annual_reports(
                promoted_tickers,
                filter_allowed=False,
            )
            if promoted_tickers
            else {
                "requested_tickers": [],
                "stored_count": 0,
                "per_ticker_results": [],
                "gap_summary": {"blocked_tickers": [], "retryable_tickers": []},
                "errors": [],
                "source": "Company filing discovery skipped: no promoted candidates",
            }
        )
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
        price_histories, market_errors = await market_client.get_price_histories_with_errors(
            promoted_tickers,
            start_date,
            end_date,
        )
        snapshots = [
            sorted(history, key=lambda snapshot: snapshot.trade_date)[-1]
            for history in price_histories.values()
            if history
        ]
        price_history_snapshots = [snapshot for history in price_histories.values() for snapshot in history]
        monthly_revenues, monthly_revenue_errors = await market_client.get_monthly_revenue_histories_with_errors(
            promoted_tickers,
            end_date - timedelta(days=450),
            end_date,
        )
        financial_metrics, financial_metric_errors = await market_client.get_financial_metrics_histories_with_errors(
            promoted_tickers,
            end_date - timedelta(days=365 * 6),
            end_date,
        )
        valuations, valuation_errors = await market_client.get_latest_valuations_with_errors(
            promoted_tickers,
            start_date,
            end_date,
        )
        monthly_tickers = {revenue.ticker for revenue in monthly_revenues}
        valuation_tickers = {valuation.ticker for valuation in valuations}
        leading_signal_count = sum(
            1
            for ticker in promoted_tickers
            if price_histories.get(ticker) or ticker in monthly_tickers or ticker in valuation_tickers
        )
        with session_scope() as session:
            MarketRepository(session).upsert_snapshots(price_history_snapshots)
            monthly_repository = MonthlyRevenueRepository(session)
            monthly_repository.upsert_revenues(monthly_revenues)
            FinancialMetricRepository(session).upsert_metrics(financial_metrics)
            ValuationMetricRepository(session).upsert_valuations(valuations)
            latest_monthly_revenues = monthly_repository.latest_by_tickers(promoted_tickers)
        request = ReportRequest(
            topic=payload.topic,
            tickers=promoted_tickers,
            lookback_days=payload.lookback_days,
            evidence_limit=evidence_limit,
            investor_capital=payload.investor_capital,
            beginner_mode=payload.beginner_mode,
            investor_profile=payload.investor_profile,
            max_position_pct=payload.max_position_pct,
            cash_reserve_pct=payload.cash_reserve_pct,
        )
        generator = ReportGenerator(whitelist=dynamic_whitelist)
        response = generator.generate(request, documents=documents)
        quality_gate = build_report_quality_gate(
            source_audit,
            promoted_tickers,
            market_count=len(snapshots),
            monthly_revenue_count=len(latest_monthly_revenues),
            financial_metrics_count=len(financial_metrics),
            valuation_count=len(valuations),
            investor_capital=payload.investor_capital,
            cash_reserve_pct=payload.cash_reserve_pct,
            source_quality=summarize_document_source_quality(documents, payload.lookback_days),
            plan_quality=source_audit.get("plan_quality"),
            leading_signal_count=leading_signal_count,
            llm_status=summarize_llm_status(generator.last_llm_result),
            company_filing_sufficient_count=sum(
                1
                for row in company_filing_ingestion.get("per_ticker_results", [])
                if row.get("status") == "sufficient"
            ),
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
            "valuation_errors": [error.model_dump() for error in valuation_errors],
            "quality_gate": quality_gate,
        }
        run_record_updated = safe_update_run_success(run_id, run_payload, report_id)
        return {
            "run_id": run_id,
            "run_record_updated": run_record_updated,
            "report_id": report_id,
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
            "report": response.model_dump(mode="json"),
        }
    except Exception as exc:
        safe_mark_run_failed(run_id, str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/reports/generate_async")
def generate_report_async(request: ReportRequest) -> dict:
    if not EntityMapper().filter_allowed_tickers(request.tickers):
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
