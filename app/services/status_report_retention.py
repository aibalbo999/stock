from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.report_files import (
    prune_older_report_files_by_topic,
    report_file_topic_key,
)


def report_retention_status() -> dict:
    root = Path(__file__).resolve().parents[2]
    persistence_source = _read_text(root / "app" / "services" / "persistence.py")
    report_files_source = _read_text(root / "app" / "services" / "report_files.py")
    report_query_source = _read_text(root / "app" / "services" / "report_query.py")
    data_operations_source = _read_text(root / "app" / "services" / "data_operations_api.py")
    maintenance_ui_source = _read_text(
        root / "app" / "ui" / "system_settings_maintenance.py"
    )
    write_prunes_db = "self.prune_older_for_topic(report.topic, report.id)" in persistence_source
    report_file_write_prunes = (
        "prune_report_files_for_topic(report_dir, safe_topic, keep_path=path)"
        in report_files_source
    )
    markdown_retention_smoke = _markdown_retention_smoke()
    return {
        "collector_path": "app/services/status_report_retention.py",
        "policy": "latest_per_topic",
        "write_prunes_db_by_topic": write_prunes_db,
        "write_prunes_markdown_by_topic": report_file_write_prunes,
        "repository_latest_by_topic_available": "def latest_by_topic(" in persistence_source
        and "row_number()" in persistence_source
        and "partition_by=GeneratedReport.topic" in persistence_source,
        "repository_latest_tie_breaks_by_id": "GeneratedReport.id.desc()" in persistence_source,
        "repository_bulk_prune_available": "def prune_older_by_topic(" in persistence_source,
        "repository_topic_prune_available": "def prune_older_for_topic(" in persistence_source,
        "run_links_cleared_for_pruned_reports": (
            "def _clear_analysis_run_report_links(" in persistence_source
            and "_clear_analysis_run_report_links(old_report_ids)" in persistence_source
        ),
        "run_output_paths_cleared_for_pruned_reports": (
            "def _clear_analysis_run_report_links(" in persistence_source
            and ".values(report_id=None, output_path=None)" in persistence_source
        ),
        "delete_before_clears_run_links": (
            "def delete_before(self, before: datetime) -> int:" in persistence_source
            and "_clear_analysis_run_report_links(old_report_ids)" in persistence_source
        ),
        "orphan_cleanup_clears_output_path": (
            "def clear_orphan_report_refs(" in persistence_source
            and ".values(report_id=None, output_path=None)" in persistence_source
        ),
        "markdown_bulk_prune_available": "def prune_older_report_files_by_topic(" in report_files_source,
        "markdown_topic_key_parser_available": "def report_file_topic_key(" in report_files_source,
        "markdown_retention_smoke_passed": markdown_retention_smoke["passed"],
        "markdown_retention_smoke": markdown_retention_smoke,
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
        "maintenance_returns_policy": '"report_retention_policy": "latest_per_topic"'
        in data_operations_source,
        "manual_delete_clears_run_links": ".values(report_id=None, output_path=None)"
        in persistence_source,
        "manual_delete_prunes_markdown": "delete_report_markdown_files("
        in report_query_source
        and '"deleted_report_files"' in report_query_source,
        "manual_delete_markdown_guardrail": "def _safe_report_markdown_path("
        in report_query_source
        and 'suffix.lower() != ".md"' in report_query_source
        and "report_dir not in resolved.parents" in report_query_source,
        "settings_ui_cleanup_action": '"latest_reports_only": True' in maintenance_ui_source
        and '"orphan_report_refs": True' in maintenance_ui_source,
        "covered_paths": [
            "app/services/persistence.py",
            "app/services/report_files.py",
            "app/services/report_query.py",
            "app/services/data_operations_api.py",
            "app/ui/system_settings_maintenance.py",
        ],
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _markdown_retention_smoke() -> dict:
    try:
        with TemporaryDirectory() as temp_dir:
            report_dir = Path(temp_dir)
            old_ai = report_dir / "20260606_120000_AI_topic.md"
            latest_ai = report_dir / "20260607_080000_AI_topic.md"
            old_robot = report_dir / "010_robot_topic.md"
            latest_robot = report_dir / "20260607_090000_robot_topic.md"
            standalone = report_dir / "single_report.md"
            for path in (old_ai, latest_ai, old_robot, latest_robot, standalone):
                path.write_text(path.name, encoding="utf-8")

            timestamped_topic_key = report_file_topic_key(latest_ai)
            legacy_topic_key = report_file_topic_key(old_robot)
            deleted_count = prune_older_report_files_by_topic(report_dir)
            kept_files = sorted(path.name for path in report_dir.glob("*.md"))
            expected_kept_files = sorted(
                [latest_ai.name, latest_robot.name, standalone.name]
            )
            checks = {
                "deleted_count": deleted_count == 2,
                "latest_timestamped_report_kept": latest_ai.exists(),
                "old_timestamped_report_removed": not old_ai.exists(),
                "latest_legacy_topic_report_kept": latest_robot.exists(),
                "old_legacy_topic_report_removed": not old_robot.exists(),
                "standalone_report_kept": standalone.exists(),
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
