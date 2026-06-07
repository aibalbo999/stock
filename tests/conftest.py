from typing import Any

import pytest

from app.services.service_status import service_status


@pytest.fixture(scope="session")
def service_status_snapshot() -> dict[str, Any]:
    return service_status()
