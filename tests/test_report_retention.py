from app.services.report_retention import (
    empty_repository_retention_result,
    repository_retention_result,
)


def test_empty_repository_retention_result_uses_latest_per_topic_defaults() -> None:
    assert empty_repository_retention_result() == {
        "policy": "latest_per_topic",
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


def test_repository_retention_result_records_backfill_retention() -> None:
    assert repository_retention_result(
        topic="AI 產業鏈",
        created_report_id=12,
        retained_report_id=7,
        old_report_versions_deleted=1,
        old_report_ids=[12],
    ) == {
        "policy": "latest_per_topic",
        "topic": "AI 產業鏈",
        "report_id": 7,
        "created_report_id": 12,
        "retained_report_id": 7,
        "created_report_retained": False,
        "old_report_versions_deleted": 1,
        "old_report_ids": [12],
        "run_links_cleared": True,
        "run_output_paths_cleared": True,
    }
