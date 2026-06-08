from __future__ import annotations

from app.core.async_bridge import run_async_from_sync
from app.core.time import today_taipei
from app.db.session import session_scope
from app.models.schemas import ReportRequest
from app.services import followup_executor as _followup_executor
from app.services import followup_freshness as _followup_freshness
from app.services import followup_planning_rules as _followup_planning_rules
from app.services.followup_completion import (
    follow_up_completion_blocker_actions as follow_up_completion_blocker_actions,
    follow_up_completion_reason as follow_up_completion_reason,
    follow_up_completion_status as follow_up_completion_status,
    follow_up_completion_target_label as follow_up_completion_target_label,
    summarize_follow_up_completion as summarize_follow_up_completion,
    summarize_follow_up_execution as summarize_follow_up_execution,
)
from app.services.followup_evidence import (
    company_filing_document_types_from_reason as company_filing_document_types_from_reason,
    company_name_from_follow_up_reason as company_name_from_follow_up_reason,
    follow_up_news_queries as follow_up_news_queries,
    follow_up_target_terms as follow_up_target_terms,
    ingest_follow_up_news as ingest_follow_up_news,
    needs_company_filing_sources as needs_company_filing_sources,
)
from app.services.followup_freshness import TRACKING_FRESHNESS_THRESHOLDS as TRACKING_FRESHNESS_THRESHOLDS
from app.services.followup_executor import (
    FOLLOW_UP_ACTION_CONCURRENCY as FOLLOW_UP_ACTION_CONCURRENCY,
    FOLLOW_UP_ACTION_TIMEOUT_SECONDS as FOLLOW_UP_ACTION_TIMEOUT_SECONDS,
)
from app.services.ingestion import IngestionPipeline
from app.services.followup_models import (
    FOLLOW_UP_ACTION_LABELS as FOLLOW_UP_ACTION_LABELS,
    ActionType as ActionType,
    FollowUpAction as FollowUpAction,
    manual_tracking_follow_up_actions as manual_tracking_follow_up_actions,
)


TRACKING_CANDIDATE_LIMIT = 5


class FollowUpActionPlanner:
    def plan(
        self,
        request: ReportRequest,
        quality_gate: dict | None = None,
        source_audit: dict | None = None,
        markdown: str = "",
        contexts: list[dict] | None = None,
        company_data_audit: dict | None = None,
        candidate_audit_required: bool = True,
        apply_freshness: bool = True,
    ) -> list[FollowUpAction]:
        tickers = tuple(request.tickers)
        actions: list[FollowUpAction] = []
        actions.extend(self.from_quality_gate(quality_gate or {}, tickers))
        actions.extend(self.from_source_audit(source_audit or {}, tickers))
        actions.extend(self.from_company_data_audit(company_data_audit or {}, tickers))
        actions.extend(self.from_monitoring_contexts(contexts or [], tickers))
        actions.extend(self.from_monitoring_markdown(markdown, tickers))
        actions.extend(self.from_candidate_audit_markdown(markdown, tickers, required=candidate_audit_required))
        if actions and not any(action.action_type == "rerun_analysis" for action in actions):
            purpose = "required" if any(action.purpose == "required" for action in actions) else "tracking"
            reason = (
                "補強資料完成後自動重跑分析，讓投資結論反映最新資料。"
                if purpose == "required"
                else "追蹤資料更新後重跑分析，確認投資結論是否需要調整。"
            )
            actions.append(
                FollowUpAction(
                    "rerun_analysis",
                    reason,
                    tickers,
                    "high",
                    "once",
                    purpose,
                )
            )
        actions = dedupe_actions(actions)
        return filter_fresh_tracking_actions(actions, request) if apply_freshness else actions

    def from_source_audit(self, source_audit: dict, tickers: tuple[str, ...]) -> list[FollowUpAction]:
        return _followup_planning_rules.from_source_audit(source_audit, tickers, FollowUpAction)

    def from_quality_gate(self, quality_gate: dict, tickers: tuple[str, ...]) -> list[FollowUpAction]:
        return _followup_planning_rules.from_quality_gate(quality_gate, tickers, FollowUpAction)

    def from_company_data_audit(self, audit: dict, fallback_tickers: tuple[str, ...]) -> list[FollowUpAction]:
        return _followup_planning_rules.from_company_data_audit(audit, fallback_tickers, FollowUpAction)

    def from_monitoring_contexts(self, contexts: list[dict], fallback_tickers: tuple[str, ...]) -> list[FollowUpAction]:
        return _followup_planning_rules.from_monitoring_contexts(contexts, fallback_tickers, FollowUpAction)

    def from_monitoring_markdown(self, markdown: str, fallback_tickers: tuple[str, ...]) -> list[FollowUpAction]:
        return _followup_planning_rules.from_monitoring_markdown(markdown, fallback_tickers, FollowUpAction)

    def from_candidate_audit_markdown(
        self,
        markdown: str,
        fallback_tickers: tuple[str, ...],
        required: bool = True,
    ) -> list[FollowUpAction]:
        return _followup_planning_rules.from_candidate_audit_markdown(
            markdown,
            fallback_tickers,
            FollowUpAction,
            required=required,
            candidate_limit=TRACKING_CANDIDATE_LIMIT,
        )


def dedupe_actions(actions: list[FollowUpAction]) -> list[FollowUpAction]:
    merged: dict[tuple[str, tuple[str, ...]], FollowUpAction] = {}
    priority_rank = {"low": 0, "medium": 1, "high": 2}
    purpose_rank = {"tracking": 0, "required": 1}
    for action in actions:
        key = action.key()
        existing = merged.get(key)
        if existing is None:
            merged[key] = action
            continue
        priority = action.priority if priority_rank[action.priority] > priority_rank[existing.priority] else existing.priority
        purpose = action.purpose if purpose_rank[action.purpose] > purpose_rank[existing.purpose] else existing.purpose
        reason = existing.reason if existing.reason == action.reason else f"{existing.reason}；{action.reason}"
        merged[key] = FollowUpAction(action.action_type, reason, action.tickers, priority, existing.frequency, purpose)
    return list(merged.values())


def filter_fresh_tracking_actions(actions: list[FollowUpAction], request: ReportRequest) -> list[FollowUpAction]:
    return _followup_freshness.filter_fresh_tracking_actions(
        actions,
        request,
        split_func=split_fresh_tracking_actions,
    )


def skipped_fresh_tracking_actions(actions: list[FollowUpAction], request: ReportRequest) -> list[FollowUpAction]:
    return _followup_freshness.skipped_fresh_tracking_actions(
        actions,
        request,
        freshness_details_func=tracking_freshness_details_by_action,
    )


def tracking_freshness_by_action(actions: list[FollowUpAction], request: ReportRequest) -> dict[tuple[str, tuple[str, ...]], bool]:
    return _followup_freshness.tracking_freshness_by_action(
        actions,
        request,
        freshness_details_func=tracking_freshness_details_by_action,
    )


def tracking_freshness_details_by_action(actions: list[FollowUpAction], request: ReportRequest) -> dict[tuple[str, tuple[str, ...]], dict]:
    return _followup_freshness.tracking_freshness_details_by_action(
        actions,
        request,
        session_scope_func=session_scope,
        today_func=today_taipei,
        thresholds=TRACKING_FRESHNESS_THRESHOLDS,
    )


def skipped_fresh_tracking_details(actions: list[FollowUpAction], request: ReportRequest) -> list[dict]:
    _, rows = split_fresh_tracking_actions(actions, request)
    return rows


def split_fresh_tracking_actions(
    actions: list[FollowUpAction],
    request: ReportRequest,
) -> tuple[list[FollowUpAction], list[dict]]:
    return _followup_freshness.split_fresh_tracking_actions(
        actions,
        request,
        freshness_details_func=tracking_freshness_details_by_action,
    )


def render_follow_up_actions_markdown(actions: list[FollowUpAction]) -> str:
    if not actions:
        return "目前沒有需要系統自動補強的任務。"
    lines = [
        "系統會把品質缺口與監控條件轉成以下自動補強任務；補強完成後再重新產生報告，避免只把問題列出來卻沒有處理。",
        "",
        "| 任務 | 股票 | 性質 | 優先級 | 頻率 | 觸發原因 |",
        "|---|---|---|---|---|---|",
    ]
    for action in actions:
        tickers = "、".join(action.tickers) if action.tickers else "全主題"
        purpose = "資料缺口補強" if action.purpose == "required" else "追蹤更新"
        lines.append(
            f"| {FOLLOW_UP_ACTION_LABELS.get(action.action_type, action.action_type)} | {tickers} | {purpose} | {action.priority} | "
            f"{action.frequency} | {action.reason} |"
        )
    return "\n".join(lines)


async def execute_follow_up_actions(
    actions: list[FollowUpAction],
    request: ReportRequest,
    news_limit: int = 30,
) -> dict:
    return await _followup_executor.execute_follow_up_actions(
        actions,
        request,
        news_limit,
        pipeline_factory=IngestionPipeline,
        today_func=today_taipei,
        concurrency=FOLLOW_UP_ACTION_CONCURRENCY,
        timeout_seconds=FOLLOW_UP_ACTION_TIMEOUT_SECONDS,
        summarize_execution_func=summarize_follow_up_execution,
        single_action_executor=execute_single_follow_up_action,
        error_result_func=follow_up_action_error_result,
    )


def execute_follow_up_actions_sync(actions: list[FollowUpAction], request: ReportRequest, news_limit: int = 30) -> dict:
    return run_async_from_sync(
        execute_follow_up_actions(actions, request, news_limit),
        operation="follow_up.execute_actions",
    )


async def execute_single_follow_up_action(
    action: FollowUpAction,
    request: ReportRequest,
    news_limit: int,
    today,
) -> dict:
    return await _followup_executor.execute_single_follow_up_action(
        action,
        request,
        news_limit,
        today,
        pipeline_factory=IngestionPipeline,
        error_result_func=follow_up_action_error_result,
    )


def follow_up_result_key(action: FollowUpAction, request: ReportRequest) -> str:
    return _followup_executor.follow_up_result_key(action, request)


def follow_up_action_error_result(
    action: FollowUpAction,
    tickers: list[str],
    message: str,
    category: str,
) -> dict:
    return _followup_executor.follow_up_action_error_result(action, tickers, message, category)
