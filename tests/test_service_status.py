from app.core.config import Settings
from app.services.candidate_confidence import HIGH_CONFIDENCE_THRESHOLD, MEDIUM_CONFIDENCE_THRESHOLD
from app.services.llm_client import DEFAULT_MAX_RETRIES_PER_KEY, RETRYABLE_HTTP_STATUSES
from app.services.service_status import _redact_url, service_status


def test_redact_url_with_password() -> None:
    assert _redact_url("redis://user:secret@localhost:6379/0") == "redis://user:***@localhost:6379/0"


def test_service_status_shape() -> None:
    status = service_status()

    assert "redis" in status
    assert "gemini" in status
    assert "finmind" in status
    assert "vector_store" in status
    assert status["gemini"]["retryable_http_statuses"] == sorted(RETRYABLE_HTTP_STATUSES)
    assert status["gemini"]["max_retries_per_key"] == DEFAULT_MAX_RETRIES_PER_KEY
    assert status["gemini"]["base_retry_delay_seconds"] == 0.5
    assert status["gemini"]["max_retry_delay_seconds"] == 5.0
    assert status["candidate_confidence"]["high_threshold"] == HIGH_CONFIDENCE_THRESHOLD
    assert status["candidate_confidence"]["medium_threshold"] == MEDIUM_CONFIDENCE_THRESHOLD


def test_settings_default_api_base_url() -> None:
    assert Settings().api_base_url == "http://127.0.0.1:8000"


def test_candidate_confidence_threshold_settings_defaults() -> None:
    settings = Settings()

    assert settings.candidate_confidence_high_threshold == HIGH_CONFIDENCE_THRESHOLD
    assert settings.candidate_confidence_medium_threshold == MEDIUM_CONFIDENCE_THRESHOLD


def test_llm_retry_settings_defaults() -> None:
    settings = Settings()

    assert settings.llm_max_retries_per_key == DEFAULT_MAX_RETRIES_PER_KEY
    assert settings.llm_base_retry_delay_seconds == 0.5
    assert settings.llm_max_retry_delay_seconds == 5.0
