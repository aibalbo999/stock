from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime

from app.core.time import utc_now_naive
from app.db.session import session_scope
from app.services.persistence import AnalysisRunRepository


DISCOVERED_PIPELINE_STEPS = [
    "topic_discovery",
    "source_ingestion",
    "candidate_revalidation",
    "market_data_refresh",
    "report_build",
    "auto_follow_up",
]

STANDARD_PIPELINE_STEPS = [
    "pre_report_refresh",
    "report_build",
    "auto_follow_up",
]

CELERY_REPORT_STEPS = [
    "pre_report_refresh",
    "report_build",
    "follow_up_actions",
    "report_persist",
]


class WorkflowCheckpointRecorder:
    def __init__(
        self,
        session_scope_factory: Callable = session_scope,
        analysis_run_repository_cls=AnalysisRunRepository,
        clock: Callable[[], datetime] = utc_now_naive,
    ) -> None:
        self.session_scope_factory = session_scope_factory
        self.analysis_run_repository_cls = analysis_run_repository_cls
        self.clock = clock

    def initialize(self, run_id: int, workflow_name: str, steps: list[str]) -> bool:
        return self._mutate(
            run_id,
            lambda payload: self.initialize_payload(payload, workflow_name, steps, self._now()),
        )

    def start_step(self, run_id: int, step: str, summary: dict | None = None) -> bool:
        return self._mutate(
            run_id,
            lambda payload: self.start_step_payload(payload, step, self._now(), summary),
        )

    def complete_step(self, run_id: int, step: str, summary: dict | None = None) -> bool:
        return self._mutate(
            run_id,
            lambda payload: self.complete_step_payload(payload, step, self._now(), summary),
        )

    def fail_step(self, run_id: int, step: str, error: str, summary: dict | None = None) -> bool:
        return self._mutate(
            run_id,
            lambda payload: self.fail_step_payload(payload, step, error, self._now(), summary),
        )

    def cancel_step(self, run_id: int, step: str, reason: str, summary: dict | None = None) -> bool:
        return self._mutate(
            run_id,
            lambda payload: self.cancel_step_payload(payload, step, reason, self._now(), summary),
        )

    def complete_workflow_payload(self, run_id: int, final_payload: dict) -> dict:
        workflow = self._current_workflow(run_id)
        if not workflow:
            return final_payload
        workflow = dict(workflow)
        workflow["status"] = "success"
        workflow["finished_at"] = self._now()
        workflow["current_step"] = None
        workflow = self._with_resume_state(workflow)
        return {**final_payload, "workflow": workflow}

    def payload_with_current_workflow(self, run_id: int, payload: dict) -> dict:
        workflow = self._current_workflow(run_id)
        if not workflow:
            return payload
        return {**payload, "workflow": self._with_resume_state(dict(workflow))}

    @classmethod
    def initialize_payload(
        cls,
        payload: dict,
        workflow_name: str,
        steps: list[str],
        now: str,
    ) -> dict:
        workflow = {
            **payload,
            "workflow": {
                "name": workflow_name,
                "status": "running",
                "started_at": now,
                "finished_at": None,
                "current_step": None,
                "steps": [
                    {
                        "name": step,
                        "status": "pending",
                        "started_at": None,
                        "finished_at": None,
                        "duration_ms": None,
                        "summary": {},
                        "error": None,
                    }
                    for step in steps
                ],
            },
        }
        workflow["workflow"] = cls._with_resume_state(workflow["workflow"])
        return workflow

    @classmethod
    def start_step_payload(
        cls,
        payload: dict,
        step: str,
        now: str,
        summary: dict | None = None,
    ) -> dict:
        workflow = cls._ensure_workflow(payload, [step])
        workflow["status"] = "running"
        workflow["current_step"] = step
        step_payload = cls._ensure_step(workflow, step)
        step_payload["status"] = "running"
        step_payload["started_at"] = step_payload.get("started_at") or now
        step_payload["finished_at"] = None
        step_payload["error"] = None
        if summary:
            step_payload["summary"] = {**(step_payload.get("summary") or {}), **summary}
        workflow = cls._with_resume_state(workflow)
        return {**payload, "workflow": workflow}

    @classmethod
    def complete_step_payload(
        cls,
        payload: dict,
        step: str,
        now: str,
        summary: dict | None = None,
    ) -> dict:
        workflow = cls._ensure_workflow(payload, [step])
        step_payload = cls._ensure_step(workflow, step)
        step_payload["status"] = "success"
        step_payload["finished_at"] = now
        step_payload["duration_ms"] = cls._duration_ms(step_payload.get("started_at"), now)
        step_payload["error"] = None
        if summary:
            step_payload["summary"] = {**(step_payload.get("summary") or {}), **summary}
        workflow["current_step"] = None
        workflow = cls._with_resume_state(workflow)
        return {**payload, "workflow": workflow}

    @classmethod
    def fail_step_payload(
        cls,
        payload: dict,
        step: str,
        error: str,
        now: str,
        summary: dict | None = None,
    ) -> dict:
        workflow = cls._ensure_workflow(payload, [step])
        workflow["status"] = "failed"
        workflow["finished_at"] = now
        workflow["current_step"] = step
        step_payload = cls._ensure_step(workflow, step)
        step_payload["status"] = "failed"
        step_payload["finished_at"] = now
        step_payload["duration_ms"] = cls._duration_ms(step_payload.get("started_at"), now)
        step_payload["error"] = str(error)
        if summary:
            step_payload["summary"] = {**(step_payload.get("summary") or {}), **summary}
        workflow = cls._with_resume_state(workflow)
        return {**payload, "workflow": workflow}

    @classmethod
    def cancel_step_payload(
        cls,
        payload: dict,
        step: str,
        reason: str,
        now: str,
        summary: dict | None = None,
    ) -> dict:
        workflow = cls._ensure_workflow(payload, [step])
        workflow["status"] = "cancelled"
        workflow["finished_at"] = now
        workflow["current_step"] = step
        step_payload = cls._ensure_step(workflow, step)
        step_payload["status"] = "cancelled"
        step_payload["finished_at"] = now
        step_payload["duration_ms"] = cls._duration_ms(step_payload.get("started_at"), now)
        step_payload["error"] = str(reason)
        if summary:
            step_payload["summary"] = {**(step_payload.get("summary") or {}), **summary}
        workflow = cls._with_resume_state(workflow)
        return {**payload, "workflow": workflow}

    @classmethod
    def resume_state(cls, workflow: dict) -> dict:
        steps = [step for step in workflow.get("steps") or [] if isinstance(step, dict)]
        completed_steps = [str(step.get("name")) for step in steps if step.get("status") == "success"]
        failed_steps = [str(step.get("name")) for step in steps if step.get("status") == "failed"]
        running_steps = [str(step.get("name")) for step in steps if step.get("status") == "running"]
        pending_steps = [
            str(step.get("name"))
            for step in steps
            if step.get("status") in {None, "", "pending"}
        ]
        current_step = str(workflow.get("current_step") or "") or (running_steps[0] if running_steps else None)
        next_incomplete_step = next(
            (
                str(step.get("name"))
                for step in steps
                if step.get("status") != "success" and step.get("name")
            ),
            None,
        )
        status = str(workflow.get("status") or "running")
        resume_from_step = current_step or (
            failed_steps[0]
            if failed_steps
            else pending_steps[0]
            if pending_steps
            else None
        )
        if status in {"success", "cancelled"}:
            resume_from_step = None
        return {
            "resumable": status in {"running", "failed"} and bool(resume_from_step),
            "resume_from_step": resume_from_step,
            "next_incomplete_step": next_incomplete_step,
            "current_step": current_step,
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
            "running_steps": running_steps,
            "pending_steps": pending_steps,
            "blocked_by_failure": bool(failed_steps),
        }

    @classmethod
    def _with_resume_state(cls, workflow: dict) -> dict:
        return {**workflow, "resume": cls.resume_state(workflow)}

    @staticmethod
    def _ensure_workflow(payload: dict, steps: list[str]) -> dict:
        workflow = dict(payload.get("workflow") or {})
        workflow.setdefault("name", "analysis_workflow")
        workflow.setdefault("status", "running")
        workflow.setdefault("started_at", None)
        workflow.setdefault("finished_at", None)
        workflow.setdefault("current_step", None)
        workflow_steps = list(workflow.get("steps") or [])
        existing = {str(step.get("name")) for step in workflow_steps if isinstance(step, dict)}
        for step in steps:
            if step in existing:
                continue
            workflow_steps.append(
                {
                    "name": step,
                    "status": "pending",
                    "started_at": None,
                    "finished_at": None,
                    "duration_ms": None,
                    "summary": {},
                    "error": None,
                }
            )
        workflow["steps"] = workflow_steps
        return workflow

    @staticmethod
    def _ensure_step(workflow: dict, step: str) -> dict:
        for item in workflow.get("steps") or []:
            if isinstance(item, dict) and item.get("name") == step:
                return item
        new_step = {
            "name": step,
            "status": "pending",
            "started_at": None,
            "finished_at": None,
            "duration_ms": None,
            "summary": {},
            "error": None,
        }
        workflow.setdefault("steps", []).append(new_step)
        return new_step

    @staticmethod
    def _duration_ms(started_at: str | None, finished_at: str) -> int | None:
        if not started_at:
            return None
        try:
            start = datetime.fromisoformat(started_at)
            end = datetime.fromisoformat(finished_at)
        except ValueError:
            return None
        return max(0, int((end - start).total_seconds() * 1000))

    def _mutate(self, run_id: int, mutator: Callable[[dict], dict]) -> bool:
        try:
            with self.session_scope_factory() as session:
                repository = self.analysis_run_repository_cls(session)
                run = repository.get(run_id)
                if run is None:
                    return False
                payload = _parse_payload(getattr(run, "payload_json", None))
                repository.update_payload(run_id, mutator(payload))
                return True
        except Exception:
            return False

    def _current_workflow(self, run_id: int) -> dict | None:
        try:
            with self.session_scope_factory() as session:
                repository = self.analysis_run_repository_cls(session)
                run = repository.get(run_id)
                if run is None:
                    return None
                payload = _parse_payload(getattr(run, "payload_json", None))
                workflow = payload.get("workflow")
                return workflow if isinstance(workflow, dict) else None
        except Exception:
            return None

    def _now(self) -> str:
        return self.clock().isoformat()


def workflow_run_summary(workflow: dict | None) -> dict | None:
    if not isinstance(workflow, dict):
        return None
    steps = [step for step in workflow.get("steps") or [] if isinstance(step, dict)]
    total_steps = len(steps)
    completed_count = sum(1 for step in steps if step.get("status") == "success")
    failed_count = sum(1 for step in steps if step.get("status") == "failed")
    running_count = sum(1 for step in steps if step.get("status") == "running")
    pending_count = sum(1 for step in steps if step.get("status") in {None, "", "pending"})
    resume = workflow.get("resume") if isinstance(workflow.get("resume"), dict) else WorkflowCheckpointRecorder.resume_state(workflow)
    resume_from_step = resume.get("resume_from_step")
    status = str(workflow.get("status") or "running")
    if resume.get("resumable"):
        resume_hint = f"可從 {resume_from_step} 重新啟動或人工接續。"
    elif status == "success":
        resume_hint = "流程已完成，無需續跑。"
    elif status == "cancelled":
        resume_hint = "流程已取消；可視需要重新送出任務。"
    else:
        resume_hint = "目前沒有可用的續跑步驟。"
    return {
        "name": workflow.get("name"),
        "status": status,
        "total_steps": total_steps,
        "completed_steps_count": completed_count,
        "failed_steps_count": failed_count,
        "running_steps_count": running_count,
        "pending_steps_count": pending_count,
        "progress_pct": (completed_count / total_steps) if total_steps else None,
        "current_step": resume.get("current_step"),
        "next_incomplete_step": resume.get("next_incomplete_step"),
        "resume_from_step": resume_from_step,
        "resumable": bool(resume.get("resumable")),
        "blocked_by_failure": bool(resume.get("blocked_by_failure")),
        "resume_hint": resume_hint,
    }


def _parse_payload(payload_json: str | None) -> dict:
    if not payload_json:
        return {}
    try:
        payload = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
