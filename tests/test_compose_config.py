from pathlib import Path

import yaml


def test_docker_compose_defines_dependencies_and_celery_services() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))

    assert "redis" in compose["services"]
    assert "postgres" in compose["services"]
    assert "neo4j" in compose["services"]
    assert "browserless" in compose["services"]
    assert "flaresolverr" in compose["services"]
    assert "chroma" in compose["services"]
    assert "celery-worker" in compose["services"]
    assert "celery-beat" in compose["services"]
    assert compose["services"]["redis"]["ports"] == ["6379:6379"]
    assert compose["services"]["postgres"]["environment"]["POSTGRES_DB"] == "stock_ai"
    assert compose["services"]["neo4j"]["ports"] == ["7474:7474", "7687:7687"]
    assert compose["services"]["neo4j"]["environment"]["NEO4J_AUTH"].startswith("neo4j/")
    assert compose["services"]["browserless"]["ports"] == ["3000:3000"]
    assert compose["services"]["browserless"]["environment"]["TOKEN"] == "stock_ai_browserless_token"
    assert compose["services"]["browserless"]["environment"]["CONCURRENT"] == "4"
    assert "json/version?token=stock_ai_browserless_token" in compose["services"]["browserless"]["healthcheck"]["test"][1]
    assert compose["services"]["flaresolverr"]["profiles"] == ["unlocker"]
    assert compose["services"]["flaresolverr"]["ports"] == ["8191:8191"]
    assert compose["services"]["flaresolverr"]["image"] == "ghcr.io/flaresolverr/flaresolverr:latest"
    assert "http://127.0.0.1:8191/health" in compose["services"]["flaresolverr"]["healthcheck"]["test"][1]
    assert compose["services"]["chroma"]["image"] == "chromadb/chroma:latest"
    assert compose["services"]["chroma"]["ports"] == ["8001:8000"]
    assert "api/v2/heartbeat" in compose["services"]["chroma"]["healthcheck"]["test"][1]
    worker = compose["services"]["celery-worker"]
    beat = compose["services"]["celery-beat"]
    assert worker["depends_on"]["browserless"]["condition"] == "service_healthy"
    assert worker["depends_on"]["chroma"]["condition"] == "service_healthy"
    assert worker["environment"]["DATABASE_URL"].startswith("postgresql+psycopg://stock_ai:")
    assert worker["environment"]["REDIS_URL"] == "redis://redis:6379/0"
    assert worker["environment"]["CHROMA_API_URL"] == "http://chroma:8000"
    assert (
        worker["environment"]["COMPANY_FILING_BROWSER_RENDER_PROVIDER"]
        == "${COMPANY_FILING_BROWSER_RENDER_PROVIDER:-browserless}"
    )
    assert (
        worker["environment"]["COMPANY_FILING_BROWSER_RENDER_URL"]
        == "${COMPANY_FILING_BROWSER_RENDER_URL:-http://browserless:3000/content?token=stock_ai_browserless_token}"
    )
    assert (
        worker["environment"]["COMPANY_FILING_BROWSER_RENDER_TOKEN"]
        == "${COMPANY_FILING_BROWSER_RENDER_TOKEN:-stock_ai_browserless_token}"
    )
    assert worker["environment"]["COMPANY_FILING_BROWSER_RENDER_CONCURRENCY"] == "4"
    assert worker["command"][:4] == [
        "celery",
        "-A",
        "app.tasks.celery_app.celery_app",
        "worker",
    ]
    assert beat["command"][:4] == [
        "celery",
        "-A",
        "app.tasks.celery_app.celery_app",
        "beat",
    ]
    assert "neo4j_data" in compose["volumes"]
    assert "chroma_data" in compose["volumes"]
    assert "celerybeat_data" in compose["volumes"]
