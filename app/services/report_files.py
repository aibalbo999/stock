from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any

from app.models.schemas import ReportRequest


TIMESTAMPED_REPORT_PATTERN = re.compile(r"^(?P<date>\d{8})_(?P<time>\d{6})_(?P<topic>.+)$")
PREFIXED_REPORT_PATTERN = re.compile(r"^\d+_(?P<topic>.+)$")
REPORT_ARTIFACT_SUFFIXES = frozenset({".md", ".html", ".pdf"})


def write_report_file(report_dir: Path, request: ReportRequest, response: Any) -> Path:
    return write_report_file_with_retention(report_dir, request, response)["path"]


def write_report_file_with_retention(
    report_dir: Path,
    request: ReportRequest,
    response: Any,
) -> dict:
    report_dir.mkdir(parents=True, exist_ok=True)
    safe_topic = safe_report_topic(request.topic)
    filename = f"{response.generated_at.strftime('%Y%m%d_%H%M%S')}_{safe_topic}.md"
    path = report_dir / filename.replace("/", "_")
    path.write_text(response.markdown, encoding="utf-8")
    deleted = prune_report_files_for_topic(report_dir, safe_topic, keep_path=path)
    return {
        "policy": "latest_per_topic",
        "topic": safe_topic,
        "path": path,
        "old_report_files_deleted": deleted,
    }


def safe_report_topic(topic: str) -> str:
    return str(topic or "report").replace("/", "_")


def prune_report_files_for_topic(report_dir: Path, safe_topic: str, *, keep_path: Path) -> int:
    deleted = 0
    keep_path = keep_path.resolve()
    keep_stem = keep_path.stem
    for candidate in report_artifact_files(report_dir):
        if candidate.resolve() == keep_path or candidate.stem == keep_stem:
            continue
        if not report_file_matches_topic(candidate, safe_topic):
            continue
        deleted += _unlink_report_file(candidate)
    return deleted


def prune_older_report_files_by_topic(report_dir: Path) -> int:
    grouped = _report_versions_by_topic(report_dir)
    deleted = 0
    for report_versions in grouped.values():
        if len(report_versions) <= 1:
            continue
        keep_stem = max(
            report_versions,
            key=lambda stem: report_artifact_version_sort_key(report_versions[stem]),
        )
        for stem, files in report_versions.items():
            if stem == keep_stem:
                continue
            for candidate in files:
                deleted += _unlink_report_file(candidate)
    return deleted


def report_retention_preview(report_dir: Path) -> dict:
    grouped = _report_versions_by_topic(report_dir)
    topics = []
    deletable_artifact_count = 0
    retained_artifact_count = 0
    for topic, report_versions in sorted(grouped.items()):
        keep_stem = max(
            report_versions,
            key=lambda stem: report_artifact_version_sort_key(report_versions[stem]),
        )
        retained_files = sorted(path.name for path in report_versions[keep_stem])
        deletable_files = sorted(
            path.name
            for stem, files in report_versions.items()
            if stem != keep_stem
            for path in files
        )
        deletable_artifact_count += len(deletable_files)
        retained_artifact_count += len(retained_files)
        topics.append(
            {
                "topic": topic,
                "version_count": len(report_versions),
                "artifact_count": sum(len(files) for files in report_versions.values()),
                "retained_stem": keep_stem,
                "retained_files": retained_files,
                "deletable_files": deletable_files,
                "deletable_artifact_count": len(deletable_files),
            }
        )

    return {
        "policy": "latest_per_topic",
        "report_dir": str(report_dir),
        "report_dir_exists": report_dir.exists(),
        "topic_count": len(topics),
        "stale_topic_count": sum(1 for row in topics if row["deletable_artifact_count"]),
        "artifact_count": sum(int(row["artifact_count"]) for row in topics),
        "retained_artifact_count": retained_artifact_count,
        "deletable_artifact_count": deletable_artifact_count,
        "topics": topics,
    }


def _report_versions_by_topic(report_dir: Path) -> dict[str, dict[str, list[Path]]]:
    grouped: dict[str, dict[str, list[Path]]] = {}
    for candidate in report_artifact_files(report_dir):
        grouped.setdefault(report_file_topic_key(candidate), {}).setdefault(
            candidate.stem,
            [],
        ).append(candidate)
    return grouped


def report_artifact_files(report_dir: Path) -> list[Path]:
    if not report_dir.exists():
        return []
    return [
        candidate
        for candidate in report_dir.iterdir()
        if candidate.is_file() and candidate.suffix.lower() in REPORT_ARTIFACT_SUFFIXES
    ]


def report_file_matches_topic(path: Path, safe_topic: str) -> bool:
    stem = path.stem
    return report_file_topic_key(path) == safe_topic or stem == safe_topic or stem.endswith(f"_{safe_topic}")


def report_file_topic_key(path: Path) -> str:
    stem = path.stem
    timestamped = TIMESTAMPED_REPORT_PATTERN.match(stem)
    if timestamped:
        return timestamped.group("topic")
    prefixed = PREFIXED_REPORT_PATTERN.match(stem)
    if prefixed:
        return prefixed.group("topic")
    return stem


def report_file_sort_key(path: Path) -> tuple[datetime, float, str]:
    parsed = _report_file_timestamp(path)
    try:
        modified_at = path.stat().st_mtime
    except OSError:
        modified_at = 0.0
    return parsed or datetime.min, modified_at, path.name


def report_artifact_version_sort_key(paths: list[Path]) -> tuple[datetime, float, str]:
    if not paths:
        return datetime.min, 0.0, ""
    return max(report_file_sort_key(path) for path in paths)


def _report_file_timestamp(path: Path) -> datetime | None:
    match = TIMESTAMPED_REPORT_PATTERN.match(path.stem)
    if not match:
        return None
    try:
        return datetime.strptime(
            f"{match.group('date')}_{match.group('time')}",
            "%Y%m%d_%H%M%S",
        )
    except ValueError:
        return None


def _unlink_report_file(path: Path) -> int:
    try:
        path.unlink()
    except FileNotFoundError:
        return 0
    except OSError:
        return 0
    return 1
