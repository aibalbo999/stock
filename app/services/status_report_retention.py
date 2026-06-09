from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.report_files import (
    prune_older_report_files_by_topic,
    report_artifact_files,
    report_file_topic_key,
    report_retention_preview,
)


def report_retention_status() -> dict:
    root = Path(__file__).resolve().parents[2]
    analysis_run_repository_source = _read_text(
        root / "app" / "services" / "analysis_run_repository.py"
    )
    report_repository_source = _read_text(root / "app" / "services" / "report_repository.py")
    report_retention_source = _read_text(root / "app" / "services" / "report_retention.py")
    report_files_source = _read_text(root / "app" / "services" / "report_files.py")
    report_query_source = _read_text(root / "app" / "services" / "report_query.py")
    data_operations_source = _read_text(root / "app" / "services" / "data_operations_api.py")
    maintenance_ui_source = _read_text(root / "app" / "ui" / "system_settings_maintenance.py")
    maintenance_cleanup_source = _read_text(root / "app" / "ui" / "maintenance_cleanup_panel.py")
    report_routes_source = _read_text(root / "app" / "api" / "report_routes.py")
    schedule_config_source = _read_text(root / "app" / "services" / "schedule_config.py")
    celery_app_source = _read_text(root / "app" / "tasks" / "celery_app.py")
    tasks_source = _read_text(root / "app" / "tasks" / "tasks.py")
    report_generation_task_source = _read_text(root / "app" / "tasks" / "report_generation.py")
    maintenance_cleanup_task_source = _read_text(root / "app" / "tasks" / "maintenance_cleanup.py")
    task_exports_source = _read_text(root / "app" / "api" / "task_exports.py")
    task_queue_status_source = _read_text(root / "app" / "services" / "status_task_queue.py")
    schedule_ui_source = _read_text(root / "app" / "ui" / "system_settings_schedule.py")
    write_prunes_db = (
        "self.prune_older_for_topic(report.topic, report.id)" in report_repository_source
    )
    report_file_write_prunes = (
        "prune_report_files_for_topic(report_dir, safe_topic, keep_path=path)"
        in report_files_source
    )
    report_file_write_returns_retention = (
        "def write_report_file_with_retention(" in report_files_source
        and '"old_report_files_deleted"' in report_files_source
        and '"policy": "latest_per_topic"' in report_files_source
    )
    report_file_write_retains_latest_version = (
        "def _matching_report_versions_by_stem(" in report_files_source
        and "report_artifact_version_sort_key(versions[stem])" in report_files_source
        and '"written_path"' in report_files_source
        and '"retained_path"' in report_files_source
        and '"written_file_retained"' in report_files_source
    )
    repository_create_records_retention = (
        "self.last_retention_result" in report_repository_source
        and "repository_retention_result(" in report_repository_source
        and '"old_report_versions_deleted"' in report_retention_source
        and '"old_report_ids"' in report_retention_source
    )
    repository_create_retains_latest_version = (
        "def _latest_report_id_for_topic(" in report_repository_source
        and "GeneratedReport.generated_at.desc()" in report_repository_source
        and '"created_report_id"' in report_retention_source
        and '"retained_report_id"' in report_retention_source
        and '"created_report_retained"' in report_retention_source
    )
    celery_combined_write_guard = (
        "def _create_report_with_retention(" in tasks_source
        and "def _write_report_file_with_retention(" in tasks_source
        and "def _combined_report_retention(" in tasks_source
        and "combined_report_retention_func(db_retention, file_retention)"
        in report_generation_task_source
        and '"retention": retention' in report_generation_task_source
    )
    artifact_retention_smoke = _report_artifact_retention_smoke()
    report_file_write_prunes_artifacts = (
        report_file_write_prunes and "REPORT_ARTIFACT_SUFFIXES" in report_files_source
    )
    maintenance_prunes_artifacts = (
        "self._prune_older_report_files()" in data_operations_source
        and "prune_older_report_files_by_topic" in data_operations_source
        and "REPORT_ARTIFACT_SUFFIXES" in report_files_source
    )
    manual_delete_prunes_artifacts = (
        "delete_report_markdown_files(" in report_query_source
        and "_report_artifact_sibling_paths(" in report_query_source
        and "REPORT_ARTIFACT_SUFFIXES" in report_query_source
        and '"deleted_report_files"' in report_query_source
    )
    manual_delete_artifact_guardrail = (
        "def _safe_report_markdown_path(" in report_query_source
        and 'suffix.lower() != ".md"' in report_query_source
        and "report_dir not in resolved.parents" in report_query_source
        and "def _report_artifact_sibling_paths(" in report_query_source
    )
    retention_preview_smoke = _report_retention_preview_smoke()
    return {
        "collector_path": "app/services/status_report_retention.py",
        "policy": "latest_per_topic",
        "write_prunes_db_by_topic": write_prunes_db,
        "write_prunes_markdown_by_topic": report_file_write_prunes,
        "write_prunes_report_artifacts_by_topic": report_file_write_prunes_artifacts,
        "repository_create_records_retention_result": repository_create_records_retention,
        "report_file_write_returns_retention_result": report_file_write_returns_retention,
        "report_file_write_retains_latest_version": report_file_write_retains_latest_version,
        "repository_create_retains_latest_version": repository_create_retains_latest_version,
        "celery_report_write_uses_combined_retention_guard": celery_combined_write_guard,
        "repository_latest_by_topic_available": "def latest_by_topic(" in report_repository_source
        and "row_number()" in report_repository_source
        and "partition_by=GeneratedReport.topic" in report_repository_source,
        "repository_latest_tie_breaks_by_id": "GeneratedReport.id.desc()"
        in report_repository_source,
        "repository_bulk_prune_available": "def prune_older_by_topic(" in report_repository_source,
        "repository_topic_prune_available": "def prune_older_for_topic("
        in report_repository_source,
        "run_links_cleared_for_pruned_reports": (
            "def _clear_analysis_run_report_links(" in report_repository_source
            and "_clear_analysis_run_report_links(old_report_ids)" in report_repository_source
        ),
        "run_output_paths_cleared_for_pruned_reports": (
            "def _clear_analysis_run_report_links(" in report_repository_source
            and ".values(report_id=None, output_path=None)" in report_repository_source
        ),
        "delete_before_clears_run_links": (
            "def delete_before(self, before: datetime) -> int:" in report_repository_source
            and "_clear_analysis_run_report_links(old_report_ids)" in report_repository_source
        ),
        "orphan_cleanup_clears_output_path": (
            "def clear_orphan_report_refs(" in analysis_run_repository_source
            and ".values(report_id=None, output_path=None)" in analysis_run_repository_source
        ),
        "markdown_bulk_prune_available": "def prune_older_report_files_by_topic("
        in report_files_source,
        "report_artifact_bulk_prune_available": "def report_artifact_files(" in report_files_source
        and "def prune_older_report_files_by_topic(" in report_files_source,
        "report_retention_preview_available": "def report_retention_preview(" in report_files_source
        and "def retention_preview(" in report_query_source,
        "report_retention_preview_endpoint": '"/reports/retention/preview"' in report_routes_source
        and "def report_retention_preview(" in report_routes_source,
        "settings_ui_retention_preview": '"/reports/retention/preview"'
        in maintenance_cleanup_source
        and "deletable_artifact_count" in maintenance_cleanup_source,
        "markdown_topic_key_parser_available": "def report_file_topic_key(" in report_files_source,
        "report_artifact_topic_key_parser_available": "def report_file_topic_key("
        in report_files_source
        and "REPORT_ARTIFACT_SUFFIXES" in report_files_source,
        "markdown_retention_smoke_passed": artifact_retention_smoke["passed"],
        "markdown_retention_smoke": artifact_retention_smoke,
        "report_artifact_retention_smoke_passed": artifact_retention_smoke["passed"],
        "report_artifact_retention_smoke": artifact_retention_smoke,
        "report_retention_preview_smoke_passed": retention_preview_smoke["passed"],
        "report_retention_preview_smoke": retention_preview_smoke,
        "list_reports_uses_latest_by_topic": "latest_by_topic(limit)" in report_query_source,
        "quality_summary_uses_latest_by_topic": "latest_by_topic(safe_limit)"
        in report_query_source,
        "report_list_returns_policy": '"retention_policy": "latest_per_topic"'
        in report_query_source,
        "maintenance_prunes_db_by_topic": "reports.prune_older_by_topic()"
        in data_operations_source,
        "maintenance_prunes_markdown_by_topic": "self._prune_older_report_files()"
        in data_operations_source
        and "prune_older_report_files_by_topic" in data_operations_source,
        "maintenance_prunes_report_artifacts_by_topic": maintenance_prunes_artifacts,
        "maintenance_returns_policy": '"report_retention_policy": "latest_per_topic"'
        in data_operations_source,
        "scheduled_cleanup_config_available": (
            "maintenance_cleanup_enabled: bool = True" in schedule_config_source
            and "maintenance_cleanup_payload" in schedule_config_source
            and "maintenance_cleanup_latest_reports_only: bool = True" in schedule_config_source
            and "maintenance_cleanup_orphan_report_refs: bool = True" in schedule_config_source
        ),
        "scheduled_cleanup_payload_retains_latest": (
            '"latest_reports_only": config.maintenance_cleanup_latest_reports_only'
            in schedule_config_source
            and '"orphan_report_refs": config.maintenance_cleanup_orphan_report_refs'
            in schedule_config_source
        ),
        "scheduled_cleanup_task_registered": (
            'name="app.tasks.tasks.maintenance_cleanup_task"' in tasks_source
            and "def maintenance_cleanup_task(" in tasks_source
            and "def _run_maintenance_cleanup_payload(" in tasks_source
            and ".data_operations_api()" in maintenance_cleanup_task_source
            and ".maintenance_cleanup(" in maintenance_cleanup_task_source
        ),
        "scheduled_cleanup_beat_registered": (
            '"daily-maintenance-cleanup"' in celery_app_source
            and '"task": "app.tasks.tasks.maintenance_cleanup_task"' in celery_app_source
            and "schedule_store.maintenance_cleanup_payload()" in celery_app_source
        ),
        "scheduled_cleanup_task_queue_visible": (
            '"maintenance_cleanup_task"' in task_exports_source
            and '"maintenance_cleanup_task"' in task_queue_status_source
            and '"app.tasks.tasks.maintenance_cleanup_task"' in task_queue_status_source
        ),
        "settings_ui_scheduled_cleanup_controls": (
            "maintenance_cleanup_enabled" in schedule_ui_source
            and "maintenance_cleanup_latest_reports_only" in schedule_ui_source
            and "maintenance_cleanup_orphan_report_refs" in schedule_ui_source
            and "maintenance_cleanup_stale_running_minutes" in schedule_ui_source
        ),
        "manual_delete_clears_run_links": ".values(report_id=None, output_path=None)"
        in report_repository_source,
        "manual_delete_prunes_markdown": "delete_report_markdown_files(" in report_query_source
        and '"deleted_report_files"' in report_query_source,
        "manual_delete_prunes_report_artifacts": manual_delete_prunes_artifacts,
        "manual_delete_markdown_guardrail": "def _safe_report_markdown_path(" in report_query_source
        and 'suffix.lower() != ".md"' in report_query_source
        and "report_dir not in resolved.parents" in report_query_source,
        "manual_delete_artifact_guardrail": manual_delete_artifact_guardrail,
        "settings_ui_cleanup_action": "render_maintenance_cleanup_panel()" in maintenance_ui_source
        and '"/maintenance/cleanup"' in maintenance_cleanup_source
        and '"latest_reports_only": True' in maintenance_cleanup_source
        and '"orphan_report_refs": True' in maintenance_cleanup_source,
        "covered_paths": [
            "app/services/analysis_run_repository.py",
            "app/services/persistence.py",
            "app/services/report_files.py",
            "app/services/report_query.py",
            "app/services/data_operations_api.py",
            "app/services/schedule_config.py",
            "app/tasks/celery_app.py",
            "app/tasks/tasks.py",
            "app/tasks/report_generation.py",
            "app/tasks/maintenance_cleanup.py",
            "app/api/task_exports.py",
            "app/services/status_task_queue.py",
            "app/ui/system_settings_maintenance.py",
            "app/ui/maintenance_cleanup_panel.py",
            "app/ui/system_settings_schedule.py",
        ],
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _report_artifact_retention_smoke() -> dict:
    try:
        with TemporaryDirectory() as temp_dir:
            report_dir = Path(temp_dir)
            old_ai = report_dir / "20260606_120000_AI_topic.md"
            old_ai_html = report_dir / "20260606_120000_AI_topic.html"
            old_ai_pdf = report_dir / "20260606_120000_AI_topic.pdf"
            latest_ai = report_dir / "20260607_080000_AI_topic.md"
            latest_ai_html = report_dir / "20260607_080000_AI_topic.html"
            latest_ai_pdf = report_dir / "20260607_080000_AI_topic.pdf"
            old_robot = report_dir / "010_robot_topic.md"
            old_robot_pdf = report_dir / "010_robot_topic.pdf"
            latest_robot = report_dir / "20260607_090000_robot_topic.md"
            latest_robot_html = report_dir / "20260607_090000_robot_topic.html"
            standalone = report_dir / "single_report.md"
            standalone_html = report_dir / "single_report.html"
            for path in (
                old_ai,
                old_ai_html,
                old_ai_pdf,
                latest_ai,
                latest_ai_html,
                latest_ai_pdf,
                old_robot,
                old_robot_pdf,
                latest_robot,
                latest_robot_html,
                standalone,
                standalone_html,
            ):
                path.write_text(path.name, encoding="utf-8")

            timestamped_topic_key = report_file_topic_key(latest_ai)
            legacy_topic_key = report_file_topic_key(old_robot)
            deleted_count = prune_older_report_files_by_topic(report_dir)
            kept_files = sorted(path.name for path in report_artifact_files(report_dir))
            expected_kept_files = sorted(
                [
                    latest_ai.name,
                    latest_ai_html.name,
                    latest_ai_pdf.name,
                    latest_robot.name,
                    latest_robot_html.name,
                    standalone.name,
                    standalone_html.name,
                ]
            )
            checks = {
                "deleted_count": deleted_count == 5,
                "latest_timestamped_report_kept": latest_ai.exists(),
                "latest_timestamped_html_kept": latest_ai_html.exists(),
                "latest_timestamped_pdf_kept": latest_ai_pdf.exists(),
                "old_timestamped_report_removed": not old_ai.exists(),
                "old_timestamped_html_removed": not old_ai_html.exists(),
                "old_timestamped_pdf_removed": not old_ai_pdf.exists(),
                "latest_legacy_topic_report_kept": latest_robot.exists(),
                "latest_legacy_topic_html_kept": latest_robot_html.exists(),
                "old_legacy_topic_report_removed": not old_robot.exists(),
                "old_legacy_topic_pdf_removed": not old_robot_pdf.exists(),
                "standalone_report_kept": standalone.exists(),
                "standalone_html_kept": standalone_html.exists(),
                "timestamped_topic_key": timestamped_topic_key == "AI_topic",
                "legacy_topic_key": legacy_topic_key == "robot_topic",
                "kept_files": kept_files == expected_kept_files,
            }
            return {
                "passed": all(checks.values()),
                "deleted_count": deleted_count,
                "kept_files": kept_files,
                "expected_kept_files": expected_kept_files,
                "checks": checks,
                "error": None,
            }
    except Exception as exc:
        return {
            "passed": False,
            "deleted_count": 0,
            "kept_files": [],
            "expected_kept_files": [],
            "checks": {},
            "error": f"{type(exc).__name__}: {exc}",
        }


def _report_retention_preview_smoke() -> dict:
    try:
        with TemporaryDirectory() as temp_dir:
            report_dir = Path(temp_dir)
            old_ai = report_dir / "20260606_120000_AI_topic.md"
            old_ai_html = report_dir / "20260606_120000_AI_topic.html"
            latest_ai = report_dir / "20260607_080000_AI_topic.md"
            standalone = report_dir / "single_report.md"
            for path in (old_ai, old_ai_html, latest_ai, standalone):
                path.write_text(path.name, encoding="utf-8")

            preview = report_retention_preview(report_dir)
            checks = {
                "policy": preview.get("policy") == "latest_per_topic",
                "topic_count": preview.get("topic_count") == 2,
                "stale_topic_count": preview.get("stale_topic_count") == 1,
                "deletable_artifact_count": preview.get("deletable_artifact_count") == 2,
                "preview_does_not_delete_old_md": old_ai.exists(),
                "preview_does_not_delete_old_html": old_ai_html.exists(),
                "preview_keeps_latest": latest_ai.exists(),
            }
            return {
                "passed": all(checks.values()),
                "checks": checks,
                "preview": preview,
                "error": None,
            }
    except Exception as exc:
        return {
            "passed": False,
            "checks": {},
            "preview": {},
            "error": f"{type(exc).__name__}: {exc}",
        }
