from pathlib import Path

import yaml


def test_docker_compose_defines_redis_postgres_neo4j_and_browserless() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))

    assert "redis" in compose["services"]
    assert "postgres" in compose["services"]
    assert "neo4j" in compose["services"]
    assert "browserless" in compose["services"]
    assert compose["services"]["redis"]["ports"] == ["6379:6379"]
    assert compose["services"]["postgres"]["environment"]["POSTGRES_DB"] == "stock_ai"
    assert compose["services"]["neo4j"]["ports"] == ["7474:7474", "7687:7687"]
    assert compose["services"]["neo4j"]["environment"]["NEO4J_AUTH"].startswith("neo4j/")
    assert compose["services"]["browserless"]["ports"] == ["3000:3000"]
    assert compose["services"]["browserless"]["environment"]["TOKEN"] == "stock_ai_browserless_token"
    assert "neo4j_data" in compose["volumes"]
