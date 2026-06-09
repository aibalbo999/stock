from pathlib import Path


LLM_USAGE_CALLER_PATHS = (
    Path("app/services/llm_usage.py"),
    Path("app/services/llm_quota.py"),
    Path("app/services/llm_api.py"),
)


def test_llm_usage_callers_import_repository_directly() -> None:
    for path in LLM_USAGE_CALLER_PATHS:
        source = path.read_text()

        assert "from app.services.persistence import LLMUsageRepository" not in source
        assert "from app.services.llm_usage_repository import LLMUsageRepository" in source
