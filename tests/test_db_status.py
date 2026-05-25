from app.db.status import _redact_database_url, db_status


def test_redact_database_url() -> None:
    assert _redact_database_url("sqlite:///./stock_ai.db") == "sqlite:///./stock_ai.db"
    assert (
        _redact_database_url("postgresql://user:password@localhost:5432/db")
        == "postgresql://***@localhost:5432/db"
    )


def test_db_status_contains_core_tables() -> None:
    status = db_status()

    assert "news_articles" in status["tables"]
    assert "company_filings" in status["tables"]
    assert "generated_reports" in status["tables"]
    assert "gemini_key_count" in status["settings"]
