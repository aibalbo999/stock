from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.time import utc_now_naive
from app.db.models import (
    AnalysisRun,
    GeneratedReport,
    LLMUsageRecord,
)
from app.services.company_filing_repository import (
    CompanyFilingRepository as CompanyFilingRepository,
)
from app.services.market_repositories import (
    FinancialMetricRepository as FinancialMetricRepository,
    MarketRepository as MarketRepository,
    MonthlyRevenueRepository as MonthlyRevenueRepository,
    ValuationMetricRepository as ValuationMetricRepository,
)
from app.services.news_repository import NewsRepository as NewsRepository
from app.services.risk_classification_repository import (
    RiskClassificationRepository as RiskClassificationRepository,
)
from app.services.report_repository import ReportRepository as ReportRepository
from app.services.task_failure_diagnostics import (
    parse_payload as parse_task_payload,
    task_failure_diagnostic_payload,
)


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
