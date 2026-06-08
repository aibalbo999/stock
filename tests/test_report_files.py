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
    old_same_topic_html = tmp_path / "20260606_120000_記憶體產業鏈.html"
    old_same_topic_pdf = tmp_path / "20260606_120000_記憶體產業鏈.pdf"
    old_numeric_same_topic = tmp_path / "010_記憶體產業鏈.md"
    old_slug_same_topic = tmp_path / "legacy_記憶體產業鏈.md"
    other_topic = tmp_path / "009_機器人_產業鏈.md"
    other_topic_html = tmp_path / "009_機器人_產業鏈.html"
    old_same_topic.write_text("old", encoding="utf-8")
    old_same_topic_html.write_text("old html", encoding="utf-8")
    old_same_topic_pdf.write_text("old pdf", encoding="utf-8")
    old_numeric_same_topic.write_text("old numeric", encoding="utf-8")
    old_slug_same_topic.write_text("old slug", encoding="utf-8")
    other_topic.write_text("robot", encoding="utf-8")
    other_topic_html.write_text("robot html", encoding="utf-8")

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
    assert not old_same_topic_html.exists()
    assert not old_same_topic_pdf.exists()
    assert not old_numeric_same_topic.exists()
    assert not old_slug_same_topic.exists()
    assert other_topic.exists()
    assert other_topic_html.exists()


def test_prune_older_report_files_by_topic_keeps_latest_each_topic(tmp_path) -> None:
    old_ai = tmp_path / "20260606_120000_AI產業鏈.md"
    old_ai_html = tmp_path / "20260606_120000_AI產業鏈.html"
    old_ai_pdf = tmp_path / "20260606_120000_AI產業鏈.pdf"
    latest_ai = tmp_path / "20260607_080000_AI產業鏈.md"
    latest_ai_html = tmp_path / "20260607_080000_AI產業鏈.html"
    latest_ai_pdf = tmp_path / "20260607_080000_AI產業鏈.pdf"
    old_robot = tmp_path / "010_機器人_產業鏈.md"
    old_robot_html = tmp_path / "010_機器人_產業鏈.html"
    latest_robot = tmp_path / "20260607_090000_機器人_產業鏈.md"
    latest_robot_pdf = tmp_path / "20260607_090000_機器人_產業鏈.pdf"
    standalone = tmp_path / "單一報告.md"
    standalone_html = tmp_path / "單一報告.html"
    for path in (
        old_ai,
        old_ai_html,
        old_ai_pdf,
        latest_ai,
        latest_ai_html,
        latest_ai_pdf,
        old_robot,
        old_robot_html,
        latest_robot,
        latest_robot_pdf,
        standalone,
        standalone_html,
    ):
        path.write_text(path.name, encoding="utf-8")

    assert prune_older_report_files_by_topic(tmp_path) == 5

    assert not old_ai.exists()
    assert not old_ai_html.exists()
    assert not old_ai_pdf.exists()
    assert latest_ai.exists()
    assert latest_ai_html.exists()
    assert latest_ai_pdf.exists()
    assert not old_robot.exists()
    assert not old_robot_html.exists()
    assert latest_robot.exists()
    assert latest_robot_pdf.exists()
    assert standalone.exists()
    assert standalone_html.exists()


def test_report_file_topic_key_handles_timestamped_and_legacy_names(tmp_path) -> None:
    assert report_file_topic_key(tmp_path / "20260607_080000_AI產業鏈.md") == "AI產業鏈"
    assert report_file_topic_key(tmp_path / "010_機器人_產業鏈.md") == "機器人_產業鏈"
    assert report_file_topic_key(tmp_path / "單一報告.md") == "單一報告"
