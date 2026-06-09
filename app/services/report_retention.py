from __future__ import annotations

REPORT_RETENTION_POLICY = "latest_per_topic"


def empty_repository_retention_result() -> dict:
    return {
        "policy": REPORT_RETENTION_POLICY,
        "topic": None,
        "report_id": None,
        "created_report_id": None,
        "retained_report_id": None,
        "created_report_retained": True,
        "old_report_versions_deleted": 0,
        "old_report_ids": [],
        "run_links_cleared": False,
        "run_output_paths_cleared": False,
    }


def repository_retention_result(
    *,
    topic: str,
    created_report_id: int,
    retained_report_id: int,
    old_report_versions_deleted: int,
    old_report_ids: list[int],
) -> dict:
    return {
        "policy": REPORT_RETENTION_POLICY,
        "topic": topic,
        "report_id": retained_report_id,
        "created_report_id": created_report_id,
        "retained_report_id": retained_report_id,
        "created_report_retained": created_report_id == retained_report_id,
        "old_report_versions_deleted": old_report_versions_deleted,
        "old_report_ids": list(old_report_ids),
        "run_links_cleared": bool(old_report_versions_deleted),
        "run_output_paths_cleared": bool(old_report_versions_deleted),
    }


__all__ = [
    "REPORT_RETENTION_POLICY",
    "empty_repository_retention_result",
    "repository_retention_result",
]
