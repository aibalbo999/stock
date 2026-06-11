from __future__ import annotations

from collections.abc import Mapping
from typing import Any


RISKY_SUBMISSION_GUARDS: tuple[dict[str, str], ...] = (
    {
        "id": "analysis_submission",
        "guard_key": "ui_analysis_submission_quota_confirmation_enabled",
        "surface": "analysis_workspace",
    },
    {
        "id": "market_data_operation",
        "guard_key": "ui_data_enrichment_market_submission_confirmation_enabled",
        "surface": "data_enrichment_market",
    },
    {
        "id": "company_filing_url_import",
        "guard_key": "ui_company_filing_url_import_confirmation_enabled",
        "surface": "data_enrichment_manual",
    },
    {
        "id": "rss_fetch",
        "guard_key": "ui_rss_fetch_confirmation_enabled",
        "surface": "data_enrichment_rss",
    },
    {
        "id": "report_follow_up_run",
        "guard_key": "ui_report_follow_up_submission_confirmation_enabled",
        "surface": "report_follow_up_controls",
    },
    {
        "id": "report_delete",
        "guard_key": "ui_report_delete_confirmation_gate_enabled",
        "surface": "report_center",
    },
    {
        "id": "maintenance_cleanup",
        "guard_key": "ui_maintenance_cleanup_confirmation_gate_enabled",
        "surface": "maintenance_cleanup_panel",
    },
    {
        "id": "maintenance_operation",
        "guard_key": "ui_maintenance_operation_confirmation_gate_enabled",
        "surface": "maintenance_deployment_panel",
    },
    {
        "id": "maintenance_diagnostic",
        "guard_key": "ui_maintenance_diagnostic_confirmation_gate_enabled",
        "surface": "maintenance_task_panels",
    },
    {
        "id": "maintenance_post_run_diagnostic",
        "guard_key": "ui_maintenance_post_run_diagnostic_confirmation_gate_enabled",
        "surface": "maintenance_deployment_panel",
    },
    {
        "id": "maintenance_task_retry",
        "guard_key": "ui_maintenance_task_retry_confirmation_gate_enabled",
        "surface": "maintenance_task_panels",
    },
    {
        "id": "task_status_operation",
        "guard_key": "ui_task_status_operation_confirmation_gate_enabled",
        "surface": "task_status_panel",
    },
)


def frontend_submission_guard_status(frontend_status: Mapping[str, Any]) -> dict:
    rows = [
        {
            "id": guard["id"],
            "guard_key": guard["guard_key"],
            "surface": guard["surface"],
            "ready": bool(frontend_status.get(guard["guard_key"])),
        }
        for guard in RISKY_SUBMISSION_GUARDS
    ]
    missing = [row["id"] for row in rows if not row["ready"]]
    ready_count = len(rows) - len(missing)
    return {
        "frontend_submission_guard_status_extracted": True,
        "frontend_submission_guard_status_path": (
            "app/services/status_frontend_submission_guards.py"
        ),
        "ui_risky_submission_guard_coverage_enabled": not missing,
        "ui_risky_submission_guard_ready_count": ready_count,
        "ui_risky_submission_guard_total_count": len(rows),
        "ui_risky_submission_guard_missing": missing,
        "ui_risky_submission_guard_rows": rows,
    }
