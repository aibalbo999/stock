import os
from typing import Any

import pytest

from app.core.config import get_settings
from app.services.service_status import service_status


COMPANY_FILING_RENDER_ENV_KEYS = (
    "COMPANY_FILING_PROXY_URLS",
    "COMPANY_FILING_BROWSER_RENDER_ENABLED",
    "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
    "COMPANY_FILING_BROWSER_RENDER_URL",
    "COMPANY_FILING_BROWSER_RENDER_TOKEN",
    "COMPANY_FILING_BROWSER_RENDER_TIMEOUT_SECONDS",
    "COMPANY_FILING_BROWSER_RENDER_CONCURRENCY",
    "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED",
    "COMPANY_FILING_PLAYWRIGHT_BROWSER",
    "COMPANY_FILING_PLAYWRIGHT_WAIT_UNTIL",
    "COMPANY_FILING_PLAYWRIGHT_TIMEOUT_SECONDS",
)


@pytest.fixture(autouse=True)
def clear_settings_cache_between_tests() -> None:
    original_env = {key: os.environ.get(key) for key in COMPANY_FILING_RENDER_ENV_KEYS}
    get_settings.cache_clear()
    try:
        yield
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


@pytest.fixture(scope="session")
def service_status_snapshot() -> dict[str, Any]:
    get_settings.cache_clear()
    return service_status()
