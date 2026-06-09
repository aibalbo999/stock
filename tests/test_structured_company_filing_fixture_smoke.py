from __future__ import annotations

import json
import subprocess

from scripts import structured_company_filing_fixture_smoke as fixture_smoke


class FakeFixtureProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def communicate(self, timeout=None):
        return "fixture stdout", "fixture stderr"


def test_fixture_smoke_starts_fixture_runs_live_smoke_and_cleans_up(tmp_path) -> None:
    process = FakeFixtureProcess()
    captured = {}
    probe_calls = []

    def fake_popen(command, **kwargs):
        captured["serve_command"] = command
        captured["serve_cwd"] = kwargs["cwd"]
        captured["serve_text"] = kwargs["text"]
        return process

    def fake_run(command, **kwargs):
        captured["smoke_command"] = command
        captured["smoke_cwd"] = kwargs["cwd"]
        captured["smoke_env"] = kwargs["env"]
        payload = {
            "status": "ready",
            "ready": True,
            "request": {
                "ticker": "2330",
                "company_name": "台積電",
                "document_types": ["investor_presentation"],
                "limit": 3,
            },
            "document_count": 1,
            "error_count": 0,
            "documents": [{"title": "2330 台積電 法說會", "text_length": 128}],
            "errors": [],
        }
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload, ensure_ascii=False),
            stderr="",
        )

    def fake_url_ready(url, *, timeout):
        probe_calls.append(url)
        return len(probe_calls) >= 2

    report = fixture_smoke.structured_company_filing_fixture_smoke_report(
        root=tmp_path,
        popen_func=fake_popen,
        run_func=fake_run,
        url_ready_func=fake_url_ready,
        sleep_func=lambda _: None,
    )

    assert report["status"] == "ready"
    assert report["ready"] is True
    assert report["fixture_started"] is True
    assert report["reused_existing_fixture"] is False
    assert report["document_count"] == 1
    assert process.terminated is True
    assert process.killed is False
    assert captured["serve_command"][1:] == [
        "scripts/local_structured_company_filing_api.py",
        "--sample-json",
        "examples/structured_company_filing_sample.json",
        "--host",
        "127.0.0.1",
        "--port",
        "8794",
        "--path",
        "/filings",
        "--quiet",
    ]
    assert captured["serve_cwd"] == tmp_path
    assert captured["serve_text"] is True
    assert captured["smoke_command"][1:] == [
        "scripts/structured_company_filing_smoke.py",
        "--ticker",
        "2330",
        "--company-name",
        "台積電",
        "--limit",
        "3",
        "--document-type",
        "investor_presentation",
        "--json",
        "--strict",
    ]
    assert captured["smoke_cwd"] == tmp_path
    assert captured["smoke_env"]["COMPANY_FILING_STRUCTURED_API_PROVIDER"] == "custom"
    assert (
        captured["smoke_env"]["COMPANY_FILING_STRUCTURED_API_URL"]
        == "http://127.0.0.1:8794/filings"
    )
    assert "COMPANY_FILING_STRUCTURED_API_TOKEN" not in captured["smoke_env"]


def test_fixture_smoke_reuses_existing_fixture_without_starting_process(tmp_path) -> None:
    captured = {}

    def fake_popen(command, **kwargs):
        raise AssertionError("fixture server should not be started when probe is already ready")

    def fake_run(command, **kwargs):
        captured["smoke_command"] = command
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "ready", "ready": True, "document_count": 1}),
            stderr="",
        )

    report = fixture_smoke.structured_company_filing_fixture_smoke_report(
        root=tmp_path,
        popen_func=fake_popen,
        run_func=fake_run,
        url_ready_func=lambda url, *, timeout: True,
    )

    assert report["ready"] is True
    assert report["fixture_started"] is False
    assert report["reused_existing_fixture"] is True
    assert captured["smoke_command"][1] == "scripts/structured_company_filing_smoke.py"


def test_fixture_smoke_reports_failed_live_smoke_and_still_cleans_up(tmp_path) -> None:
    process = FakeFixtureProcess()
    probe_calls = []

    def fake_run(command, **kwargs):
        payload = {
            "status": "degraded",
            "ready": False,
            "document_count": 0,
            "error_count": 0,
            "remediation": "No convertible rows.",
        }
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=json.dumps(payload, ensure_ascii=False),
            stderr="",
        )

    def fake_url_ready(url, *, timeout):
        probe_calls.append(url)
        return len(probe_calls) >= 2

    report = fixture_smoke.structured_company_filing_fixture_smoke_report(
        root=tmp_path,
        popen_func=lambda command, **kwargs: process,
        run_func=fake_run,
        url_ready_func=fake_url_ready,
        sleep_func=lambda _: None,
    )

    assert report["status"] == "failed"
    assert report["ready"] is False
    assert report["error_count"] == 1
    assert report["errors"][0]["category"] == "degraded"
    assert report["remediation"] == "No convertible rows."
    assert process.terminated is True
