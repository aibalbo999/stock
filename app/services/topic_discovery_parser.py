from __future__ import annotations

import json
import re

from pydantic import ValidationError

from app.services import topic_discovery_enrichment
from app.services.topic_discovery_models import TopicDiscoveryPlan


def parse_plan(raw_text: str) -> TopicDiscoveryPlan:
    json_text = extract_json(raw_text)
    try:
        return topic_discovery_enrichment.enrich_plan(
            TopicDiscoveryPlan.model_validate_json(json_text)
        )
    except (ValidationError, ValueError) as exc:
        raise ValueError("invalid topic discovery json") from exc


def extract_json(raw_text: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("json object not found")
    candidate = raw_text[start : end + 1]
    json.loads(candidate)
    return candidate


__all__ = ["extract_json", "parse_plan"]
