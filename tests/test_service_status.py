from app.core.config import Settings
from app.services.candidate_confidence import HIGH_CONFIDENCE_THRESHOLD, MEDIUM_CONFIDENCE_THRESHOLD
from app.services.service_status import _redact_url, service_status


def test_redact_url_with_password() -> None:
    assert _redact_url("redis://user:secret@localhost:6379/0") == "redis://user:***@localhost:6379/0"


def test_service_status_shape() -> None:
    status = service_status()

    assert "redis" in status
    assert "gemini" in status
    assert "finmind" in status
    assert "vector_store" in status
    assert status["candidate_confidence"]["high_threshold"] == HIGH_CONFIDENCE_THRESHOLD
    assert status["candidate_confidence"]["medium_threshold"] == MEDIUM_CONFIDENCE_THRESHOLD


def test_settings_default_api_base_url() -> None:
    assert Settings().api_base_url == "http://127.0.0.1:8000"
