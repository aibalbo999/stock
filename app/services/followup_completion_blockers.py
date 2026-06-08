from __future__ import annotations


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
