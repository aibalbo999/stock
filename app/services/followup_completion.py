from __future__ import annotations


def summarize_follow_up_execution(execution: dict) -> dict:
    results = execution.get("results") or {}
    rows = []
    total_errors = 0
    total_items = 0
    blocked_company_filing_tickers = []
    retryable_company_filing_tickers = []
    rerun_blocker_actions = []
    for key, value in results.items():
        if not isinstance(value, dict):
            rows.append(
                {
                    "task": key,
                    "stored_count": 0,
                    "error_count": 0,
                    "completion": follow_up_completion_status(key, {}),
                }
            )
            continue
        errors = value.get("errors") or []
        error_count = len(errors) if isinstance(errors, list) else 0
        stored_count = _stored_count(value)
        gap_summary = value.get("gap_summary") or {}
        blocked_company_filing_tickers.extend(gap_summary.get("blocked_tickers") or [])
        retryable_company_filing_tickers.extend(gap_summary.get("retryable_tickers") or [])
        rerun_blocker_actions.extend(value.get("next_actions") or [])
        total_errors += error_count
        total_items += stored_count
        rows.append(
            {
                "task": key,
                "stored_count": stored_count,
                "error_count": error_count,
                "source": value.get("source"),
                "target_terms": value.get("target_terms") or [],
                "completion": follow_up_completion_status(key, value),
            }
        )
    unique_blocked = sorted(set(blocked_company_filing_tickers))
    unique_retryable = sorted(set(retryable_company_filing_tickers))
    completion = summarize_follow_up_completion(rows)
    incomplete_tasks = [
        task
        for task in completion["blocked_tasks"]
        if not _nonblocking_partial_candidate_task(task, rows, unique_blocked, total_items)
    ]
    rerun_blockers = []
    if unique_blocked and total_items <= 0:
        rerun_blockers.append(f"公司公開文件仍不足：{', '.join(unique_blocked)}")
    if incomplete_tasks:
        rerun_blockers.append("補強任務未達完成條件：" + "、".join(incomplete_tasks))
        rerun_blocker_actions.extend(follow_up_completion_blocker_actions(rows, incomplete_tasks))
    return {
        "task_result_count": len(rows),
        "stored_count": total_items,
        "error_count": total_errors,
        "has_errors": total_errors > 0,
        "completion": completion,
        "rerun_blocked": bool(rerun_blockers),
        "rerun_blockers": rerun_blockers,
        "rerun_blocker_actions": rerun_blocker_actions,
        "retryable_company_filing_tickers": unique_retryable,
        "items": rows,
    }


def _nonblocking_partial_candidate_task(
    task: str,
    rows: list[dict],
    blocked_company_filing_tickers: list[str],
    total_items: int,
) -> bool:
    row = next((item for item in rows if item.get("task") == task), {})
    if task.startswith("ingest_news"):
        is_candidate_guard = row.get("source") == "follow-up action guard"
        completion = row.get("completion") or {}
        observed = completion.get("observed") or {}
        matched_target_count = int(observed.get("matched_target_count") or 0)
        return (bool(row.get("target_terms")) or is_candidate_guard) and total_items > 0 and (
            matched_target_count > 0
            or int(row.get("error_count") or 0) > 0
        )
    if task.startswith("ingest_company_filings") and blocked_company_filing_tickers and total_items <= 0:
        return True
    if task.startswith("ingest_company_filings") and blocked_company_filing_tickers and total_items > 0:
        return True
    if task.startswith("ingest_company_filings") and total_items > 0:
        is_candidate_guard = row.get("source") == "follow-up action guard"
        return (bool(row.get("target_terms")) or is_candidate_guard) and (
            int(row.get("error_count") or 0) > 0
        )
    return False


def follow_up_completion_blocker_actions(rows: list[dict], incomplete_tasks: list[str]) -> list[dict]:
    row_by_task = {row.get("task"): row for row in rows}
    actions = []
    for task in incomplete_tasks:
        row = row_by_task.get(task) or {}
        completion = row.get("completion") or {}
        action_type, _, ticker_text = task.partition(":")
        actions.append(
            {
                "ticker": ticker_text or "",
                "company_name": "",
                "action": "complete_follow_up_check",
                "task": task,
                "check": completion.get("check") or "manual_review",
                "target": follow_up_completion_target_label(action_type),
                "reason": follow_up_completion_reason(task, completion),
                "observed": completion.get("observed") or {},
                "required": completion.get("required") or {},
            }
        )
    return actions


def follow_up_completion_target_label(action_type: str) -> str:
    labels = {
        "ingest_news": "新聞/研究/產業證據",
        "ingest_company_filings": "公司公開文件",
        "refresh_market": "股價與量能",
        "refresh_monthly_revenue": "月營收",
        "refresh_financial_metrics": "五年財務資料",
        "refresh_valuations": "估值資料",
        "rerun_discovery": "AI 主題拆解與候選白名單",
    }
    return labels.get(action_type, action_type)


def follow_up_completion_reason(task: str, completion: dict) -> str:
    observed = completion.get("observed") or {}
    required = completion.get("required") or {}
    return f"{task} 未達完成條件；目前 {observed}，要求 {required}。"


def summarize_follow_up_completion(rows: list[dict]) -> dict:
    completed = sum(1 for row in rows if (row.get("completion") or {}).get("completed"))
    blocked = [
        row["task"]
        for row in rows
        if not (row.get("completion") or {}).get("completed")
    ]
    return {
        "completed_count": completed,
        "total_count": len(rows),
        "all_completed": bool(rows) and completed == len(rows),
        "blocked_tasks": blocked,
    }


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
