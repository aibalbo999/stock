from pathlib import Path

import yaml


def test_docker_compose_defines_redis_and_postgres() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))

    assert "redis" in compose["services"]
    assert "postgres" in compose["services"]
    assert compose["services"]["redis"]["ports"] == ["6379:6379"]
    assert compose["services"]["postgres"]["environment"]["POSTGRES_DB"] == "stock_ai"
