from __future__ import annotations

import subprocess

from scripts.start_system import (
    docker_compose_command,
    pull_missing_dependency_images,
    start_dependency_services,
)


def test_docker_compose_command_prefers_docker_compose_plugin(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return type("Result", (), {"returncode": 0, "stdout": "Docker Compose", "stderr": ""})()

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    assert docker_compose_command() == ["docker", "compose"]
    assert calls == [["docker", "compose", "version"]]


def test_docker_compose_command_falls_back_to_legacy_binary(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return type(
            "Result",
            (),
            {
                "returncode": 1 if command[:2] == ["docker", "compose"] else 0,
                "stdout": "",
                "stderr": "",
            },
        )()

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    assert docker_compose_command() == ["docker-compose"]
    assert calls == [["docker", "compose", "version"], ["docker-compose", "version"]]


def test_start_dependency_services_runs_compose_for_required_services(monkeypatch, tmp_path) -> None:
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text("services: {}\n", encoding="utf-8")
    captured = {}

    monkeypatch.setattr("scripts.start_system.docker_compose_command", lambda: ["docker", "compose"])
    monkeypatch.setattr(
        "scripts.start_system.local_docker_image_status",
        lambda images=None: {"all_present": True, "missing_services": [], "remediation": None},
    )

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    result = start_dependency_services(tmp_path)

    assert result["status"] == "已啟動"
    assert captured["cwd"] == tmp_path
    assert captured["command"][-5:] == ["redis", "postgres", "neo4j", "browserless", "chroma"]
    assert result["services"] == ["redis", "postgres", "neo4j", "browserless", "chroma"]


def test_start_dependency_services_can_include_flaresolverr_unlocker(monkeypatch, tmp_path) -> None:
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text("services: {}\n", encoding="utf-8")
    captured = {}

    monkeypatch.setattr("scripts.start_system.docker_compose_command", lambda: ["docker", "compose"])
    monkeypatch.setattr(
        "scripts.start_system.local_docker_image_status",
        lambda images=None: {
            "all_present": True,
            "missing_services": [],
            "remediation": None,
            "images": images or {},
        },
    )

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    result = start_dependency_services(tmp_path, include_unlocker=True)

    assert result["status"] == "已啟動"
    assert captured["cwd"] == tmp_path
    assert "--profile" in captured["command"]
    assert "unlocker" in captured["command"]
    assert captured["command"][-6:] == [
        "redis",
        "postgres",
        "neo4j",
        "browserless",
        "chroma",
        "flaresolverr",
    ]
    assert result["services"] == ["redis", "postgres", "neo4j", "browserless", "chroma", "flaresolverr"]


def test_start_dependency_services_explains_missing_images_before_compose_pull(
    monkeypatch,
    tmp_path,
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr("scripts.start_system.docker_compose_command", lambda: ["docker", "compose"])
    monkeypatch.setattr(
        "scripts.start_system.local_docker_image_status",
        lambda images=None: {
            "all_present": False,
            "missing_services": ["neo4j", "browserless"],
            "remediation": "docker compose pull neo4j browserless",
        },
    )

    def fake_run(command, **kwargs):
        raise AssertionError("compose up should wait until user allows missing image pull")

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    result = start_dependency_services(tmp_path)

    assert result["status"] == "需下載"
    assert "缺少 Docker image：neo4j、browserless" in result["message"]
    assert "docker compose pull neo4j browserless" in result["message"]
    assert "--pull-missing-dependencies" in result["message"]


def test_start_dependency_services_can_pull_missing_images_when_explicitly_allowed(
    monkeypatch,
    tmp_path,
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr("scripts.start_system.docker_compose_command", lambda: ["docker", "compose"])
    image_statuses = iter(
        [
            {
                "all_present": False,
                "missing_services": ["neo4j"],
                "remediation": "docker compose pull neo4j",
            },
            {"all_present": True, "missing_services": [], "remediation": None},
        ]
    )
    monkeypatch.setattr("scripts.start_system.local_docker_image_status", lambda images=None: next(image_statuses))

    def fake_run(command, **kwargs):
        calls.append(command)
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    result = start_dependency_services(tmp_path, allow_pull_missing_images=True)

    assert result["status"] == "已啟動"
    assert calls[0][-2:] == ["pull", "neo4j"]
    assert calls[1][-5:] == ["redis", "postgres", "neo4j", "browserless", "chroma"]


def test_start_dependency_services_can_pull_missing_flaresolverr_image_when_unlocker_enabled(
    monkeypatch,
    tmp_path,
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr("scripts.start_system.docker_compose_command", lambda: ["docker", "compose"])
    image_statuses = iter(
        [
            {
                "all_present": False,
                "missing_services": ["flaresolverr"],
                "remediation": "docker compose pull flaresolverr",
            },
            {"all_present": True, "missing_services": [], "remediation": None},
        ]
    )
    monkeypatch.setattr("scripts.start_system.local_docker_image_status", lambda images=None: next(image_statuses))

    def fake_run(command, **kwargs):
        calls.append(command)
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    result = start_dependency_services(
        tmp_path,
        allow_pull_missing_images=True,
        include_unlocker=True,
    )

    assert result["status"] == "已啟動"
    assert calls[0][-2:] == ["pull", "flaresolverr"]
    assert calls[1][-6:] == ["redis", "postgres", "neo4j", "browserless", "chroma", "flaresolverr"]


def test_start_dependency_services_reports_missing_image_after_pull(
    monkeypatch,
    tmp_path,
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr("scripts.start_system.docker_compose_command", lambda: ["docker", "compose"])
    monkeypatch.setattr(
        "scripts.start_system.local_docker_image_status",
        lambda images=None: {
            "all_present": False,
            "missing_services": ["neo4j"],
            "remediation": "docker compose pull neo4j",
        },
    )

    def fake_run(command, **kwargs):
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    result = start_dependency_services(tmp_path, allow_pull_missing_images=True)

    assert result["status"] == "失敗"
    assert "下載後仍缺少：neo4j" in result["message"]


def test_pull_missing_dependency_images_reports_service_timeout(monkeypatch, tmp_path) -> None:
    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"])

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    result = pull_missing_dependency_images(
        tmp_path,
        ["docker", "compose"],
        ["neo4j", "browserless", "flaresolverr"],
        timeout_seconds=30,
    )

    assert result["status"] == "失敗"
    assert "Docker image 下載逾時：neo4j" in result["message"]
    assert "docker compose pull neo4j browserless flaresolverr" in result["message"]


def test_start_dependency_services_explains_image_pull_timeout(monkeypatch, tmp_path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr("scripts.start_system.docker_compose_command", lambda: ["docker", "compose"])
    monkeypatch.setattr(
        "scripts.start_system.local_docker_image_status",
        lambda images=None: {"all_present": True, "missing_services": [], "remediation": None},
    )

    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=120)

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    result = start_dependency_services(tmp_path)

    assert result["status"] == "失敗"
    assert "docker compose pull redis postgres neo4j browserless chroma" in result["message"]


def test_start_dependency_services_skips_when_docker_compose_is_missing(monkeypatch, tmp_path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr("scripts.start_system.docker_compose_command", lambda: None)

    result = start_dependency_services(tmp_path)

    assert result["status"] == "略過"
    assert "Docker Compose" in result["message"]
