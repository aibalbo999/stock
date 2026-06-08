from __future__ import annotations


def follow_up_completion_status(task: str, result: dict) -> dict:
    action_type = task.split(":", 1)[0]
    stored_count = _stored_count(result)
    errors = result.get("errors") or []
    error_count = len(errors) if isinstance(errors, list) else 0
    stale_source_count = int(result.get("stale_source_count") or 0)
    if action_type == "ingest_company_filings":
        blocked = ((result.get("gap_summary") or {}).get("blocked_tickers") or [])
        return {
            "check": "company_filing_quality",
            "completed": stored_count > 0 and not blocked,
            "observed": {"stored_count": stored_count, "blocked_tickers": blocked},
            "required": {"min_documents": 1, "blocked_tickers": []},
        }
    if action_type == "refresh_market":
        return {
            "check": "market_history_coverage",
            "completed": stored_count >= 120 and error_count == 0 and stale_source_count == 0,
            "observed": _refresh_completion_observed(stored_count, error_count, stale_source_count),
            "required": _refresh_completion_required("min_days", 120, stale_source_count),
        }
    if action_type == "refresh_monthly_revenue":
        return {
            "check": "monthly_revenue_coverage",
            "completed": stored_count >= 12 and error_count == 0 and stale_source_count == 0,
            "observed": _refresh_completion_observed(stored_count, error_count, stale_source_count),
            "required": _refresh_completion_required("min_months", 12, stale_source_count),
        }
    if action_type == "refresh_financial_metrics":
        return {
            "check": "financial_metric_coverage",
            "completed": stored_count >= 5 and error_count == 0 and stale_source_count == 0,
            "observed": _refresh_completion_observed(stored_count, error_count, stale_source_count),
            "required": _refresh_completion_required("min_years", 5, stale_source_count),
        }
    if action_type == "refresh_valuations":
        return {
            "check": "valuation_availability",
            "completed": stored_count > 0 and error_count == 0 and stale_source_count == 0,
            "observed": _refresh_completion_observed(stored_count, error_count, stale_source_count),
            "required": _refresh_completion_required("min_records", 1, stale_source_count),
        }
    if action_type == "ingest_news":
        target_tickers = [ticker for ticker in task.split(":", 1)[1].split(",") if ticker] if ":" in task else []
        matched_count = _matched_target_item_count(
            result.get("items") or [],
            target_tickers,
            result.get("target_terms") or [],
        )
        coverage_fallback_count = int(result.get("coverage_fallback_count") or 0)
        completed = stored_count > 0 and matched_count > 0
        if not target_tickers and coverage_fallback_count > 0:
            completed = stored_count > 0
        return {
            "check": "company_evidence_sources",
            "completed": completed,
            "observed": {
                "stored_count": stored_count,
                "matched_target_count": matched_count,
                "coverage_fallback_count": coverage_fallback_count,
                "error_count": error_count,
            },
            "required": {"min_documents": 1, "min_matched_target_documents": 1},
        }
    if action_type == "rerun_discovery":
        status = result.get("status")
        return {
            "check": "candidate_revalidation_ready",
            "completed": status in {"planned", "completed", "ready"},
            "observed": {"status": status},
            "required": {"status": "planned_or_ready"},
        }
    return {
        "check": "manual_review",
        "completed": stored_count > 0 and error_count == 0,
        "observed": {"stored_count": stored_count, "error_count": error_count},
        "required": {"manual_review": True},
    }


def _refresh_completion_observed(stored_count: int, error_count: int, stale_source_count: int) -> dict:
    observed = {"stored_count": stored_count, "error_count": error_count}
    if stale_source_count:
        observed["stale_source_count"] = stale_source_count
    return observed


def _refresh_completion_required(count_key: str, count_value: int, stale_source_count: int) -> dict:
    required = {count_key: count_value, "error_count": 0}
    if stale_source_count:
        required["stale_source_count"] = 0
    return required


def _stored_count(result: dict) -> int:
    for key in ("stored_history_count", "stored_count", "count"):
        value = result.get(key)
        if isinstance(value, int):
            return value
    stored = result.get("stored")
    if isinstance(stored, list):
        return len(stored)
    latest = result.get("latest")
    if isinstance(latest, list):
        return len(latest)
    return 0


def _matched_target_item_count(items: list, target_tickers: list[str], target_terms: list[str] | None = None) -> int:
    if not target_tickers and not target_terms:
        return len(items)
    targets = set(target_tickers)
    text_terms = [
        term.lower()
        for term in [*target_tickers, *(target_terms or [])]
        if term
    ]
    matched = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        matches = item.get("entity_matches") or []
        if any(isinstance(match, dict) and match.get("ticker") in targets for match in matches):
            matched += 1
            continue
        haystack = " ".join(
            str(item.get(key) or "")
            for key in ["title", "publisher", "url", "id", "excerpt", "text"]
        ).lower()
        if haystack and any(term in haystack for term in text_terms):
            matched += 1
    return matched
