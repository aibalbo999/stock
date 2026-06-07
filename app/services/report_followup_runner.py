from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.services.followup_actions import manual_tracking_follow_up_actions
from app.services.llm_usage import record_llm_usage_from_report_execution
from app.services.report_generator import ReportExecutionError
from app.services.report_followup import (
    can_rerun_candidate_revalidation_from_existing_evidence,
    filter_follow_up_actions,
    follow_up_action_summary,
    plan_quality_from_quality_gate,
    should_require_candidate_audit_follow_up,
    summarize_candidate_support_payload,
)
from app.services.task_cancellation import TaskCancelledError, raise_if_task_cancelled


class ReportFollowUpRunService:
    def __init__(
        self,
        *,
        session_scope_factory: Callable,
        analysis_run_repository_cls: type,
        report_repository_cls: type,
        follow_up_action_planner_cls: type,
        load_report_follow_up_context_func: Callable[[int], dict],
        prepare_follow_up_report_context_func: Callable[[dict, Any, list], Awaitable[dict]],
        execute_follow_up_actions_func: Callable[..., Awaitable[dict]],
        summarize_follow_up_execution_func: Callable[[dict], dict],
        split_fresh_tracking_actions_func: Callable[[list, Any], tuple[list, list]],
        render_follow_up_actions_markdown_func: Callable[[list], str],
        report_build_service_factory: Callable[[], Any],
        count_sufficient_company_filings_func: Callable[[list[str]], int],
        safe_mark_run_failed_func: Callable[[int, str], None],
        tracking_freshness_thresholds: dict,
        task_cancellation_checker: Callable[[int], None] | None = None,
    ) -> None:
        self.session_scope_factory = session_scope_factory
        self.analysis_run_repository_cls = analysis_run_repository_cls
        self.report_repository_cls = report_repository_cls
        self.follow_up_action_planner_cls = follow_up_action_planner_cls
        self.load_report_follow_up_context_func = load_report_follow_up_context_func
        self.prepare_follow_up_report_context_func = prepare_follow_up_report_context_func
        self.execute_follow_up_actions_func = execute_follow_up_actions_func
        self.summarize_follow_up_execution_func = summarize_follow_up_execution_func
        self.split_fresh_tracking_actions_func = split_fresh_tracking_actions_func
        self.render_follow_up_actions_markdown_func = render_follow_up_actions_markdown_func
        self.report_build_service_factory = report_build_service_factory
        self.count_sufficient_company_filings_func = count_sufficient_company_filings_func
        self.safe_mark_run_failed_func = safe_mark_run_failed_func
        self.tracking_freshness_thresholds = tracking_freshness_thresholds
        self.task_cancellation_checker = task_cancellation_checker

    async def run(self, report_id: int, payload: Any, *, celery_task_id: str | None = None) -> dict:
        context = self.load_report_follow_up_context_func(report_id)
        request = context["request"]
        quality_gate = context["quality_gate"]
        candidate_audit_required = should_require_candidate_audit_follow_up(
            quality_gate,
            context["company_data_audit"],
            context.get("candidate_whitelist") or [],
        )
        candidate_actions = self.follow_up_action_planner_cls().plan(
            request,
            quality_gate=quality_gate,
            source_audit=context["source_audit"],
            markdown=context["markdown"],
            company_data_audit=context["company_data_audit"],
            candidate_audit_required=candidate_audit_required,
            apply_freshness=False,
        )
        if not candidate_actions and payload.force_refresh:
            candidate_actions = manual_tracking_follow_up_actions(request)
        fresh_actions, skipped_details = self.split_fresh_tracking_actions_func(candidate_actions, request)
        skipped_action_payloads = [
            {key: value for key, value in detail.items() if key != "freshness"}
            for detail in skipped_details
        ]
        all_actions = candidate_actions if payload.force_refresh else fresh_actions
        actions = filter_follow_up_actions(all_actions, payload.purpose)
        available_summary = follow_up_action_summary(all_actions)
        selected_summary = follow_up_action_summary(actions)
        freshness = self._freshness_payload(skipped_details, skipped_action_payloads)
        if not actions and not payload.record_noop:
            return {
                "report_id": report_id,
                "run_id": None,
                "status": "no_action_required",
                "purpose": payload.purpose,
                "summary": {
                    "available": available_summary,
                    "selected": selected_summary,
                },
                "freshness": freshness,
                "available_actions": [action.to_dict() for action in all_actions],
                "actions": [],
                "results": {},
            }

        run_id = self._start_run(
            report_id,
            context,
            request,
            quality_gate,
            candidate_audit_required,
            all_actions,
            actions,
            freshness,
            payload,
            celery_task_id=celery_task_id,
        )
        try:
            self._check_cancelled(run_id)
            if not actions:
                return self._mark_no_action_run_success(
                    run_id,
                    report_id,
                    context,
                    request,
                    quality_gate,
                    candidate_audit_required,
                    all_actions,
                    available_summary,
                    selected_summary,
                    freshness,
                    payload,
                    celery_task_id=celery_task_id,
                )

            execution = await self._execute_actions(run_id, actions, request, payload.news_limit)
            self._check_cancelled(run_id)
            execution_summary = execution.get("execution_summary") or {}
            if "completion" not in execution_summary:
                execution_summary = self.summarize_follow_up_execution_func(execution)
            response_payload = {
                "report_id": report_id,
                "run_id": run_id,
                "status": "executed",
                "purpose": payload.purpose,
                "force_refresh": payload.force_refresh,
                "summary": {
                    "available": available_summary,
                    "selected": selected_summary,
                    "execution": execution_summary,
                },
                "freshness": freshness,
                "actions": [action.to_dict() for action in actions],
                "results": execution["results"],
                "rerun_report": None,
            }
            can_revalidate = can_rerun_candidate_revalidation_from_existing_evidence(context, actions)
            if can_revalidate and execution_summary.get("rerun_blocked"):
                execution_summary = {
                    **execution_summary,
                    "rerun_blocked": False,
                    "rerun_blockers": [],
                    "rerun_blocker_actions": [],
                    "revalidation_from_existing_evidence": True,
                }
                response_payload["summary"]["execution"] = execution_summary
            if payload.rerun_report and execution_summary.get("rerun_blocked") and not can_revalidate:
                response_payload["rerun_report"] = {
                    "status": "skipped",
                    "reason": "補資料後仍有關鍵缺口，先不重新產生報告。",
                    "blockers": execution_summary.get("rerun_blockers", []),
                    "next_actions": execution_summary.get("rerun_blocker_actions", []),
                }
            elif payload.rerun_report:
                self._check_cancelled(run_id)
                response_payload["rerun_report"] = await self._build_rerun_report(
                    run_id,
                    context,
                    request,
                    actions,
                )
                self._check_cancelled(run_id)
            self._persist_executed_run(
                run_id,
                report_id,
                context,
                request,
                quality_gate,
                all_actions,
                actions,
                execution,
                response_payload,
                freshness,
                payload,
                celery_task_id=celery_task_id,
            )
            return response_payload
        except TaskCancelledError as exc:
            self._mark_run_cancelled(run_id, str(exc))
            return {
                "report_id": report_id,
                "run_id": run_id,
                "status": "cancelled",
                "cancelled": True,
            }

    def _start_run(
        self,
        report_id: int,
        context: dict,
        request: Any,
        quality_gate: dict,
        candidate_audit_required: bool,
        all_actions: list,
        actions: list,
        freshness: dict,
        payload: Any,
        *,
        celery_task_id: str | None = None,
    ) -> int:
        run_payload = {
            "source_report_id": report_id,
            "source_report_topic": context.get("source_report_topic"),
            "source_report_tickers": context.get("source_report_tickers") or [],
            "source_report_generated_at": context.get("source_report_generated_at"),
            "source_report_created_at": context.get("source_report_created_at"),
            "request": request.model_dump(mode="json"),
            "quality_gate_before": quality_gate,
            "company_data_audit_before": context["company_data_audit"],
            "candidate_audit_required": candidate_audit_required,
            "available_actions": [action.to_dict() for action in all_actions],
            "freshness": freshness,
            "planned_actions": [action.to_dict() for action in actions],
            "rerun_report": payload.rerun_report,
            **self._follow_up_request_options(payload),
        }
        if celery_task_id:
            run_payload["celery_task_id"] = celery_task_id
        with self.session_scope_factory() as session:
            run = self.analysis_run_repository_cls(session).start("follow_up_api", run_payload)
            return run.id

    def _mark_no_action_run_success(
        self,
        run_id: int,
        report_id: int,
        context: dict,
        request: Any,
        quality_gate: dict,
        candidate_audit_required: bool,
        all_actions: list,
        available_summary: dict,
        selected_summary: dict,
        freshness: dict,
        payload: Any,
        *,
        celery_task_id: str | None = None,
    ) -> dict:
        run_payload = {
            "source_report_id": report_id,
            "source_report_topic": context.get("source_report_topic"),
            "source_report_tickers": context.get("source_report_tickers") or [],
            "source_report_generated_at": context.get("source_report_generated_at"),
            "source_report_created_at": context.get("source_report_created_at"),
            "request": request.model_dump(mode="json"),
            "quality_gate_before": quality_gate,
            "company_data_audit_before": context["company_data_audit"],
            "candidate_audit_required": candidate_audit_required,
            "available_actions": [action.to_dict() for action in all_actions],
            "planned_actions": [],
            **self._follow_up_request_options(payload),
            "summary": {
                "available": available_summary,
                "selected": selected_summary,
            },
            "freshness": freshness,
            "status": "no_action_required",
        }
        if celery_task_id:
            run_payload["celery_task_id"] = celery_task_id
        with self.session_scope_factory() as session:
            repository = self.analysis_run_repository_cls(session)
            repository.update_payload(run_id, run_payload)
            repository.mark_success(run_id, report_id)
        return {
            "report_id": report_id,
            "run_id": run_id,
            "status": "no_action_required",
            "purpose": payload.purpose,
            "summary": {
                "available": available_summary,
                "selected": selected_summary,
            },
            "freshness": freshness,
            "actions": [],
            "results": {},
        }

    async def _execute_actions(
        self,
        run_id: int,
        actions: list,
        request: Any,
        news_limit: int,
    ) -> dict:
        try:
            return await self.execute_follow_up_actions_func(actions, request, news_limit=news_limit)
        except Exception as exc:
            self.safe_mark_run_failed_func(run_id, str(exc))
            raise

    async def _build_rerun_report(
        self,
        run_id: int,
        context: dict,
        request: Any,
        actions: list,
    ) -> dict:
        rerun_context = await self.prepare_follow_up_report_context_func(context, request, actions)
        rerun_request = rerun_context["request"]
        candidate_revalidation = rerun_context["candidate_revalidation"]
        rerun_candidate_support = summarize_candidate_support_payload(
            candidate_revalidation.get("candidate_whitelist") or []
        )
        try:
            report_result = self.report_build_service_factory().build(
                rerun_request,
                whitelist=rerun_context["whitelist"],
                company_filing_sufficient_count=self.count_sufficient_company_filings_func(
                    rerun_request.tickers
                ),
                candidate_support=rerun_candidate_support,
                plan_quality=(
                    (context.get("run_payload") or {}).get("plan_quality")
                    or ((context.get("run_payload") or {}).get("discovery") or {}).get("plan_quality")
                    or plan_quality_from_quality_gate(context.get("quality_gate") or {})
                ),
            )
        except ReportExecutionError as exc:
            self.safe_mark_run_failed_func(run_id, str(exc))
            raise
        response = report_result["response"]
        refreshed_quality_gate = report_result["quality_gate"]
        with self.session_scope_factory() as session:
            new_report = self.report_repository_cls(session).create(rerun_request, response)
            new_report_id = new_report.id
        record_llm_usage_from_report_execution(
            report_result.get("report_execution"),
            operation="report_follow_up_rerun",
            report_id=new_report_id,
            run_id=run_id,
            session_scope_factory=self.session_scope_factory,
        )
        return {
            "report_id": new_report_id,
            "request": rerun_request.model_dump(mode="json"),
            "quality_gate": refreshed_quality_gate,
            "report_execution": report_result["report_execution"],
            "candidate_revalidation": candidate_revalidation,
            "follow_up_section": self.render_follow_up_actions_markdown_func(
                self.follow_up_action_planner_cls().plan(
                    rerun_request,
                    quality_gate=refreshed_quality_gate,
                    markdown=response.markdown,
                    candidate_audit_required=should_require_candidate_audit_follow_up(
                        refreshed_quality_gate,
                        {"status": "sufficient"},
                        candidate_revalidation.get("candidate_whitelist") or [],
                    ),
                )
            ),
        }

    def _persist_executed_run(
        self,
        run_id: int,
        report_id: int,
        context: dict,
        request: Any,
        quality_gate: dict,
        all_actions: list,
        actions: list,
        execution: dict,
        response_payload: dict,
        freshness: dict,
        payload: Any,
        *,
        celery_task_id: str | None = None,
    ) -> None:
        persisted_request = (
            (response_payload["rerun_report"] or {}).get("request")
            or request.model_dump(mode="json")
        )
        persisted_candidates = (
            (response_payload["rerun_report"] or {})
            .get("candidate_revalidation", {})
            .get("candidate_whitelist")
            or context.get("candidate_whitelist")
        )
        run_payload = {
            "source_report_id": report_id,
            "source_report_topic": context.get("source_report_topic"),
            "source_report_tickers": context.get("source_report_tickers") or [],
            "source_report_generated_at": context.get("source_report_generated_at"),
            "source_report_created_at": context.get("source_report_created_at"),
            "request": persisted_request,
            "quality_gate_before": quality_gate,
            "available_actions": [action.to_dict() for action in all_actions],
            "freshness": freshness,
            "planned_actions": [action.to_dict() for action in actions],
            "execution": execution,
            "rerun_report": response_payload["rerun_report"],
            "candidate_whitelist": persisted_candidates,
            **self._follow_up_request_options(payload),
            "summary": response_payload["summary"],
        }
        if celery_task_id:
            run_payload["celery_task_id"] = celery_task_id
        with self.session_scope_factory() as session:
            repository = self.analysis_run_repository_cls(session)
            repository.update_payload(run_id, run_payload)
            repository.mark_success(
                run_id,
                (response_payload["rerun_report"] or {}).get("report_id") or report_id,
            )

    def _freshness_payload(
        self,
        skipped_details: list,
        skipped_action_payloads: list,
    ) -> dict:
        return {
            "skipped_count": len(skipped_details),
            "skipped_actions": skipped_action_payloads,
            "skipped_details": skipped_details,
            "thresholds": self.tracking_freshness_thresholds,
        }

    @staticmethod
    def _follow_up_request_options(payload: Any) -> dict[str, Any]:
        return {
            "rerun_report_requested": payload.rerun_report,
            "news_limit": payload.news_limit,
            "record_noop": payload.record_noop,
            "purpose": payload.purpose,
            "force_refresh": payload.force_refresh,
        }

    def _mark_run_cancelled(self, run_id: int, reason: str) -> None:
        with self.session_scope_factory() as session:
            repository = self.analysis_run_repository_cls(session)
            mark_cancelled = getattr(repository, "mark_cancelled", None)
            if callable(mark_cancelled):
                mark_cancelled(run_id, reason)
            else:
                self.safe_mark_run_failed_func(run_id, reason)

    def _check_cancelled(self, run_id: int) -> None:
        if self.task_cancellation_checker is not None:
            self.task_cancellation_checker(run_id)
            return
        raise_if_task_cancelled(
            run_id,
            session_scope_factory=self.session_scope_factory,
            analysis_run_repository_cls=self.analysis_run_repository_cls,
        )
