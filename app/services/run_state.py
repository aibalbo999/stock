from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any


class RunStateService:
    def __init__(
        self,
        *,
        session_scope_factory: Callable,
        analysis_run_repository_cls: type,
    ) -> None:
        self.session_scope_factory = session_scope_factory
        self.analysis_run_repository_cls = analysis_run_repository_cls

    def safe_mark_failed(self, run_id: int, error: str) -> None:
        try:
            with self.session_scope_factory() as session:
                repository = self.analysis_run_repository_cls(session)
                if repository.get(run_id):
                    repository.mark_failed(run_id, error)
        except Exception:
            return

    def safe_update_success(self, run_id: int, payload: dict[str, Any], report_id: int) -> bool:
        with self.session_scope_factory() as session:
            repository = self.analysis_run_repository_cls(session)
            if repository.get(run_id) is None:
                return False
            repository.update_payload(run_id, payload)
            repository.mark_success(run_id, report_id)
            return True

    def safe_merge_payload(self, run_id: int, updates: dict[str, Any]) -> bool:
        if not updates:
            return False
        try:
            with self.session_scope_factory() as session:
                repository = self.analysis_run_repository_cls(session)
                run = repository.get(run_id)
                if run is None:
                    return False
                payload = self._parse_payload(getattr(run, "payload_json", None))
                repository.update_payload(run_id, {**payload, **updates})
                return True
        except Exception:
            return False

    @staticmethod
    def _parse_payload(payload_json: str | None) -> dict[str, Any]:
        if not payload_json:
            return {}
        try:
            payload = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}
