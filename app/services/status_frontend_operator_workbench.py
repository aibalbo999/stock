from __future__ import annotations

from app.services.status_frontend_sources import FrontendSourceContext


def frontend_operator_workbench_status(source_context: FrontendSourceContext) -> dict:
    operator_status_source = source_context.ui_sources.get("operator_status.py", "")
    operator_decisions_source = source_context.ui_sources.get("operator_decisions.py", "")

    return {
        "frontend_operator_workbench_status_extracted": True,
        "frontend_operator_workbench_status_path": (
            "app/services/status_frontend_operator_workbench.py"
        ),
        "ui_operator_quota_summary_enabled": (
            "def quota_operator_summary(" in operator_status_source
            and "model_order_label" in operator_status_source
            and "limited_model_label" in operator_status_source
            and "high_quota_fallback_label" in operator_status_source
            and "def _model_order_label(" in operator_status_source
            and "def _limited_model_label(" in operator_status_source
            and "def _first_limited_quota_model(" in operator_status_source
            and (
                "quota_summary[\"caption\"]" in operator_status_source
                or "quota_summary['caption']" in operator_status_source
            )
        ),
        "ui_operator_retryable_failure_primary_action_enabled": (
            "def _retryable_failure_affecting_report(" in operator_decisions_source
            and "def _task_summary_failures(" in operator_decisions_source
            and "重試影響最新版報告的任務" in operator_decisions_source
            and "priority=7" in operator_decisions_source
            and 'action_label="重試任務"' in operator_decisions_source
            and 'route_hint=f"task:{retry_task_id}"' in operator_decisions_source
        ),
        "ui_operator_stale_running_primary_action_enabled": (
            "def _first_incident_by_id(" in operator_decisions_source
            and "task_queue_stale_running" in operator_decisions_source
            and "task_queue:stale_running" in operator_decisions_source
            and "檢查卡住的背景任務" in operator_decisions_source
            and "priority=2" in operator_decisions_source
            and 'action_label=stale_running_incident.get("action_label") or "查看任務"'
            in operator_decisions_source
            and 'route_hint=stale_running_incident["route_hint"]' in operator_decisions_source
        ),
        "ui_operator_quota_missing_read_guard_enabled": (
            "def _healthy_read_reason(" in operator_decisions_source
            and "def _healthy_read_risk(" in operator_decisions_source
            and "quota_missing = not quota_payload" in operator_decisions_source
            and "模型額度狀態暫不可讀" in operator_decisions_source
            and "閱讀現有報告不消耗額度" in operator_decisions_source
            and "reason=_healthy_read_reason(quota_missing=quota_missing)"
            in operator_decisions_source
            and "risk=_healthy_read_risk(quota_missing=quota_missing)"
            in operator_decisions_source
        ),
    }
