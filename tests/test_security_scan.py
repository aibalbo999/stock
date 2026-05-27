from pathlib import Path

from scripts.security_scan import scan_paths


def test_security_scan_ignores_css_classes_and_task_ids(tmp_path) -> None:
    path = tmp_path / "sample.py"
    path.write_text(
        """
css = "risk-high task-card task-meta"
task_id = "task-abc"
        """,
        encoding="utf-8",
    )

    assert scan_paths([path], tmp_path) == []


def test_security_scan_detects_realistic_api_keys(tmp_path) -> None:
    path = tmp_path / "sample.py"
    path.write_text(
        'key = "AIza' + "A" * 35 + '"\nopenai = "sk-' + "b" * 40 + '"\n',
        encoding="utf-8",
    )

    findings = scan_paths([path], tmp_path)

    assert {finding["type"] for finding in findings} == {"google_api_key", "openai_api_key"}
    assert all(finding["path"] == Path("sample.py").as_posix() for finding in findings)
