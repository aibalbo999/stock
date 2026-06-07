from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.models.schemas import ReportRequest
from app.services.report_files import (
    prune_older_report_files_by_topic,
    report_file_topic_key,
    write_report_file,
)


def test_write_report_file_prunes_same_topic_files(tmp_path) -> None:
    old_same_topic = tmp_path / "20260606_120000_記憶體產業鏈.md"
    old_numeric_same_topic = tmp_path / "010_記憶體產業鏈.md"
    old_slug_same_topic = tmp_path / "legacy_記憶體產業鏈.md"
    other_topic = tmp_path / "009_機器人_產業鏈.md"
    old_same_topic.write_text("old", encoding="utf-8")
    old_numeric_same_topic.write_text("old numeric", encoding="utf-8")
    old_slug_same_topic.write_text("old slug", encoding="utf-8")
    other_topic.write_text("robot", encoding="utf-8")

    path = write_report_file(
        tmp_path,
        ReportRequest(topic="記憶體產業鏈"),
        SimpleNamespace(
            generated_at=datetime(2026, 6, 7, 8, 0, 0),
            markdown="# latest",
        ),
    )

    assert path.name == "20260607_080000_記憶體產業鏈.md"
    assert path.read_text(encoding="utf-8") == "# latest"
    assert not old_same_topic.exists()
    assert not old_numeric_same_topic.exists()
    assert not old_slug_same_topic.exists()
    assert other_topic.exists()


def test_prune_older_report_files_by_topic_keeps_latest_each_topic(tmp_path) -> None:
    old_ai = tmp_path / "20260606_120000_AI產業鏈.md"
    latest_ai = tmp_path / "20260607_080000_AI產業鏈.md"
    old_robot = tmp_path / "010_機器人_產業鏈.md"
    latest_robot = tmp_path / "20260607_090000_機器人_產業鏈.md"
    standalone = tmp_path / "單一報告.md"
    for path in (old_ai, latest_ai, old_robot, latest_robot, standalone):
        path.write_text(path.name, encoding="utf-8")

    assert prune_older_report_files_by_topic(tmp_path) == 2

    assert not old_ai.exists()
    assert latest_ai.exists()
    assert not old_robot.exists()
    assert latest_robot.exists()
    assert standalone.exists()


def test_report_file_topic_key_handles_timestamped_and_legacy_names(tmp_path) -> None:
    assert report_file_topic_key(tmp_path / "20260607_080000_AI產業鏈.md") == "AI產業鏈"
    assert report_file_topic_key(tmp_path / "010_機器人_產業鏈.md") == "機器人_產業鏈"
    assert report_file_topic_key(tmp_path / "單一報告.md") == "單一報告"
