from __future__ import annotations

import json
from json import JSONDecodeError
from typing import Any, Callable
from urllib.error import URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from app.services.runtime_identity import runtime_identity_status


RUNTIME_IDENTITY_ENDPOINT = "/services/runtime-identity"


def check_api_runtime_identity(
    api_url: str = "http://127.0.0.1:8000",
    *,
    expected_commit: str | None = None,
    endpoint: str = RUNTIME_IDENTITY_ENDPOINT,
    timeout_seconds: float = 10.0,
    opener: Callable[..., Any] | None = None,
) -> dict:
    opener = opener or urlopen
    local_identity = runtime_identity_status()
    expected = str(
        expected_commit if expected_commit is not None else local_identity.get("git_commit") or ""
    )
    url = _join_url(api_url, endpoint)
    result = {
        "label": "api_runtime_identity",
        "url": _iri_to_uri(url),
        "expected_commit": expected,
        "expected_commit_short": expected[:12] if expected else "",
    }
    try:
        payload = _read_json_url(url, timeout_seconds=timeout_seconds, opener=opener)
    except (OSError, URLError, TimeoutError, JSONDecodeError) as exc:
        return {
            **result,
            "status": "failed",
            "error": str(exc) or exc.__class__.__name__,
        }
    identity = payload.get("runtime_identity") if isinstance(payload.get("runtime_identity"), dict) else payload
    actual = str(identity.get("git_commit") or "")
    if not expected:
        return {
            **result,
            "status": "skipped",
            "reason": "local_git_commit_unavailable",
            "actual_commit": actual,
            "actual_commit_short": actual[:12] if actual else "",
        }
    if not actual:
        return {
            **result,
            "status": "failed",
            "reason": "api_runtime_commit_unavailable",
            "actual_commit": "",
        }
    matched = _commits_match(expected, actual)
    return {
        **result,
        "status": "passed" if matched else "failed",
        "actual_commit": actual,
        "actual_commit_short": actual[:12],
        "actual_source": identity.get("source"),
        "actual_dirty": identity.get("git_dirty"),
        "reason": None if matched else "api_runtime_commit_mismatch",
    }


def _read_json_url(
    url: str,
    *,
    timeout_seconds: float,
    opener: Callable[..., Any],
) -> dict:
    request = Request(_iri_to_uri(url), headers={"User-Agent": "stock-ai-runtime-smoke/1.0"})
    with opener(request, timeout=timeout_seconds) as response:
        body = response.read(250_000).decode("utf-8", errors="ignore")
    payload = json.loads(body)
    return payload if isinstance(payload, dict) else {"value": payload}


def _commits_match(expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    if len(expected) >= 7 and len(actual) >= 7:
        return expected.startswith(actual) or actual.startswith(expected)
    return False


def _join_url(base_url: str, endpoint: str) -> str:
    return base_url.rstrip("/") + "/" + endpoint.lstrip("/")


def _iri_to_uri(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            quote(parsed.path, safe="/%"),
            quote(parsed.query, safe="=&%:/?+-_.,"),
            quote(parsed.fragment, safe="=&%:/?+-_.,"),
        )
    )
