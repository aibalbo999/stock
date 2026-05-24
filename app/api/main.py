from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.time import today_taipei
from app.data_sources.market import MarketDataClient
from app.data_sources.news import NewsFetcher, NewsSourceStore
from app.db.status import db_status
from app.db.session import init_db, session_scope
from app.models.schemas import ReportRequest, ReportResponse
from app.rag.vector_store import VectorStore
from app.services.entity_mapping import EntityMapper
from app.services.ingestion import IngestionPipeline
from app.services.persistence import (
    AnalysisRunRepository,
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
    max_queries = 30
    if payload.deep_analysis:
        limit_per_query = max(limit_per_query, 12)
        evidence_limit = max(evidence_limit, 120)
        max_queries = 80
    return limit_per_query, evidence_limit, max_queries


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
) -> dict:
    dynamic_summary = summarize_ingestion_stage(dynamic_query_ingestion)
    fixed_summary = summarize_ingestion_stage([fixed_source_ingestion])
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
        "total_stored_count": fixed_summary["stored_count"] + dynamic_summary["stored_count"],
        "total_error_count": fixed_summary["error_count"] + dynamic_summary["error_count"],
    }


def summarize_candidate_support(candidates) -> dict:
    total = len(candidates)
    supported = sum(1 for candidate in candidates if candidate.status == "evidence_supported")
    weak = sum(1 for candidate in candidates if candidate.status == "weak_evidence")
    unsupported = total - supported
    return {
        "total": total,
        "supported": supported,
        "weak": weak,
        "unsupported": unsupported,
        "supported_ratio": supported / total if total else 0,
    }


def should_supplement_discovery_sources(source_audit: dict, candidate_support: dict) -> bool:
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
        "supplemental_rounds": 3 if deep_analysis else 2,
        "supplemental_batch_size": 12 if deep_analysis else 6,
    }


async def ingest_dynamic_news_urls(
    urls: list[str],
    limit_per_query: int,
    start_date: date,
    end_date: date,
) -> list[dict]:
    ingestion_results = []
    for url in urls:
        ingestion_results.append(
            await IngestionPipeline().ingest_feeds(
                url=url,
                publisher=None,
                limit=limit_per_query,
                start_date=start_date,
                end_date=end_date,
            )
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
    urls = service.google_news_urls(
        plan,
        include_international=payload.include_international,
        max_urls=budget["initial_queries"],
    )
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
    candidate_support = {"total": 0, "supported": 0, "unsupported": 0, "supported_ratio": 0}
    source_audit = build_source_audit(
        payload,
        urls,
        fixed_source_ingestion,
        dynamic_query_ingestion,
        limit_per_query,
        evidence_limit,
        max_queries,
    )

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
        candidate_support = summarize_candidate_support(candidates)
        source_audit = build_source_audit(
            payload,
            urls,
            fixed_source_ingestion,
            dynamic_query_ingestion,
            limit_per_query,
            evidence_limit,
            max_queries,
        )
        if not should_supplement_discovery_sources(source_audit, candidate_support):
            break
        remaining_queries = max_queries - len(urls)
        if remaining_queries <= 0 or round_index >= budget["supplemental_rounds"]:
            break
        supplemental_urls = service.supplemental_google_news_urls(
            plan,
            candidates,
            include_international=payload.include_international,
            max_urls=min(remaining_queries, budget["supplemental_batch_size"]),
            existing_urls=urls,
        )
        if not supplemental_urls:
            break
        supplemental_ingestion = await ingest_dynamic_news_urls(
            supplemental_urls,
            limit_per_query,
            start_date,
            end_date,
        )
        urls.extend(supplemental_urls)
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
    )
    source_audit["candidate_support"] = candidate_support
    source_audit["remediation"] = {
        "supplemented": bool(remediation_rounds),
        "reason": "low_candidate_or_source_coverage" if remediation_rounds else "coverage_sufficient",
        "rounds": remediation_rounds,
        "supplemental_query_count": sum(round_item["query_count"] for round_item in remediation_rounds),
        "supplemental_stored_count": sum(round_item["stored_count"] for round_item in remediation_rounds),
    }
    source_audit["query_budget"] = budget
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
    }


@app.post("/discovery/topic-plan")
def discovery_topic_plan(payload: TopicDiscoveryRequest) -> dict:
    return TopicDiscoveryService().discover(payload.topic)


@app.post("/discovery/ingest")
async def discovery_ingest(payload: TopicDiscoveryRequest) -> dict:
    service = TopicDiscoveryService()
    discovery = service.discover(payload.topic)
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
        return {
            "id": report.id,
            "title": report.title,
            "topic": report.topic,
            "generated_at": report.generated_at.isoformat(),
            "markdown": report.markdown,
            "quality_gate": parse_quality_gate_from_markdown(report.markdown),
        }


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
        discovery = service.discover(payload.topic)
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
        promoted_tickers = [
            candidate["ticker"]
            for candidate in candidate_payload
            if candidate["status"] == "evidence_supported"
        ]
        dynamic_whitelist = SupplyChainWhitelist.from_candidate_whitelist(candidate_payload)

        market_client = MarketDataClient()
        snapshots, market_errors = await market_client.get_latest_snapshots_with_errors(
            promoted_tickers,
            start_date,
            end_date,
        )
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
        with session_scope() as session:
            MarketRepository(session).upsert_snapshots(snapshots)
            monthly_repository = MonthlyRevenueRepository(session)
            monthly_repository.upsert_revenues(monthly_revenues)
            FinancialMetricRepository(session).upsert_metrics(financial_metrics)
            ValuationMetricRepository(session).upsert_valuations(valuations)
            latest_monthly_revenues = monthly_repository.latest_by_tickers(promoted_tickers)
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
        )

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
        response = ReportGenerator(whitelist=dynamic_whitelist).generate(request, documents=documents)
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
            "source_audit": source_audit,
            "candidate_whitelist": candidate_payload,
            "market": [snapshot.model_dump(mode="json") for snapshot in snapshots],
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
            "source_audit": source_audit,
            "candidate_whitelist": candidate_payload,
            "promoted_tickers": promoted_tickers,
            "market": [snapshot.model_dump(mode="json") for snapshot in snapshots],
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
