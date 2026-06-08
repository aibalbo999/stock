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
    report_dir.mkdir(parents=True, exist_ok=True)
    safe_topic = safe_report_topic(request.topic)
    filename = f"{response.generated_at.strftime('%Y%m%d_%H%M%S')}_{safe_topic}.md"
    path = report_dir / filename.replace("/", "_")
    path.write_text(response.markdown, encoding="utf-8")
    prune_report_files_for_topic(report_dir, safe_topic, keep_path=path)
    return path


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
    if not report_dir.exists():
        return 0
    grouped: dict[str, dict[str, list[Path]]] = {}
    for candidate in report_artifact_files(report_dir):
        grouped.setdefault(report_file_topic_key(candidate), {}).setdefault(
            candidate.stem,
            [],
        ).append(candidate)

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
