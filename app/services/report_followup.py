from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from app.core.time import TAIPEI_TZ
from app.models.schemas import ReportRequest
from app.services.candidate_confidence import is_low_formal_confidence
from app.services.candidate_audit import render_candidate_audit_markdown
from app.services.followup_actions import company_filing_document_types_from_reason
from app.services.workflow_checkpoint import workflow_run_summary


def serialize_run(run: Any) -> dict:
    payload = parse_run_payload(run.payload_json)
    workflow = payload.get("workflow") if isinstance(payload.get("workflow"), dict) else None
    workflow_orchestration = (
        payload.get("workflow_orchestration")
        if isinstance(payload.get("workflow_orchestration"), dict)
        else None
    )
    return {
        "id": run.id,
        "source": run.source,
        "status": run.status,
        "payload": run.payload_json,
        "workflow": workflow,
        "workflow_summary": workflow_run_summary(workflow),
        "workflow_orchestration": workflow_orchestration,
        "report_id": run.report_id,
        "output_path": run.output_path,
        "error": run.error,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def parse_run_payload(run_payload_json: str | None) -> dict:
    if not run_payload_json:
        return {}
    try:
        payload = json.loads(run_payload_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def report_tickers(report: Any) -> list[str]:
    try:
        tickers = json.loads(report.tickers_json)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(ticker) for ticker in tickers if str(ticker).strip()]


def datetime_identity_value(
    value: datetime | None,
    *,
    naive_timezone=timezone.utc,
) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.replace(tzinfo=naive_timezone).astimezone(timezone.utc).replace(tzinfo=None)


def datetime_iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def latest_follow_up_run_for_report(
    repository: Any,
    report: Any,
    report_repository: Any | None = None,
) -> dict | None:
    latest = getattr(repository, "latest", None)
    if not callable(latest):
        return None
    matches = []
    for run in latest(100):
        payload = parse_run_payload(run.payload_json)
        if _follow_up_run_matches_report(run, payload, report) and _rerun_report_matches_report(
            payload,
            report,
            report_repository,
        ):
            matches.append((run, payload))
    if not matches:
        return None
    run, payload = max(matches, key=lambda item: _run_completion_identity_value(item[0]))
    return {
        **serialize_run(run),
        "source_report_id": payload.get("source_report_id"),
        "source_report_topic": payload.get("source_report_topic"),
        "source_report_tickers": payload.get("source_report_tickers") or [],
        "summary": payload.get("summary") or {},
        "planned_actions": payload.get("planned_actions") or [],
        "rerun_report": payload.get("rerun_report"),
    }


def matching_follow_up_rerun_report_id(
    auto_follow_up: dict | None,
    source_report_id: int | str | None,
    *,
    source_topic: str | None = None,
    source_tickers: list[str] | None = None,
) -> int | None:
    if not isinstance(auto_follow_up, dict):
        return None
    if source_report_id is not None:
        recorded_source_id = auto_follow_up.get("source_report_id")
        if recorded_source_id is not None and str(recorded_source_id) != str(source_report_id):
            return None
    recorded_source_topic = auto_follow_up.get("source_report_topic")
    if source_topic:
        if not recorded_source_topic or str(recorded_source_topic) != str(source_topic):
            return None
    recorded_source_tickers = auto_follow_up.get("source_report_tickers")
    if source_tickers:
        if not isinstance(recorded_source_tickers, list) or not recorded_source_tickers:
            return None
        if [str(ticker) for ticker in recorded_source_tickers] != [str(ticker) for ticker in source_tickers]:
            return None
    rerun_report = auto_follow_up.get("rerun_report")
    if not isinstance(rerun_report, dict):
        return None
    rerun_request = rerun_report.get("request") if isinstance(rerun_report.get("request"), dict) else {}
    rerun_topic = rerun_request.get("topic") or rerun_report.get("topic")
    if source_topic and not rerun_topic:
        return None
    if source_topic and rerun_topic and str(rerun_topic) != str(source_topic):
        return None
    rerun_report_id = rerun_report.get("report_id")
    if rerun_report_id is None:
        return None
    try:
        return int(rerun_report_id)
    except (TypeError, ValueError):
        return None


def request_from_report_record(
    topic: str,
    tickers: list[str],
    run_payload_json: str | None = None,
) -> ReportRequest:
    payload = parse_run_payload(run_payload_json)
    if payload:
        request_payload = payload.get("request") if isinstance(payload, dict) else None
        if isinstance(request_payload, dict):
            return ReportRequest.model_validate(request_payload)
    return ReportRequest(topic=topic, tickers=tickers)


def candidate_audit_from_run_payload(payload: dict) -> list[dict]:
    candidates = payload.get("candidate_whitelist") or []
    return candidates if isinstance(candidates, list) else []


def append_candidate_audit_if_missing(
    markdown: str,
    candidates: list[dict],
    promoted_tickers: list[str],
) -> str:
    if not candidates or "\n## 候選公司審計" in f"\n{markdown}":
        return markdown
    return (
        markdown.rstrip()
        + "\n\n## 候選公司審計\n"
        + render_candidate_audit_markdown(candidates, promoted_tickers)
    )


def sync_candidate_audit_section(
    markdown: str,
    candidates: list[dict],
    promoted_tickers: list[str],
) -> str:
    if not candidates:
        return markdown
    section = "\n\n## 候選公司審計\n" + render_candidate_audit_markdown(candidates, promoted_tickers)
    pattern = re.compile(r"\n## 候選公司審計\n.*?(?=\n## |\Z)", re.DOTALL)
    source = f"\n{markdown}"
    match = pattern.search(source)
    if not match:
        return markdown.rstrip() + section
    synced = source[: match.start()].rstrip() + section + source[match.end() :]
    return synced.lstrip("\n")


def candidate_audit_has_data_gaps(candidates: list[dict] | None) -> bool:
    return any(
        candidate.get("status") in {"weak_evidence", "needs_evidence", "evidence_unavailable"}
        for candidate in (candidates or [])
        if candidate.get("ticker")
    )


def should_require_candidate_audit_follow_up(
    quality_gate: dict,
    company_data_audit: dict,
    candidates: list[dict] | None = None,
) -> bool:
    if company_data_audit and company_data_audit.get("status") != "sufficient":
        return True
    if candidate_audit_has_data_gaps(candidates):
        return True
    if quality_gate.get("status") == "ready":
        return False
    metrics = quality_gate.get("metrics") or {}
    issue_text = "；".join(
        str(item)
        for item in [*(quality_gate.get("blockers") or []), *(quality_gate.get("warnings") or [])]
    )
    source_only_gap = (
        bool(issue_text)
        and "主題拆解子題" in issue_text
        and not any(term in issue_text for term in ["缺少候選公司", "正式分析股票", "候選公司證據覆蓋率低於"])
    )
    if (
        source_only_gap
        and int(metrics.get("promoted_count") or 0) > 0
        and float(metrics.get("candidate_supported_ratio") or 0) >= 0.6
        and metrics.get("discovery_plan_status") == "ready"
    ):
        return False
    return True


def summarize_candidate_support_payload(candidates: list[dict]) -> dict:
    total = len(candidates)
    supported = sum(1 for candidate in candidates if candidate.get("status") == "evidence_supported")
    weak = sum(1 for candidate in candidates if candidate.get("status") == "weak_evidence")
    unsupported = sum(1 for candidate in candidates if candidate.get("status") == "needs_evidence")
    unavailable = sum(1 for candidate in candidates if candidate.get("status") == "evidence_unavailable")
    limited = sum(1 for candidate in candidates if candidate.get("status") == "evidence_limited")
    supported_scores = [
        int(candidate.get("evidence_confidence_score") or 0)
        for candidate in candidates
        if candidate.get("status") == "evidence_supported"
    ]
    supported_ratio = supported / total if total else 0
    return {
        "total": total,
        "supported": supported,
        "weak": weak,
        "unsupported": unsupported,
        "unavailable": unavailable,
        "limited": limited,
        "supported_ratio": supported_ratio,
        "exploration_supported_ratio": supported_ratio,
        "formal_supported_ratio": 1.0 if supported else 0,
        "formal_confidence_avg": round(sum(supported_scores) / len(supported_scores), 1) if supported_scores else None,
        "formal_confidence_min": min(supported_scores) if supported_scores else None,
        "formal_low_confidence_count": sum(1 for score in supported_scores if is_low_formal_confidence(score)),
    }


def plan_quality_from_quality_gate(quality_gate: dict) -> dict | None:
    metrics = quality_gate.get("metrics") or {}
    status = metrics.get("discovery_plan_status")
    score = metrics.get("discovery_plan_score")
    if status is None and score is None:
        return None
    return {
        "status": status,
        "score": score,
    }


def can_rerun_candidate_revalidation_from_existing_evidence(context: dict, actions: list) -> bool:
    return bool(context.get("candidate_whitelist")) and any(
        action.action_type == "rerun_discovery"
        for action in actions
    )


def filter_follow_up_actions(actions: list, purpose: str) -> list:
    if purpose == "all":
        return actions
    selected = [action for action in actions if action.purpose == purpose]
    if selected and not any(action.action_type == "rerun_analysis" for action in selected):
        rerun = next((action for action in actions if action.action_type == "rerun_analysis"), None)
        if rerun is not None:
            selected.append(rerun)
    return selected


def follow_up_action_summary(actions: list) -> dict:
    required_count = sum(1 for action in actions if action.purpose == "required")
    tracking_count = sum(1 for action in actions if action.purpose == "tracking")
    return {
        "required_count": required_count,
        "tracking_count": tracking_count,
        "total_count": len(actions),
    }


def follow_up_plan_next_actions(actions: list) -> list[dict]:
    rows = []
    for action in actions:
        target = follow_up_plan_action_target(action)
        if target is None:
            continue
        rows.append(
            {
                "action": action.action_type,
                "tickers": list(action.tickers),
                "target": target,
                "priority": action.priority,
                "purpose": action.purpose,
                "reason": action.reason,
                "next_step": follow_up_plan_action_next_step(action),
                "completion_criteria": follow_up_plan_action_completion_criteria(action),
                "completion_checks": follow_up_plan_action_completion_checks(action),
            }
        )
    return rows


def follow_up_plan_action_target(action: Any) -> str | None:
    if action.action_type == "ingest_company_filings":
        document_types = company_filing_document_types_from_reason(action.reason) or []
        return "、".join(document_types) if document_types else "公司公開文件"
    targets = {
        "ingest_news": "新聞/研究/產業證據",
        "refresh_market": "股價與量能",
        "refresh_monthly_revenue": "月營收",
        "refresh_financial_metrics": "五年財務資料",
        "refresh_valuations": "估值資料",
        "rerun_discovery": "AI 主題拆解與候選白名單",
        "rerun_analysis": "完整投資報告",
    }
    return targets.get(action.action_type)


def follow_up_plan_action_next_step(action: Any) -> str:
    steps = {
        "ingest_news": "依股票與主題補抓設定回看區間內的多來源資料，補足公司層級證據。",
        "ingest_company_filings": "先自動搜尋官方/MOPS/IR 文件；若仍不足，系統會列出需人工匯入的文件。",
        "refresh_market": "刷新近 120 天股價、量能與波動資料，用於目前情境降值分與進出場檢查。",
        "refresh_monthly_revenue": "補齊近月營收序列，用於成長加速或轉弱判斷。",
        "refresh_financial_metrics": "補齊多年財報指標，用於財務體質、利潤率與負債檢查。",
        "refresh_valuations": "刷新本益比、股價淨值比與殖利率，用於同業估值比較。",
        "rerun_discovery": "重新拆解主題與候選公司，確認白名單是否需調整。",
        "rerun_analysis": "在補資料後重新產生報告；若仍有關鍵缺口，系統會先暫停重跑。",
    }
    return steps.get(action.action_type, "依任務設定補齊資料後再評估是否重跑報告。")


def follow_up_plan_action_completion_criteria(action: Any) -> str:
    criteria = {
        "ingest_news": "每檔至少補到 2 個以上來源或足以支撐/排除產業鏈關聯的回看區間內證據。",
        "ingest_company_filings": "每檔至少有必要類型的高品質官方文件；若仍缺件，列入人工匯入清單。",
        "refresh_market": "目標股票近 120 天內有可用股價與量能資料。",
        "refresh_monthly_revenue": "目標股票至少取得近 12 個月月營收資料。",
        "refresh_financial_metrics": "目標股票取得足以做 5 年趨勢判斷的財務期數。",
        "refresh_valuations": "目標股票取得最新本益比、股價淨值比或可比較估值資料。",
        "rerun_discovery": "主題拆解、候選白名單與排除原因重新產出並通過基本品質檢查。",
        "rerun_analysis": "補強後無關鍵 blocker，才重新產生完整投資報告。",
    }
    return criteria.get(action.action_type, "補強結果可被資料審計或品質閘門確認。")


def follow_up_plan_action_completion_checks(action: Any) -> list[dict]:
    if action.action_type == "ingest_company_filings":
        document_types = company_filing_document_types_from_reason(action.reason) or []
        return [
            {
                "check": "company_filing_quality",
                "required_document_types": document_types,
                "min_quality_score": 70,
                "min_documents_per_ticker": 1,
            }
        ]
    checks = {
        "ingest_news": [
            {"check": "company_evidence_sources", "min_sources_per_ticker": 2},
        ],
        "refresh_market": [
            {"check": "market_history_coverage", "min_days": 120},
        ],
        "refresh_monthly_revenue": [
            {"check": "monthly_revenue_coverage", "min_months": 12},
        ],
        "refresh_financial_metrics": [
            {"check": "financial_metric_coverage", "min_years": 5},
        ],
        "refresh_valuations": [
            {"check": "valuation_availability", "required_fields": ["pe_ratio", "pb_ratio"]},
        ],
        "rerun_discovery": [
            {"check": "candidate_revalidation_ready"},
        ],
        "rerun_analysis": [
            {"check": "quality_gate_no_blockers"},
        ],
    }
    return checks.get(action.action_type, [{"check": "manual_review"}])


def _follow_up_run_matches_report(run: Any, payload: dict, report: Any) -> bool:
    if run.source != "follow_up_api":
        return False
    if payload.get("source_report_id") != report.id:
        return False

    rerun_report = payload.get("rerun_report") if isinstance(payload.get("rerun_report"), dict) else {}
    rerun_report_id = rerun_report.get("report_id")
    linked_report_id = getattr(run, "report_id", None)
    if rerun_report_id is not None:
        if linked_report_id is None:
            return False
        if str(linked_report_id) != str(rerun_report_id):
            return False

    source_topic = payload.get("source_report_topic")
    if source_topic and source_topic != report.topic:
        return False
    request_payload = payload.get("request") if isinstance(payload.get("request"), dict) else {}
    request_topic = request_payload.get("topic")
    if request_topic and request_topic != report.topic:
        return False

    tickers = report_tickers(report)
    source_tickers = payload.get("source_report_tickers")
    request_tickers = request_payload.get("tickers")
    candidate_tickers = source_tickers if isinstance(source_tickers, list) and source_tickers else request_tickers
    if isinstance(candidate_tickers, list) and candidate_tickers and tickers:
        if [str(ticker) for ticker in candidate_tickers] != tickers:
            return False

    generated_at = datetime_identity_value(getattr(report, "generated_at", None), naive_timezone=TAIPEI_TZ)
    started_at = datetime_identity_value(getattr(run, "started_at", None), naive_timezone=timezone.utc)
    if generated_at and started_at and started_at < generated_at:
        return False
    return True


def _run_completion_identity_value(run: Any) -> datetime:
    value = getattr(run, "finished_at", None) or getattr(run, "started_at", None)
    return datetime_identity_value(value, naive_timezone=timezone.utc) or datetime.min


def _rerun_report_matches_report(
    payload: dict,
    report: Any,
    report_repository: Any | None = None,
) -> bool:
    rerun_report = payload.get("rerun_report") if isinstance(payload.get("rerun_report"), dict) else {}
    rerun_report_id = rerun_report.get("report_id") if isinstance(rerun_report, dict) else None
    rerun_request = rerun_report.get("request") if isinstance(rerun_report.get("request"), dict) else {}
    rerun_topic = rerun_request.get("topic") or rerun_report.get("topic")
    if rerun_topic and rerun_topic != getattr(report, "topic", None):
        return False
    if not rerun_report_id or report_repository is None:
        return True
    try:
        rerun = report_repository.get(int(rerun_report_id))
    except (TypeError, ValueError):
        return False
    if rerun is None:
        return False
    if getattr(rerun, "topic", None) != getattr(report, "topic", None):
        return False
    source_generated_at = datetime_identity_value(
        getattr(report, "generated_at", None),
        naive_timezone=TAIPEI_TZ,
    )
    rerun_generated_at = datetime_identity_value(
        getattr(rerun, "generated_at", None),
        naive_timezone=TAIPEI_TZ,
    )
    if source_generated_at and rerun_generated_at and rerun_generated_at < source_generated_at:
        return False
    return True
