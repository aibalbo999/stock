from __future__ import annotations

from app.services.followup_completion_blockers import (
    follow_up_completion_blocker_actions as follow_up_completion_blocker_actions,
    follow_up_completion_reason as follow_up_completion_reason,
    follow_up_completion_target_label as follow_up_completion_target_label,
)
from app.services.followup_completion_checks import (
    _matched_target_item_count as _matched_target_item_count,
    _stored_count as _stored_count,
    follow_up_completion_status as follow_up_completion_status,
)


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
