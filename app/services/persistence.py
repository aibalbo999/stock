from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.time import utc_now_naive
from app.db.models import (
    AnalysisRun,
    CompanyFiling,
    GeneratedReport,
    LLMUsageRecord,
    NewsArticle,
    RiskClassificationCache,
)
from app.models.schemas import (
    CompanyFilingDocument,
    NewsDocument,
    ReportRequest,
    ReportResponse,
    RiskFinding,
    Source,
)
from app.services.market_repositories import (
    FinancialMetricRepository as FinancialMetricRepository,
    MarketRepository as MarketRepository,
    MonthlyRevenueRepository as MonthlyRevenueRepository,
    ValuationMetricRepository as ValuationMetricRepository,
)
from app.services.report_integrity import assert_report_integrity
from app.services.source_quality import (
    is_formal_evidence_source,
    remove_low_quality_investor_forum_lines,
)
from app.services.task_failure_diagnostics import (
    parse_payload as parse_task_payload,
    task_failure_diagnostic_payload,
)


class NewsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_document(self, document: NewsDocument, entity_matches: list[dict]) -> NewsArticle:
        values = {
            "title": document.title,
            "text": document.text,
            "publisher": document.source.publisher,
            "url": document.source.url,
            "published_at": document.source.published_at,
            "fetched_at": document.source.fetched_at,
            "entity_matches_json": json.dumps(entity_matches, ensure_ascii=False),
        }
        return self.session.merge(NewsArticle(id=document.id, **values))

    def upsert_document_merging_matches(
        self, document: NewsDocument, entity_matches: list[dict]
    ) -> NewsArticle:
        existing = self.session.get(NewsArticle, document.id)
        merged_matches = self._merge_entity_matches(
            json.loads(existing.entity_matches_json) if existing else [],
            entity_matches,
        )
        return self.upsert_document(document, merged_matches)

    @staticmethod
    def _merge_entity_matches(existing: list[dict], incoming: list[dict]) -> list[dict]:
        merged: dict[tuple[str, str], dict] = {}
        for item in [*existing, *incoming]:
            ticker = str(item.get("ticker") or "")
            segment_id = str(item.get("segment_id") or "")
            if not ticker:
                continue
            merged[(ticker, segment_id)] = item
        return list(merged.values())

    def latest_documents(self, limit: int = 20) -> list[NewsDocument]:
        statement = select(NewsArticle).order_by(NewsArticle.created_at.desc()).limit(limit)
        return [self._to_document(article) for article in self.session.scalars(statement)]

    def search_documents(self, query: str, limit: int = 20) -> list[NewsDocument]:
        terms = [term for term in query.split() if term]
        statement = select(NewsArticle).order_by(NewsArticle.created_at.desc()).limit(limit * 3)
        documents = [self._to_document(article) for article in self.session.scalars(statement)]
        if not terms:
            return documents[:limit]
        ranked = [
            document
            for document in documents
            if any(term in document.title or term in document.text for term in terms)
        ]
        return ranked[:limit]

    @staticmethod
    def _to_document(article: NewsArticle) -> NewsDocument:
        entity_matches = _parse_entity_matches(article.entity_matches_json)
        return NewsDocument(
            id=article.id,
            title=article.title,
            text=article.text,
            source=Source(
                title=article.title,
                url=article.url,
                publisher=article.publisher,
                published_at=article.published_at,
                fetched_at=article.fetched_at,
            ),
            entity_tickers=_entity_match_values(entity_matches, "ticker"),
            entity_names=_entity_match_values(entity_matches, "name"),
        )


class CompanyFilingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_document(self, document: CompanyFilingDocument) -> CompanyFiling:
        row = self.session.get(CompanyFiling, document.id)
        values = {
            "ticker": document.ticker,
            "company_name": document.company_name,
            "document_type": document.document_type,
            "title": document.title,
            "text": document.text,
            "publisher": document.source.publisher,
            "url": document.source.url,
            "published_at": document.source.published_at,
            "fetched_at": document.source.fetched_at,
        }
        if row is None:
            row = CompanyFiling(id=document.id, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        return row

    def latest_by_tickers(
        self, tickers: list[str], limit_per_ticker: int = 5
    ) -> list[CompanyFilingDocument]:
        documents: list[CompanyFilingDocument] = []
        for ticker in tickers:
            statement = (
                select(CompanyFiling)
                .where(CompanyFiling.ticker == ticker)
                .order_by(
                    CompanyFiling.published_at.desc().nullslast(), CompanyFiling.created_at.desc()
                )
                .limit(limit_per_ticker)
            )
            documents.extend(self._to_document(row) for row in self.session.scalars(statement))
        return documents

    def search_documents(
        self, query: str, tickers: list[str] | None = None, limit: int = 20
    ) -> list[CompanyFilingDocument]:
        terms = [term for term in query.split() if term]
        statement = select(CompanyFiling).order_by(
            CompanyFiling.published_at.desc().nullslast(),
            CompanyFiling.created_at.desc(),
        )
        if tickers:
            statement = statement.where(CompanyFiling.ticker.in_(tickers))
        rows = list(self.session.scalars(statement.limit(limit * 4)))
        if terms:
            rows = [
                row
                for row in rows
                if any(
                    term in row.title or term in row.text or term == row.ticker for term in terms
                )
            ]
        return [self._to_document(row) for row in rows[:limit]]

    def stats_by_ticker(self, ticker: str) -> dict:
        rows = list(
            self.session.scalars(select(CompanyFiling).where(CompanyFiling.ticker == ticker))
        )
        latest = max((row.published_at for row in rows if row.published_at), default=None)
        return {
            "rows": len(rows),
            "document_types": sorted({row.document_type for row in rows}),
            "publishers": len({row.publisher or row.url or row.title for row in rows}),
            "latest_date": latest.isoformat() if latest else None,
        }

    @staticmethod
    def _to_document(row: CompanyFiling) -> CompanyFilingDocument:
        return CompanyFilingDocument(
            id=row.id,
            ticker=row.ticker,
            company_name=row.company_name,
            document_type=row.document_type,
            title=row.title,
            text=row.text,
            source=Source(
                title=row.title,
                url=row.url,
                publisher=row.publisher,
                published_at=row.published_at,
                fetched_at=row.fetched_at,
            ),
        )

    @staticmethod
    def to_news_document(document: CompanyFilingDocument) -> NewsDocument:
        label = f"公司公開文件/{document.document_type}"
        company = f"{document.ticker} {document.company_name or ''}".strip()
        text = (
            f"股票代號：{document.ticker}\n"
            f"公司名稱：{document.company_name or ''}\n"
            f"文件類型：{document.document_type}\n"
            f"{company}\n"
            f"{document.text}"
        )
        return NewsDocument(
            id=f"filing-{document.id}",
            title=document.title,
            text=text,
            source=Source(
                title=document.title,
                url=document.source.url,
                publisher=document.source.publisher or label,
                published_at=document.source.published_at,
                fetched_at=document.source.fetched_at,
            ),
            entity_tickers=[document.ticker],
            entity_names=[document.company_name] if document.company_name else [],
        )


def _parse_entity_matches(value: str | None) -> list[dict]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _entity_match_values(matches: list[dict], key: str) -> list[str]:
    values = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        value = str(match.get(key) or "").strip()
        if value:
            values.append(value)
    return list(dict.fromkeys(values))


def _formal_report_findings(findings: list[RiskFinding]) -> list[RiskFinding]:
    return [
        finding
        for finding in findings
        if is_formal_evidence_source(
            title=finding.source.title,
            publisher=finding.source.publisher,
            url=finding.source.url,
            source_title=finding.source.title,
            text=f"{finding.topic}\n{finding.evidence}",
        )
    ]


class ReportRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, request: ReportRequest, response: ReportResponse) -> GeneratedReport:
        markdown = remove_low_quality_investor_forum_lines(response.markdown)
        assert_report_integrity(markdown)
        findings = _formal_report_findings(response.findings)
        report = GeneratedReport(
            title=response.title,
            topic=request.topic,
            tickers_json=json.dumps(request.tickers, ensure_ascii=False),
            findings_json=json.dumps(
                [finding.model_dump(mode="json") for finding in findings],
                ensure_ascii=False,
            ),
            markdown=markdown,
            quality_gate_json=(
                json.dumps(response.quality_gate, ensure_ascii=False)
                if response.quality_gate
                else None
            ),
            generated_at=response.generated_at,
        )
        self.session.add(report)
        self.session.flush()
        self.prune_older_for_topic(report.topic, report.id)
        return report

    def latest(self, limit: int = 20) -> list[GeneratedReport]:
        statement = (
            select(GeneratedReport)
            .order_by(GeneratedReport.generated_at.desc(), GeneratedReport.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def latest_by_topic(self, limit: int = 20) -> list[GeneratedReport]:
        ranked_reports = select(
            GeneratedReport.id.label("report_id"),
            func.row_number()
            .over(
                partition_by=GeneratedReport.topic,
                order_by=(GeneratedReport.generated_at.desc(), GeneratedReport.id.desc()),
            )
            .label("topic_rank"),
        ).subquery()
        statement = (
            select(GeneratedReport)
            .join(ranked_reports, GeneratedReport.id == ranked_reports.c.report_id)
            .where(ranked_reports.c.topic_rank == 1)
            .order_by(GeneratedReport.generated_at.desc(), GeneratedReport.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def get(self, report_id: int) -> GeneratedReport | None:
        return self.session.get(GeneratedReport, report_id)

    def delete(self, report_id: int) -> bool:
        report = self.session.get(GeneratedReport, report_id)
        if report is None:
            return False
        self._clear_analysis_run_report_links([report_id])
        self.session.delete(report)
        self.session.flush()
        return True

    def delete_before(self, before: datetime) -> int:
        old_report_ids = list(
            self.session.scalars(
                select(GeneratedReport.id).where(GeneratedReport.generated_at < before)
            )
        )
        if not old_report_ids:
            return 0
        self._clear_analysis_run_report_links(old_report_ids)
        result = self.session.execute(
            delete(GeneratedReport).where(GeneratedReport.id.in_(old_report_ids))
        )
        self.session.flush()
        return result.rowcount or 0

    def prune_older_by_topic(self) -> int:
        reports = list(
            self.session.scalars(
                select(GeneratedReport).order_by(
                    GeneratedReport.generated_at.desc(),
                    GeneratedReport.id.desc(),
                )
            )
        )
        seen_topics: set[str] = set()
        old_report_ids: list[int] = []
        for report in reports:
            if report.topic in seen_topics:
                old_report_ids.append(report.id)
                continue
            seen_topics.add(report.topic)
        if not old_report_ids:
            return 0
        self._clear_analysis_run_report_links(old_report_ids)
        result = self.session.execute(
            delete(GeneratedReport).where(GeneratedReport.id.in_(old_report_ids))
        )
        self.session.flush()
        return result.rowcount or 0

    def prune_older_for_topic(self, topic: str, keep_report_id: int) -> int:
        statement = select(GeneratedReport.id).where(
            GeneratedReport.topic == topic,
            GeneratedReport.id != keep_report_id,
        )
        old_report_ids = list(self.session.scalars(statement))
        if not old_report_ids:
            return 0
        self._clear_analysis_run_report_links(old_report_ids)
        result = self.session.execute(
            delete(GeneratedReport).where(GeneratedReport.id.in_(old_report_ids))
        )
        self.session.flush()
        return result.rowcount or 0

    def _clear_analysis_run_report_links(self, report_ids: list[int]) -> None:
        if not report_ids:
            return
        self.session.execute(
            update(AnalysisRun)
            .where(AnalysisRun.report_id.in_(report_ids))
            .values(report_id=None, output_path=None)
        )


class RiskClassificationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, document_id: str, topic_hash: str) -> dict | None:
        row = self.session.get(
            RiskClassificationCache, {"document_id": document_id, "topic_hash": topic_hash}
        )
        if row is None:
            return None
        return {
            "document_id": row.document_id,
            "topic_hash": row.topic_hash,
            "classification": row.classification,
            "topic": row.topic,
            "evidence": row.evidence,
            "confidence": row.confidence,
            "keywords": json.loads(row.keywords_json),
            "model": row.model,
        }

    def upsert(
        self,
        document_id: str,
        topic_hash: str,
        classification: str,
        topic: str,
        evidence: str,
        confidence: float,
        keywords: list[str],
        model: str | None,
    ) -> RiskClassificationCache:
        row = self.session.get(
            RiskClassificationCache, {"document_id": document_id, "topic_hash": topic_hash}
        )
        values = {
            "classification": classification,
            "topic": topic,
            "evidence": evidence,
            "confidence": confidence,
            "keywords_json": json.dumps(keywords, ensure_ascii=False),
            "model": model,
            "updated_at": utc_now_naive(),
        }
        if row is None:
            row = RiskClassificationCache(document_id=document_id, topic_hash=topic_hash, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        self.session.flush()
        return row


class AnalysisRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def start(self, source: str, payload: dict) -> AnalysisRun:
        run = AnalysisRun(
            source=source,
            status="running",
            payload_json=json.dumps(payload, ensure_ascii=False),
            started_at=utc_now_naive(),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def mark_success(
        self,
        run_id: int,
        report_id: int | None,
        output_path: str | None = None,
    ) -> AnalysisRun:
        run = self.session.get(AnalysisRun, run_id)
        if run is None:
            raise ValueError(f"analysis run not found: {run_id}")
        run.status = "success"
        run.report_id = report_id
        run.output_path = output_path
        run.finished_at = utc_now_naive()
        self._clear_task_failure_diagnostic(run)
        self.session.flush()
        return run

    def update_payload(self, run_id: int, payload: dict) -> AnalysisRun:
        run = self.session.get(AnalysisRun, run_id)
        if run is None:
            raise ValueError(f"analysis run not found: {run_id}")
        run.payload_json = json.dumps(payload, ensure_ascii=False)
        self.session.flush()
        return run

    def mark_running(self, run_id: int) -> AnalysisRun:
        run = self.session.get(AnalysisRun, run_id)
        if run is None:
            raise ValueError(f"analysis run not found: {run_id}")
        run.status = "running"
        run.error = None
        run.finished_at = None
        self._clear_task_failure_diagnostic(run)
        self.session.flush()
        return run

    def mark_failed(self, run_id: int, error: str) -> AnalysisRun:
        run = self.session.get(AnalysisRun, run_id)
        if run is None:
            raise ValueError(f"analysis run not found: {run_id}")
        run.status = "failed"
        run.error = error
        run.finished_at = utc_now_naive()
        self._store_task_failure_diagnostic(run, status="failed", error=error)
        self.session.flush()
        return run

    def mark_cancelled(
        self, run_id: int, reason: str = "task cancellation requested"
    ) -> AnalysisRun:
        run = self.session.get(AnalysisRun, run_id)
        if run is None:
            raise ValueError(f"analysis run not found: {run_id}")
        run.status = "cancelled"
        run.error = reason
        run.finished_at = utc_now_naive()
        self._store_task_failure_diagnostic(run, status="cancelled", error=reason)
        self.session.flush()
        return run

    @staticmethod
    def _payload_dict(run: AnalysisRun) -> dict:
        return parse_task_payload(run.payload_json)

    def _store_task_failure_diagnostic(self, run: AnalysisRun, *, status: str, error: str) -> None:
        payload = self._payload_dict(run)
        diagnostic = task_failure_diagnostic_payload(
            run_id=run.id,
            source=run.source,
            payload=payload,
            status=status,
            error=error,
        )
        if diagnostic:
            payload["task_failure_diagnostic"] = diagnostic
            run.payload_json = json.dumps(payload, ensure_ascii=False)

    def _clear_task_failure_diagnostic(self, run: AnalysisRun) -> None:
        payload = self._payload_dict(run)
        if payload.pop("task_failure_diagnostic", None) is not None:
            run.payload_json = json.dumps(payload, ensure_ascii=False)

    def latest(self, limit: int = 20) -> list[AnalysisRun]:
        statement = select(AnalysisRun).order_by(AnalysisRun.started_at.desc()).limit(limit)
        return list(self.session.scalars(statement))

    def since(self, started_at: datetime, limit: int = 500) -> list[AnalysisRun]:
        statement = (
            select(AnalysisRun)
            .where(AnalysisRun.started_at >= started_at)
            .order_by(AnalysisRun.started_at.desc())
            .limit(max(1, int(limit)))
        )
        return list(self.session.scalars(statement))

    def get(self, run_id: int) -> AnalysisRun | None:
        return self.session.get(AnalysisRun, run_id)

    def get_by_report_id(self, report_id: int) -> AnalysisRun | None:
        statement = (
            select(AnalysisRun)
            .where(AnalysisRun.report_id == report_id)
            .order_by(AnalysisRun.started_at.desc())
            .limit(1)
        )
        return self.session.scalars(statement).first()

    def output_paths_for_report(self, report_id: int) -> list[str]:
        statement = (
            select(AnalysisRun.output_path)
            .where(AnalysisRun.report_id == report_id, AnalysisRun.output_path.is_not(None))
            .order_by(AnalysisRun.started_at.desc())
        )
        return [str(path) for path in self.session.scalars(statement) if path]

    def get_by_celery_task_id(self, task_id: str) -> AnalysisRun | None:
        statement = select(AnalysisRun).order_by(AnalysisRun.started_at.desc())
        for run in self.session.scalars(statement):
            try:
                payload = json.loads(run.payload_json)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("celery_task_id") == task_id:
                return run
        return None

    def delete(self, run_id: int) -> bool:
        run = self.session.get(AnalysisRun, run_id)
        if run is None:
            return False
        self.session.delete(run)
        self.session.flush()
        return True

    def delete_failed(self) -> int:
        result = self.session.execute(delete(AnalysisRun).where(AnalysisRun.status == "failed"))
        self.session.flush()
        return result.rowcount or 0

    def mark_stale_running_failed(self, before: datetime, error: str = "run timed out") -> int:
        statement = select(AnalysisRun).where(
            AnalysisRun.status == "running",
            AnalysisRun.started_at < before,
        )
        stale_runs = list(self.session.scalars(statement))
        finished_at = utc_now_naive()
        for run in stale_runs:
            run.status = "failed"
            run.error = error
            run.finished_at = finished_at
        self.session.flush()
        return len(stale_runs)

    def delete_before(self, before: datetime) -> int:
        result = self.session.execute(delete(AnalysisRun).where(AnalysisRun.started_at < before))
        self.session.flush()
        return result.rowcount or 0

    def orphan_report_ids(self) -> list[int]:
        statement = (
            select(AnalysisRun.id)
            .outerjoin(GeneratedReport, AnalysisRun.report_id == GeneratedReport.id)
            .where(AnalysisRun.report_id.is_not(None), GeneratedReport.id.is_(None))
        )
        return list(self.session.scalars(statement))

    def clear_orphan_report_refs(self) -> int:
        orphan_ids = self.orphan_report_ids()
        if not orphan_ids:
            return 0
        result = self.session.execute(
            update(AnalysisRun)
            .where(AnalysisRun.id.in_(orphan_ids))
            .values(report_id=None, output_path=None)
        )
        self.session.flush()
        return result.rowcount or 0


class LLMUsageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_from_report_execution(
        self,
        *,
        operation: str,
        report_execution: dict | None,
        report_id: int | None = None,
        run_id: int | None = None,
    ) -> LLMUsageRecord | None:
        llm = (report_execution or {}).get("llm") if isinstance(report_execution, dict) else None
        if not isinstance(llm, dict):
            return None
        observability = (
            llm.get("observability") if isinstance(llm.get("observability"), dict) else {}
        )
        attempt_summary = (
            llm.get("attempt_summary") if isinstance(llm.get("attempt_summary"), dict) else {}
        )
        attempts = llm.get("attempts") if isinstance(llm.get("attempts"), list) else []
        models_tried = (
            attempt_summary.get("models_tried") if isinstance(attempt_summary, dict) else []
        )
        if not isinstance(models_tried, list):
            models_tried = []
        row = LLMUsageRecord(
            operation=str(operation or "unknown")[:80],
            report_id=report_id,
            run_id=run_id,
            provider=_string_or_none(llm.get("provider"), max_length=80),
            model=_string_or_none(llm.get("model"), max_length=160),
            fallback=bool(llm.get("fallback")),
            latency_ms=_float_or_none(observability.get("latency_ms")),
            input_token_estimate=_int_or_none(observability.get("input_token_estimate")),
            output_token_estimate=_int_or_none(observability.get("output_token_estimate")),
            total_token_estimate=_int_or_none(observability.get("total_token_estimate")),
            estimated_cost_usd=_float_or_none(observability.get("estimated_cost_usd")),
            cost_tracking_mode=_string_or_none(
                observability.get("cost_tracking_mode"), max_length=80
            ),
            attempt_count=_int_or_none(attempt_summary.get("attempt_count")),
            retryable_failure_count=_int_or_none(attempt_summary.get("retryable_failure_count")),
            fallback_path_used=bool(attempt_summary.get("fallback_path_used")),
            primary_failure_category=_string_or_none(
                attempt_summary.get("primary_failure_category"),
                max_length=120,
            ),
            models_tried_json=json.dumps(models_tried, ensure_ascii=False),
            attempts_json=json.dumps(attempts[-10:], ensure_ascii=False),
            observability_json=json.dumps(observability, ensure_ascii=False),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def latest(self, limit: int = 50) -> list[LLMUsageRecord]:
        statement = select(LLMUsageRecord).order_by(LLMUsageRecord.created_at.desc()).limit(limit)
        return list(self.session.scalars(statement))

    def since(self, created_at: datetime) -> list[LLMUsageRecord]:
        statement = (
            select(LLMUsageRecord)
            .where(LLMUsageRecord.created_at >= created_at)
            .order_by(LLMUsageRecord.created_at.asc())
        )
        return list(self.session.scalars(statement))

    @staticmethod
    def to_dict(row: LLMUsageRecord) -> dict:
        return {
            "id": row.id,
            "operation": row.operation,
            "report_id": row.report_id,
            "run_id": row.run_id,
            "provider": row.provider,
            "model": row.model,
            "fallback": row.fallback,
            "latency_ms": row.latency_ms,
            "input_token_estimate": row.input_token_estimate,
            "output_token_estimate": row.output_token_estimate,
            "total_token_estimate": row.total_token_estimate,
            "estimated_cost_usd": row.estimated_cost_usd,
            "cost_tracking_mode": row.cost_tracking_mode,
            "attempt_count": row.attempt_count,
            "retryable_failure_count": row.retryable_failure_count,
            "fallback_path_used": row.fallback_path_used,
            "primary_failure_category": row.primary_failure_category,
            "models_tried": _loads_json_list(row.models_tried_json),
            "attempts": _loads_json_list(row.attempts_json),
            "observability": _loads_json_dict(row.observability_json),
            "created_at": row.created_at.isoformat(),
        }


def _string_or_none(value: object, *, max_length: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_length]


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _loads_json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def _loads_json_dict(value: str | None) -> dict:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
