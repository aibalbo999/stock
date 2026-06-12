from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.models.schemas import ReportRequest
from app.services.report_followup_context import ReportFollowUpContextNotFound
from app.services.report_generator import ReportExecutionError
from app.services.workflow_orchestration import WorkflowOrchestrationError


class FollowUpCompatibilityMixin:
    """Legacy report follow-up delegates for app.api.main imports."""

    api_services: Any

    def load_report_follow_up_context(self, report_id: int) -> dict:
        return self.api_services.report_follow_up_context().load(report_id)

    async def prepare_follow_up_report_context(
        self,
        context: dict,
        request: ReportRequest,
        actions: list,
    ) -> dict:
        return await self.api_services.report_follow_up_context().prepare(context, request, actions)

    async def refresh_market_data_for_report(self, request: ReportRequest) -> dict:
        return await self.api_services.report_follow_up_context().refresh_market_data(request)

    def get_report_follow_up_plan(self, report_id: int) -> dict:
        try:
            return self.api_services.report_follow_up_plan().build(report_id)
        except ReportFollowUpContextNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def maybe_auto_start_required_follow_up(
        self,
        report_id: int,
        run_in_background: bool = True,
    ) -> dict:
        return await self.api_services.auto_follow_up_start().start(report_id, run_in_background)

    async def run_required_follow_up_background(
        self,
        report_id: int,
        payload: Any,
    ) -> None:
        try:
            await self.run_report_follow_up(report_id, payload)
        except Exception:
            self.logger.exception("auto follow-up failed for report %s", report_id)

    async def run_report_follow_up(
        self,
        report_id: int,
        payload: Any | None = None,
    ) -> dict:
        payload = payload or self._default_follow_up_run_request()
        try:
            return await self.api_services.report_follow_up_run().run(report_id, payload)
        except HTTPException:
            raise
        except ReportFollowUpContextNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ReportExecutionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except WorkflowOrchestrationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
