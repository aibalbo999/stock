from __future__ import annotations

import json

import requests

from app.services.report_quality import parse_quality_gate_from_markdown
from app.ui.api_client import api_get


def hydrate_active_report_result(result: dict) -> dict:
    source_report_id = result.get("report_id")
    active_report_id = result.get("active_report_id") or source_report_id
    if active_report_id:
        payload = report_payload_or_none(active_report_id)
        if payload and report_topics_match(result, payload):
            return hydrate_report_result_from_payload(result, payload, source_report_id)

    latest_payload = latest_report_payload_for_topic(result)
    if latest_payload:
        return hydrate_report_result_from_payload(result, latest_payload, source_report_id)
    return result


def report_payload_or_none(report_id) -> dict | None:
    try:
        payload = api_get(f"/reports/{int(report_id)}")
    except (TypeError, ValueError, requests.RequestException):
        return None
    return payload if isinstance(payload, dict) else None


def latest_report_payload_for_topic(result: dict) -> dict | None:
    current_topic = result_topic(result)
    if not current_topic:
        return None
    try:
        reports = api_get("/reports?limit=50")
    except requests.RequestException:
        return None
    if not isinstance(reports, list):
        return None
    for report in reports:
        if not isinstance(report, dict):
            continue
        if str(report.get("topic") or "").strip() != current_topic:
            continue
        return report_payload_or_none(report.get("id"))
    return None


def result_topic(result: dict) -> str:
    return str(result.get("topic") or (result.get("request") or {}).get("topic") or "").strip()


def report_topics_match(result: dict, payload: dict) -> bool:
    current_topic = result_topic(result)
    active_topic = str(payload.get("topic") or (payload.get("request") or {}).get("topic") or "").strip()
    return not (current_topic and active_topic and current_topic != active_topic)


def hydrate_report_result_from_payload(result: dict, payload: dict, source_report_id) -> dict:
    report_id = payload.get("id") or payload.get("report_id") or source_report_id
    hydrated = {
        **result,
        "report_id": report_id,
        "source_report_id": source_report_id,
        "topic": payload.get("topic") or result.get("topic"),
        "tickers": payload.get("tickers") or result.get("promoted_tickers") or [],
        "request": payload.get("request") or result.get("request") or {},
        "quality_gate": payload.get("quality_gate") or parse_quality_gate_from_markdown(payload.get("markdown") or ""),
        "auto_follow_up": payload.get("auto_follow_up"),
        "candidate_whitelist": payload.get("candidate_whitelist") or result.get("candidate_whitelist") or [],
        "candidate_audit": payload.get("candidate_audit") or result.get("candidate_audit") or {},
        "report": {
            **(result.get("report") or {}),
            "title": payload.get("title") or (result.get("report") or {}).get("title"),
            "markdown": payload.get("markdown") or (result.get("report") or {}).get("markdown"),
        },
    }
    return hydrated


def parse_json_object(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
