from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import LLMUsageRecord


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


__all__ = ["LLMUsageRepository"]
