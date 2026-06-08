from __future__ import annotations

import asyncio
from hashlib import sha1
import importlib
from pathlib import Path
import re
import socket
from urllib.parse import quote, urlparse

import httpx

from app.core.config import get_settings


BROWSER_RENDER_PROVIDERS = {"browserless", "generic", "flaresolverr", "scrapingbee", "brightdata"}
HIGH_RISK_COMPANY_FILING_SOURCE_DOMAINS = (
    "mops.twse.com.tw",
    "mopsov.twse.com.tw",
    "doc.twse.com.tw",
    "www.twse.com.tw",
    "www.tpex.org.tw",
)
UNLOCKER_BROWSER_RENDER_PROVIDERS = {"brightdata", "flaresolverr", "scrapingbee"}
BROWSER_RENDER_PROVIDER_CAPABILITIES = {
    "browserless": {
        "tier": "browser_render",
        "captcha_unlocker": False,
        "purpose": "JavaScript rendering and browser-like page fetches.",
    },
    "generic": {
        "tier": "browser_render",
        "captcha_unlocker": False,
        "purpose": "Custom browser rendering endpoint.",
    },
    "flaresolverr": {
        "tier": "unlocker",
        "captcha_unlocker": True,
        "purpose": "Cloudflare/CAPTCHA challenge solving for protected public pages.",
    },
    "scrapingbee": {
        "tier": "managed_unlocker",
        "captcha_unlocker": True,
        "purpose": "Managed anti-bot rendering and proxy-backed public page fetches.",
    },
    "brightdata": {
        "tier": "managed_unlocker",
        "captcha_unlocker": True,
        "purpose": "Managed proxy/unlocker rendering for high-risk disclosure sources.",
    },
}
BROWSER_RENDER_PROVIDER_CONTRACT_SMOKE_CLI = (
    ".venv/bin/python scripts/company_filing_render_smoke.py --provider-contract --json"
)
DEFAULT_COMPANY_FILING_USER_AGENTS = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
)
_BROWSER_RENDER_SEMAPHORES: dict[tuple[int, int], asyncio.Semaphore] = {}


def _split_config_values(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[\n,]+", value or "") if item.strip()]


def _stable_config_choice(
    values: list[str] | tuple[str, ...],
    key: str,
    attempt: int = 0,
) -> str:
    if not values:
        return ""
    digest = sha1(key.encode("utf-8")).hexdigest()
    offset = max(0, int(attempt))
    return values[(int(digest[:8], 16) + offset) % len(values)]


def company_filing_user_agents() -> list[str]:
    configured = _split_config_values(get_settings().company_filing_user_agents)
    return configured or list(DEFAULT_COMPANY_FILING_USER_AGENTS)


def company_filing_proxy_urls() -> list[str]:
    return _split_config_values(get_settings().company_filing_proxy_urls)


def company_filing_identity_for_url(url: str, attempt: int = 0) -> dict:
    user_agents = company_filing_user_agents()
    proxy_urls = company_filing_proxy_urls()
    return {
        "attempt": max(0, int(attempt)),
        "user_agent": _stable_config_choice(user_agents, url, attempt),
        "proxy": _stable_config_choice(proxy_urls, url, attempt) or None,
        "user_agent_count": len(user_agents),
        "proxy_count": len(proxy_urls),
    }


def company_filing_user_agent_for_url(url: str, attempt: int = 0) -> str:
    return str(company_filing_identity_for_url(url, attempt).get("user_agent") or "")


def company_filing_proxy_for_url(url: str, attempt: int = 0) -> str | None:
    proxy = company_filing_identity_for_url(url, attempt).get("proxy")
    return str(proxy) if proxy else None


def company_filing_browser_render_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.company_filing_browser_render_enabled
        and settings.company_filing_browser_render_url.strip()
        and company_filing_browser_render_provider() in BROWSER_RENDER_PROVIDERS
    )


def company_filing_browser_render_provider() -> str:
    provider = str(getattr(get_settings(), "company_filing_browser_render_provider", "browserless") or "")
    provider = provider.strip().lower().replace("-", "_")
    return provider or "browserless"


def company_filing_browser_render_provider_capability(provider: str) -> dict:
    provider_key = (provider or "browserless").strip().lower().replace("-", "_")
    capability = dict(
        BROWSER_RENDER_PROVIDER_CAPABILITIES.get(
            provider_key,
            {
                "tier": "unsupported",
                "captcha_unlocker": False,
                "purpose": "Unsupported company filing browser render provider.",
            },
        )
    )
    capability["provider"] = provider_key
    return capability


def company_filing_browser_render_status(
    *,
    enabled: bool | None = None,
    endpoint: str | None = None,
    timeout_seconds: float | None = None,
) -> dict:
    settings = get_settings()
    render_enabled = (
        settings.company_filing_browser_render_enabled
        if enabled is None
        else bool(enabled)
    )
    render_endpoint = str(
        settings.company_filing_browser_render_url if endpoint is None else endpoint
    ).strip()
    configured_timeout = (
        settings.company_filing_browser_render_timeout_seconds
        if timeout_seconds is None
        else timeout_seconds
    )
    timeout = max(
        0.2,
        min(5.0, float(configured_timeout)),
    )
    status = {
        "enabled": bool(render_enabled),
        "provider": company_filing_browser_render_provider(),
        "supported_providers": sorted(BROWSER_RENDER_PROVIDERS),
        "provider_capabilities": {
            provider: company_filing_browser_render_provider_capability(provider)
            for provider in sorted(BROWSER_RENDER_PROVIDERS)
        },
        "url_configured": bool(render_endpoint),
        "endpoint": render_endpoint,
        "connection_checked": False,
        "endpoint_reachable": False,
        "runtime_available": False,
        "smoke_cli": ".venv/bin/python scripts/company_filing_render_smoke.py --url https://example.com/ --json",
        "high_risk_domains": list(HIGH_RISK_COMPANY_FILING_SOURCE_DOMAINS),
        "recommended_high_risk_providers": sorted(UNLOCKER_BROWSER_RENDER_PROVIDERS),
        "high_risk_runtime_available": False,
        "fallback_reason": None,
    }
    status["provider_capability"] = company_filing_browser_render_provider_capability(
        str(status["provider"])
    )
    status["captcha_unlocker_provider"] = bool(
        status["provider_capability"].get("captcha_unlocker")
    )
    if not render_enabled:
        status["fallback_reason"] = "browser_render_disabled"
        return status
    if status["provider"] not in BROWSER_RENDER_PROVIDERS:
        status["fallback_reason"] = "unsupported_browser_render_provider"
        return status
    if not render_endpoint:
        status["fallback_reason"] = "missing_browser_render_url"
        return status

    parsed = urlparse(render_endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        status["fallback_reason"] = "invalid_browser_render_url"
        return status
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=timeout):
            pass
    except OSError as exc:
        status["connection_checked"] = True
        status["fallback_reason"] = f"browser_render_endpoint_unreachable:{exc.__class__.__name__}"
        return status

    status["connection_checked"] = True
    status["endpoint_reachable"] = True
    status["runtime_available"] = True
    status["high_risk_runtime_available"] = bool(status["captcha_unlocker_provider"])
    return status


def company_filing_browser_render_concurrency() -> int:
    return max(1, int(get_settings().company_filing_browser_render_concurrency))


def company_filing_browser_render_limiter() -> asyncio.Semaphore:
    limit = company_filing_browser_render_concurrency()
    loop = asyncio.get_running_loop()
    key = (id(loop), limit)
    semaphore = _BROWSER_RENDER_SEMAPHORES.get(key)
    if semaphore is None:
        semaphore = asyncio.Semaphore(limit)
        _BROWSER_RENDER_SEMAPHORES[key] = semaphore
    return semaphore


def company_filing_browser_render_request(
    *,
    provider: str,
    endpoint: str,
    target_url: str,
    headers: dict[str, str],
    token: str,
    timeout_seconds: float,
) -> tuple[str, str, dict]:
    provider = (provider or "browserless").strip().lower().replace("-", "_")
    rendered_url = endpoint
    if "{url}" in endpoint:
        return endpoint.format(url=quote(target_url, safe="")), "GET", {"headers": headers}
    if provider == "flaresolverr":
        return (
            rendered_url,
            "POST",
            {
                "headers": {**headers, "Content-Type": "application/json"},
                "json": {
                    "cmd": "request.get",
                    "url": target_url,
                    "maxTimeout": int(max(1.0, timeout_seconds) * 1000),
                },
            },
        )
    if provider == "scrapingbee":
        params = {"url": target_url, "render_js": "true"}
        if token:
            params["api_key"] = token
        return rendered_url, "GET", {"headers": headers, "params": params}
    if provider == "brightdata":
        request_headers = dict(headers)
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        return (
            rendered_url,
            "POST",
            {
                "headers": request_headers,
                "json": {"url": target_url, "format": "raw"},
            },
        )

    request_headers = dict(headers)
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    return (
        rendered_url,
        "POST",
        {
            "headers": request_headers,
            "json": {"url": target_url, "waitUntil": "networkidle0"},
        },
    )


def company_filing_browser_render_response_text(
    response: httpx.Response,
    *,
    provider: str,
    target_url: str,
) -> tuple[str, str]:
    provider = (provider or "browserless").strip().lower().replace("-", "_")
    if provider == "flaresolverr":
        payload = response.json()
        solution = payload.get("solution") if isinstance(payload, dict) else {}
        if not isinstance(solution, dict):
            solution = {}
        html = str(solution.get("response") or "")
        final_url = str(solution.get("url") or target_url)
        if not html:
            raise ValueError("FlareSolverr response did not include solution.response")
        return html, final_url
    return response.text, target_url


def company_filing_browser_render_provider_contract_status(
    *,
    target_url: str = "https://example.com/",
) -> dict:
    rows = [
        _browser_render_provider_contract_row(provider, target_url=target_url)
        for provider in sorted(BROWSER_RENDER_PROVIDERS)
    ]
    ready = all(row.get("ready") for row in rows)
    return {
        "status": "ready" if ready else "degraded",
        "ready": ready,
        "target_url": target_url,
        "provider_count": len(rows),
        "providers": rows,
        "smoke_cli": BROWSER_RENDER_PROVIDER_CONTRACT_SMOKE_CLI,
        "remediation": None
        if ready
        else "Inspect company filing render provider request/response contract rows.",
    }


def _browser_render_provider_contract_row(provider: str, *, target_url: str) -> dict:
    endpoint = _browser_render_provider_contract_endpoint(provider)
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "User-Agent": "company-filing-render-contract-smoke",
    }
    try:
        rendered_url, method, request_kwargs = company_filing_browser_render_request(
            provider=provider,
            endpoint=endpoint,
            target_url=target_url,
            headers=headers,
            token="contract-sample",
            timeout_seconds=30.0,
        )
        response_html, final_url = _browser_render_provider_contract_response(
            provider,
            target_url=target_url,
        )
    except Exception as exc:
        return {
            "provider": provider,
            "ready": False,
            "error": f"{exc.__class__.__name__}: {exc}",
        }
    return {
        "provider": provider,
        "ready": bool(response_html),
        "method": method,
        "endpoint": rendered_url,
        "request_contract": _browser_render_request_contract_summary(
            request_kwargs,
            target_url,
        ),
        "response_contract": {
            "parser_ready": bool(response_html),
            "final_url": final_url,
            "html_length": len(response_html),
        },
    }


def _browser_render_provider_contract_endpoint(provider: str) -> str:
    endpoints = {
        "brightdata": "https://api.brightdata.com/request",
        "browserless": "https://browserless.example/content",
        "flaresolverr": "http://flaresolverr:8191/v1",
        "generic": "https://render.example/content",
        "scrapingbee": "https://app.scrapingbee.com/api/v1",
    }
    return endpoints.get(provider, "https://render.example/content")


def _browser_render_provider_contract_response(
    provider: str,
    *,
    target_url: str,
) -> tuple[str, str]:
    if provider == "flaresolverr":
        response = httpx.Response(
            200,
            json={
                "status": "ok",
                "solution": {
                    "url": f"{target_url.rstrip('/')}/rendered",
                    "response": "<html><body>company filing render contract</body></html>",
                },
            },
            request=httpx.Request(
                "POST",
                _browser_render_provider_contract_endpoint(provider),
            ),
        )
    else:
        response = httpx.Response(
            200,
            text="<html><body>company filing render contract</body></html>",
            request=httpx.Request(
                "GET",
                _browser_render_provider_contract_endpoint(provider),
            ),
        )
    return company_filing_browser_render_response_text(
        response,
        provider=provider,
        target_url=target_url,
    )


def _browser_render_request_contract_summary(
    request_kwargs: dict,
    target_url: str,
) -> dict:
    headers = (
        request_kwargs.get("headers")
        if isinstance(request_kwargs.get("headers"), dict)
        else {}
    )
    json_payload = (
        request_kwargs.get("json")
        if isinstance(request_kwargs.get("json"), dict)
        else {}
    )
    params = (
        request_kwargs.get("params")
        if isinstance(request_kwargs.get("params"), dict)
        else {}
    )
    return {
        "header_keys": sorted(headers),
        "authorization_header_configured": "Authorization" in headers,
        "json_keys": sorted(json_payload),
        "param_keys": sorted(params),
        "target_url_attached": target_url in {json_payload.get("url"), params.get("url")},
        "query_auth_param_configured": "api_key" in params,
    }


def company_filing_playwright_render_enabled() -> bool:
    return bool(get_settings().company_filing_playwright_render_enabled)


def company_filing_playwright_available() -> bool:
    try:
        return importlib.util.find_spec("playwright.async_api") is not None
    except (ImportError, ValueError):
        return False


def company_filing_playwright_browser_status(browser_name: str | None = None) -> dict:
    browser = (
        str(browser_name or get_settings().company_filing_playwright_browser or "chromium")
        .strip()
        .lower()
    )
    dependency_available = company_filing_playwright_available()
    status = {
        "browser": browser,
        "dependency_available": dependency_available,
        "browser_available": False,
        "browser_executable_exists": False,
        "executable_path": None,
        "smoke_cli": ".venv/bin/python scripts/company_filing_render_smoke.py --url https://example.com/ --json",
        "fallback_reason": None,
    }
    if not dependency_available:
        status["fallback_reason"] = "missing_dependency:playwright"
        return status
    try:
        playwright_sync_api = importlib.import_module("playwright.sync_api")
        sync_playwright = getattr(playwright_sync_api, "sync_playwright", None)
        if sync_playwright is None:
            status["fallback_reason"] = "missing_dependency:playwright.sync_api"
            return status
        with sync_playwright() as playwright:
            launcher = getattr(playwright, browser, None)
            if launcher is None:
                status["fallback_reason"] = f"unsupported_browser:{browser}"
                return status
            executable_path = getattr(launcher, "executable_path", None)
    except Exception as exc:
        status["fallback_reason"] = f"browser_runtime_check_failed:{exc.__class__.__name__}"
        return status

    if not executable_path:
        status["fallback_reason"] = f"missing_browser_executable_path:{browser}"
        return status
    status["executable_path"] = str(executable_path)
    executable_exists = Path(str(executable_path)).exists()
    status["browser_executable_exists"] = executable_exists
    status["browser_available"] = executable_exists
    if not executable_exists:
        status["fallback_reason"] = (
            f"missing_browser_binary:{browser}; run python -m playwright install {browser}"
        )
    return status


def company_filing_render_fallback_configured() -> bool:
    return company_filing_browser_render_configured() or (
        company_filing_playwright_render_enabled() and company_filing_playwright_available()
    )
