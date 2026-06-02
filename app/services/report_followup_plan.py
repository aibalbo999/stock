from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.services.followup_actions import (
    FollowUpActionPlanner,
    TRACKING_FRESHNESS_THRESHOLDS,
    render_follow_up_actions_markdown,
    split_fresh_tracking_actions,
)
from app.services.report_followup import (
    follow_up_action_summary,
    follow_up_plan_next_actions,
    should_require_candidate_audit_follow_up,
)


class ReportFollowUpPlanService:
    def __init__(
        self,
        *,
        load_report_follow_up_context_func: Callable[[int], dict],
        follow_up_action_planner_cls=FollowUpActionPlanner,
        should_require_candidate_audit_follow_up_func: Callable[[dict, dict, list | None], bool] = (
            should_require_candidate_audit_follow_up
        ),
        split_fresh_tracking_actions_func: Callable[[list, Any], tuple[list, list]] = (
            split_fresh_tracking_actions
        ),
        follow_up_action_summary_func: Callable[[list], dict] = follow_up_action_summary,
        follow_up_plan_next_actions_func: Callable[[list], list[dict]] = follow_up_plan_next_actions,
        render_follow_up_actions_markdown_func: Callable[[list], str] = render_follow_up_actions_markdown,
        tracking_freshness_thresholds: dict = TRACKING_FRESHNESS_THRESHOLDS,
    ) -> None:
        self.load_report_follow_up_context_func = load_report_follow_up_context_func
        self.follow_up_action_planner_cls = follow_up_action_planner_cls
        self.should_require_candidate_audit_follow_up_func = should_require_candidate_audit_follow_up_func
        self.split_fresh_tracking_actions_func = split_fresh_tracking_actions_func
        self.follow_up_action_summary_func = follow_up_action_summary_func
        self.follow_up_plan_next_actions_func = follow_up_plan_next_actions_func
        self.render_follow_up_actions_markdown_func = render_follow_up_actions_markdown_func
        self.tracking_freshness_thresholds = tracking_freshness_thresholds

    def build(self, report_id: int) -> dict:
        context = self.load_report_follow_up_context_func(report_id)
        request = context["request"]
        markdown = context["markdown"]
        quality_gate = context["quality_gate"]
        company_data_audit = context["company_data_audit"]
        source_audit = context["source_audit"]
        candidate_audit_required = self.should_require_candidate_audit_follow_up_func(
            quality_gate,
            company_data_audit,
            context.get("candidate_whitelist") or [],
        )
        candidate_actions = self.follow_up_action_planner_cls().plan(
            request,
            quality_gate=quality_gate,
            source_audit=source_audit,
            markdown=markdown,
            company_data_audit=company_data_audit,
            candidate_audit_required=candidate_audit_required,
            apply_freshness=False,
        )
        actions, skipped_details = self.split_fresh_tracking_actions_func(candidate_actions, request)
        skipped_action_payloads = [
            {key: value for key, value in detail.items() if key != "freshness"}
            for detail in skipped_details
        ]
        return {
            "report_id": report_id,
            "request": request.model_dump(mode="json"),
            "quality_gate_status": quality_gate.get("status"),
            "summary": self.follow_up_action_summary_func(actions),
            "freshness": {
                "skipped_count": len(skipped_details),
                "skipped_actions": skipped_action_payloads,
                "skipped_details": skipped_details,
                "thresholds": self.tracking_freshness_thresholds,
                "message": "部分追蹤更新因資料仍在新鮮範圍內而略過。" if skipped_details else None,
            },
            "actions": [action.to_dict() for action in actions],
            "next_actions": self.follow_up_plan_next_actions_func(actions),
            "markdown_preview": self.render_follow_up_actions_markdown_func(actions),
        }


class AutoFollowUpStartService:
    def __init__(
        self,
        *,
        settings_provider: Callable[[], Any],
        plan_provider: Callable[[int], dict],
        follow_up_run_request_cls: type,
        run_follow_up_func: Callable[[int, Any], Awaitable[dict]],
        background_runner_func: Callable[[int, Any], Awaitable[None]],
        create_task_func: Callable[[Awaitable[None]], Any],
    ) -> None:
        self.settings_provider = settings_provider
        self.plan_provider = plan_provider
        self.follow_up_run_request_cls = follow_up_run_request_cls
        self.run_follow_up_func = run_follow_up_func
        self.background_runner_func = background_runner_func
        self.create_task_func = create_task_func

    async def start(self, report_id: int, run_in_background: bool = True) -> dict:
        settings = self.settings_provider()
        if not settings.auto_follow_up_enabled:
            return {"status": "disabled", "reason": "AUTO_FOLLOW_UP_ENABLED=false"}

        plan = self.plan_provider(report_id)
        source_metadata = self._source_metadata(report_id, plan)
        required_count = int((plan.get("summary") or {}).get("required_count") or 0)
        if required_count <= 0:
            return {
                "status": "not_needed",
                "reason": (
                    "quality_gate_ready"
                    if plan.get("quality_gate_status") == "ready"
                    else "no_required_data_gap"
                ),
                "plan": {
                    "summary": plan.get("summary") or {},
                    "next_actions": plan.get("next_actions") or [],
                },
                **source_metadata,
            }

        payload = self.follow_up_run_request_cls(
            rerun_report=True,
            news_limit=settings.auto_follow_up_news_limit,
            purpose="required",
            record_noop=True,
        )
        if run_in_background:
            self.create_task_func(self.background_runner_func(report_id, payload))
            return {
                "status": "queued",
                "summary": {
                    "selected": plan.get("summary") or {},
                },
                "actions": plan.get("actions") or [],
                "next_actions": plan.get("next_actions") or [],
                **source_metadata,
            }

        try:
            result = await self.run_follow_up_func(report_id, payload)
        except Exception as exc:
            return {
                "status": "failed",
                "reason": str(exc),
                "plan": {
                    "summary": plan.get("summary") or {},
                    "next_actions": plan.get("next_actions") or [],
                },
                **source_metadata,
            }

        return {
            "status": "started",
            "run_id": result.get("run_id"),
            "summary": result.get("summary") or {},
            "freshness": result.get("freshness") or {},
            "actions": result.get("actions") or [],
            "rerun_report": result.get("rerun_report"),
            "results": result.get("results") or {},
            **source_metadata,
        }

    @staticmethod
    def _source_metadata(report_id: int, plan: dict) -> dict:
        request = plan.get("request") if isinstance(plan.get("request"), dict) else {}
        return {
            "source_report_id": report_id,
            "source_report_topic": request.get("topic"),
            "source_report_tickers": request.get("tickers") or [],
        }
