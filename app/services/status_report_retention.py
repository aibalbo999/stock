from __future__ import annotations

from pathlib import Path


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
    return {
        "collector_path": "app/services/status_report_retention.py",
        "policy": "latest_per_topic",
        "write_prunes_db_by_topic": write_prunes_db,
        "write_prunes_markdown_by_topic": report_file_write_prunes,
        "repository_latest_by_topic_available": "def latest_by_topic(" in persistence_source
        and "seen_topics" in persistence_source,
        "repository_bulk_prune_available": "def prune_older_by_topic(" in persistence_source,
        "repository_topic_prune_available": "def prune_older_for_topic(" in persistence_source,
        "run_links_cleared_for_pruned_reports": ".values(report_id=None)" in persistence_source,
        "markdown_bulk_prune_available": "def prune_older_report_files_by_topic(" in report_files_source,
        "markdown_topic_key_parser_available": "def report_file_topic_key(" in report_files_source,
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
