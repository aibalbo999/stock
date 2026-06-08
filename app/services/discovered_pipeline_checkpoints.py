from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from app.models.schemas import NewsDocument
from app.services.report_generator import ReportExecutionError

__all__ = [
    "date_from_checkpoint",
    "documents_from_payload",
    "documents_payload",
    "json_safe",
    "parse_checkpoint_payload_json",
    "payload_from_checkpoint",
    "payload_model_dump",
    "resume_report_id",
]


def parse_checkpoint_payload_json(payload_json: str | None) -> dict:
    if not payload_json:
        return {}
    try:
        payload = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def resume_report_id(run: Any, payload: dict) -> int:
    value = getattr(run, "report_id", None) or payload.get("report_id")
    try:
        report_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ReportExecutionError(
            "ai_discovered_topic_pipeline resume requires an existing report_id"
        ) from exc
    if report_id <= 0:
        raise ReportExecutionError(
            "ai_discovered_topic_pipeline resume requires an existing report_id"
        )
    return report_id


def payload_model_dump(payload: Any) -> dict:
    dump = getattr(payload, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except TypeError:
            return dump()
    if isinstance(payload, dict):
        return dict(payload)
    return {
        key: value
        for key, value in vars(payload).items()
        if not key.startswith("_") and not callable(value)
    }


def payload_from_checkpoint(checkpoint: dict) -> Any:
    raw = checkpoint.get("pipeline_request")
    if not isinstance(raw, dict):
        raw = checkpoint.get("request") if isinstance(checkpoint.get("request"), dict) else {}
    if not raw:
        request_keys = {
            "topic",
            "limit_per_query",
            "lookback_days",
            "evidence_limit",
            "analysis_mode",
            "deep_analysis",
            "include_international",
            "investor_capital",
            "beginner_mode",
            "investor_profile",
            "max_position_pct",
            "cash_reserve_pct",
        }
        raw = {key: checkpoint[key] for key in request_keys if key in checkpoint}
    defaults = {
        "topic": "AI 產業鏈",
        "limit_per_query": 5,
        "lookback_days": 14,
        "evidence_limit": 40,
        "analysis_mode": "standard",
        "deep_analysis": False,
        "include_international": True,
        "investor_capital": 1_000_000,
        "beginner_mode": True,
        "investor_profile": "beginner",
        "max_position_pct": 0.10,
        "cash_reserve_pct": 0.30,
    }
    return PayloadAdapter({**defaults, **raw})


class PayloadAdapter:
    def __init__(self, data: dict) -> None:
        self.__dict__.update(data)

    def model_dump(self, mode=None):
        return dict(self.__dict__)


def json_safe(value: Any) -> Any:
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except TypeError:
            return dump()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def date_from_checkpoint(value: Any) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ReportExecutionError(
                "ai_discovered_topic_pipeline resume requires valid discovery_end_date"
            ) from exc
    raise ReportExecutionError("ai_discovered_topic_pipeline resume requires discovery_end_date")


def documents_payload(documents: list) -> list:
    return [json_safe(document) for document in documents]


def documents_from_payload(documents: list) -> list:
    restored = []
    for document in documents:
        if isinstance(document, dict) and {"id", "title", "text", "source"}.issubset(document):
            restored.append(NewsDocument.model_validate(document))
        else:
            restored.append(document)
    return restored
