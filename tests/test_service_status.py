from app.services.candidate_confidence import HIGH_CONFIDENCE_THRESHOLD, MEDIUM_CONFIDENCE_THRESHOLD
from app.services.service_status import _redact_url


def test_redact_url_with_password() -> None:
    assert _redact_url("redis://user:secret@localhost:6379/0") == "redis://user:***@localhost:6379/0"


def test_service_status_shape(service_status_snapshot) -> None:
    status = service_status_snapshot

    assert "database" in status
    assert "redis" in status
    assert "gemini" in status
    assert "finmind" in status
    assert "fugle" in status
    assert "market_data_cache" in status
    assert "company_filings" in status
    assert "vector_store" in status
    assert "supply_chain_graph" in status
    assert "workflow_orchestration" in status
    assert "python_runtime" in status
    assert "task_queue" in status
    assert status["candidate_confidence"]["high_threshold"] == HIGH_CONFIDENCE_THRESHOLD
    assert status["candidate_confidence"]["medium_threshold"] == MEDIUM_CONFIDENCE_THRESHOLD
    assert status["candidate_confidence"]["source_credibility_weights"]["official"] == 1.0
    assert status["candidate_confidence"]["source_credibility_weights"]["investment_blog"] < 0.75
