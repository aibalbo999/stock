from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from app.core.config import get_settings
from app.data_sources.company_filing_http import company_filing_error
from app.data_sources.company_filing_render import (
    company_filing_browser_render_provider,
    company_filing_browser_render_provider_contract_status,
    company_filing_browser_render_status,
    company_filing_playwright_browser_status,
    company_filing_proxy_urls,
)
from app.data_sources.company_filings import CompanyFilingFetcher
from app.services.local_dependency_diagnostics import (
    LOCAL_BROWSERLESS_PORT,
    LOCAL_BROWSER_RENDER_ENV_DEFAULTS,
    LOCAL_FLARESOLVERR_PORT,
    LOCAL_FLARESOLVERR_RENDER_ENV_DEFAULTS,
    is_local_port_open,
)


DEFAULT_SMOKE_URL = "https://example.com/"
SMOKE_COMMAND = (
    ".venv/bin/python scripts/company_filing_render_smoke.py "
    "--url https://example.com/ --json"
)
PROVIDER_CONTRACT_SMOKE_COMMAND = (
    ".venv/bin/python scripts/company_filing_render_smoke.py "
    "--provider-contract --json"
)


def apply_local_browser_render_defaults(
    *,
    prefer_browserless: bool = False,
    prefer_unlocker: bool = False,
) -> dict[str, str]:
    cache_clear = getattr(get_settings, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()
    settings = get_settings()
    if prefer_unlocker and is_local_port_open("127.0.0.1", LOCAL_FLARESOLVERR_PORT):
        defaults = LOCAL_FLARESOLVERR_RENDER_ENV_DEFAULTS
        applied = {}
        for key, value in defaults.items():
            os.environ[key] = value
            applied[key] = value
        os.environ.pop("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", None)
        if callable(cache_clear):
            cache_clear()
        return applied
    if settings.company_filing_proxy_urls:
        return {}
    if (
        settings.company_filing_browser_render_enabled
        and settings.company_filing_browser_render_url
    ):
        return {}
    if settings.company_filing_playwright_render_enabled:
        return {}
    defaults = None
    if prefer_browserless or is_local_port_open("127.0.0.1", LOCAL_BROWSERLESS_PORT):
        defaults = LOCAL_BROWSER_RENDER_ENV_DEFAULTS
    elif is_local_port_open("127.0.0.1", LOCAL_FLARESOLVERR_PORT):
        defaults = LOCAL_FLARESOLVERR_RENDER_ENV_DEFAULTS
    if not defaults:
        return {}
    applied = {}
    for key, value in defaults.items():
        if key == "COMPANY_FILING_BROWSER_RENDER_PROVIDER" and not prefer_unlocker:
            continue
        os.environ[key] = value
        applied[key] = value
    if callable(cache_clear):
        cache_clear()
    return applied


async def company_filing_render_smoke_report(
    *,
    url: str = DEFAULT_SMOKE_URL,
    min_text_chars: int = 20,
    fetcher: CompanyFilingFetcher | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    browser_runtime, playwright_runtime, proxy_urls = await asyncio.to_thread(
        render_runtime_snapshot,
        settings.company_filing_playwright_browser,
    )
    proxy_configured = bool(proxy_urls)
    attempts = render_smoke_attempt_plan(
        browser_runtime=browser_runtime,
        playwright_runtime=playwright_runtime,
        browser_render_enabled=bool(settings.company_filing_browser_render_enabled),
        playwright_render_enabled=bool(settings.company_filing_playwright_render_enabled),
        proxy_configured=proxy_configured,
    )
    runnable_attempts = [attempt for attempt in attempts if attempt.get("runnable")]
    if not attempts:
        return {
            "status": "not_configured",
            "ready": False,
            "url": url,
            "browser_render_runtime": browser_runtime,
            "playwright_render_runtime": playwright_runtime,
            "proxy_configured": proxy_configured,
            "proxy_count": len(proxy_urls),
            "smoke_command": SMOKE_COMMAND,
            "remediation": (
                "執行 live render/proxy 檢查前，請先設定 COMPANY_FILING_BROWSER_RENDER_PROVIDER/URL、"
                "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED=true，或 COMPANY_FILING_PROXY_URLS。"
            ),
        }
    if not runnable_attempts:
        return {
            "status": "unavailable",
            "ready": False,
            "url": url,
            "browser_render_runtime": browser_runtime,
            "playwright_render_runtime": playwright_runtime,
            "proxy_configured": proxy_configured,
            "proxy_count": len(proxy_urls),
            "attempts": attempts,
            "smoke_command": SMOKE_COMMAND,
            "remediation": "已設定文件後援，但 runtime 無法連線或尚未安裝。",
        }

    selected_fetcher = fetcher or CompanyFilingFetcher()
    results = []
    min_chars = max(1, int(min_text_chars))
    for attempt in runnable_attempts:
        result = await run_render_smoke_attempt(
            selected_fetcher,
            url=url,
            attempt=attempt,
            min_text_chars=min_chars,
        )
        results.append(result)
        if result.get("ready"):
            return render_smoke_report(
                status="ready",
                ready=True,
                url=url,
                browser_runtime=browser_runtime,
                playwright_runtime=playwright_runtime,
                proxy_configured=proxy_configured,
                proxy_count=len(proxy_urls),
                attempts=results,
                remediation=None,
            )
    status = "failed" if any(result.get("error") for result in results) else "degraded"
    remediation = (
        "已設定的文件後援有執行，但沒有回傳足夠可解析文字。"
        if status == "degraded"
        else "已設定的文件後援執行失敗；請檢查嘗試錯誤與 provider logs。"
    )
    return render_smoke_report(
        status=status,
        ready=False,
        url=url,
        browser_runtime=browser_runtime,
        playwright_runtime=playwright_runtime,
        proxy_configured=proxy_configured,
        proxy_count=len(proxy_urls),
        attempts=results,
        remediation=remediation,
    )


def render_runtime_snapshot(browser_name: str | None) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    return (
        company_filing_browser_render_status(),
        company_filing_playwright_browser_status(browser_name),
        company_filing_proxy_urls(),
    )


def render_smoke_attempt_plan(
    *,
    browser_runtime: dict[str, Any],
    playwright_runtime: dict[str, Any],
    browser_render_enabled: bool,
    playwright_render_enabled: bool,
    proxy_configured: bool,
) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    if browser_render_enabled or browser_runtime.get("url_configured"):
        attempts.append(
            {
                "kind": "browser_render",
                "provider": browser_runtime.get("provider") or company_filing_browser_render_provider(),
                "runnable": bool(browser_runtime.get("runtime_available")),
                "fallback_reason": browser_runtime.get("fallback_reason"),
            }
        )
    if playwright_render_enabled:
        attempts.append(
            {
                "kind": "playwright_render",
                "provider": "playwright",
                "browser": playwright_runtime.get("browser"),
                "runnable": bool(playwright_runtime.get("browser_available")),
                "fallback_reason": playwright_runtime.get("fallback_reason"),
            }
        )
    if proxy_configured:
        attempts.append(
            {
                "kind": "proxy_fetch",
                "provider": "proxy",
                "runnable": True,
                "fallback_reason": None,
            }
        )
    return attempts


async def run_render_smoke_attempt(
    fetcher: CompanyFilingFetcher,
    *,
    url: str,
    attempt: dict[str, Any],
    min_text_chars: int,
) -> dict[str, Any]:
    kind = str(attempt.get("kind") or "")
    try:
        if kind == "browser_render":
            document = await fetcher._fetch_browser_rendered_url_as_document(url)
        elif kind == "playwright_render":
            document = await fetcher._fetch_playwright_rendered_url_as_document(url)
        elif kind == "proxy_fetch":
            document = await fetcher._fetch_url_as_document(url)
        else:
            raise ValueError(f"unsupported render smoke attempt kind: {kind}")
    except Exception as exc:
        return {
            **attempt,
            "ready": False,
            "error": company_filing_error(url, exc, stage=kind or "render_smoke"),
        }
    sample = document_sample(document)
    ready = int(sample.get("text_length") or 0) >= max(1, int(min_text_chars))
    return {
        **attempt,
        "ready": ready,
        "document": sample,
        "min_text_chars": max(1, int(min_text_chars)),
        "fallback_reason": None if ready else "rendered_text_too_short",
    }


def render_smoke_report(
    *,
    status: str,
    ready: bool,
    url: str,
    browser_runtime: dict[str, Any],
    playwright_runtime: dict[str, Any],
    proxy_configured: bool,
    proxy_count: int,
    attempts: list[dict[str, Any]],
    remediation: str | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "ready": ready,
        "url": url,
        "browser_render_runtime": browser_runtime,
        "playwright_render_runtime": playwright_runtime,
        "proxy_configured": proxy_configured,
        "proxy_count": proxy_count,
        "attempts": attempts,
        "smoke_command": SMOKE_COMMAND,
        "remediation": remediation,
    }


def document_sample(document: Any) -> dict[str, Any]:
    source = getattr(document, "source", None)
    published_at = getattr(source, "published_at", None)
    return {
        "id": getattr(document, "id", None),
        "title": getattr(document, "title", None),
        "publisher": getattr(source, "publisher", None),
        "published_at": published_at.isoformat() if published_at else None,
        "url": getattr(source, "url", None),
        "text_length": len(str(getattr(document, "text", "") or "")),
    }


def company_filing_render_provider_contract_report(
    *,
    target_url: str = DEFAULT_SMOKE_URL,
) -> dict[str, Any]:
    report = company_filing_browser_render_provider_contract_status(
        target_url=target_url,
    )
    return {
        **report,
        "smoke_command": report.get("smoke_cli") or PROVIDER_CONTRACT_SMOKE_COMMAND,
    }


def local_browser_render_defaults_smoke_command(*, url: str, prefer_unlocker: bool) -> str:
    return (
        ".venv/bin/python scripts/company_filing_render_smoke.py "
        "--local-browser-render-defaults "
        + ("--prefer-unlocker " if prefer_unlocker else "")
        + f"--url {url} --json"
    )


def format_company_filing_render_smoke(report: dict[str, Any]) -> str:
    if report.get("providers"):
        return format_company_filing_render_provider_contract(report)
    lines = [
        f"公司文件渲染後援檢查: {report['status']}",
        f"- 就緒: {_yes_no(report.get('ready'))}",
        f"- URL: {report.get('url')}",
        f"- 代理數: {report.get('proxy_count', 0)}",
    ]
    browser_runtime = report.get("browser_render_runtime") or {}
    playwright_runtime = report.get("playwright_render_runtime") or {}
    lines.append(
        f"- 瀏覽器渲染: {browser_runtime.get('provider')} / "
        f"{browser_runtime.get('fallback_reason') or 'ready'}"
    )
    lines.append(
        f"- Playwright: {playwright_runtime.get('browser')} / "
        f"{playwright_runtime.get('fallback_reason') or 'ready'}"
    )
    for attempt in report.get("attempts") or []:
        marker = "OK" if attempt.get("ready") else "WARN"
        lines.append(f"- [{marker}] {attempt.get('kind')}: {attempt.get('provider')}")
        if attempt.get("error"):
            lines.append(f"  錯誤: {attempt['error'].get('category')} - {attempt['error'].get('error')}")
    if report.get("remediation"):
        lines.append(f"- 修復建議: {report['remediation']}")
    if report.get("smoke_command"):
        lines.append(f"- 指令: {report['smoke_command']}")
    return "\n".join(lines)


def format_company_filing_render_provider_contract(report: dict[str, Any]) -> str:
    lines = [
        f"公司文件渲染提供者格式檢查: {report['status']}",
        f"- 就緒: {_yes_no(report.get('ready'))}",
        f"- 提供者數: {report.get('provider_count', 0)}",
    ]
    for row in report.get("providers") or []:
        marker = "OK" if row.get("ready") else "WARN"
        lines.append(f"- [{marker}] {row.get('provider')}: {row.get('method') or '-'}")
        if row.get("error"):
            lines.append(f"  錯誤: {row['error']}")
    if report.get("remediation"):
        lines.append(f"- 修復建議: {report['remediation']}")
    if report.get("smoke_command"):
        lines.append(f"- 指令: {report['smoke_command']}")
    return "\n".join(lines)


def _yes_no(value: object) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    return str(value if value is not None else "-")


def smoke_exit_code(report: dict[str, Any], *, strict: bool = False) -> int:
    if report.get("ready"):
        return 0
    if strict:
        return 1
    return 0 if report.get("status") == "not_configured" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="檢查公司文件瀏覽器/代理渲染後援是否可用。"
    )
    parser.add_argument("--url", default=DEFAULT_SMOKE_URL, help="要渲染或抓取的公開 URL。")
    parser.add_argument(
        "--min-text-chars",
        type=int,
        default=20,
        help="判定就緒所需的最少可解析文字長度。",
    )
    parser.add_argument(
        "--provider-contract",
        action="store_true",
        help="不連網檢查渲染/解鎖提供者的請求與回應格式。",
    )
    parser.add_argument(
        "--local-browser-render-defaults",
        action="store_true",
        help=(
            "只在這次檢查套用本機 Browserless/FlareSolverr 渲染預設值，"
            "不寫入 .env。"
        ),
    )
    parser.add_argument(
        "--prefer-unlocker",
        action="store_true",
        help="搭配 --local-browser-render-defaults 時優先使用本機 FlareSolverr。",
    )
    parser.add_argument("--strict", action="store_true", help="未就緒時回傳非 0 結束碼。")
    parser.add_argument("--json", action="store_true", help="輸出 JSON，方便工具讀取。")
    args = parser.parse_args(argv)

    local_defaults = (
        apply_local_browser_render_defaults(prefer_unlocker=bool(args.prefer_unlocker))
        if args.local_browser_render_defaults
        else {}
    )
    if args.provider_contract:
        report = company_filing_render_provider_contract_report(target_url=args.url)
    else:
        report = asyncio.run(
            company_filing_render_smoke_report(
                url=args.url,
                min_text_chars=args.min_text_chars,
            )
        )
    if args.local_browser_render_defaults:
        report["smoke_command"] = local_browser_render_defaults_smoke_command(
            url=args.url,
            prefer_unlocker=bool(args.prefer_unlocker),
        )
        report["local_browser_render_defaults"] = {
            "applied_env_keys": sorted(local_defaults),
            "prefer_unlocker": bool(args.prefer_unlocker),
            "note": "預設值只套用在本次檢查程序；不會修改 .env。",
        }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_company_filing_render_smoke(report))
    return smoke_exit_code(report, strict=bool(args.strict))


if __name__ == "__main__":
    raise SystemExit(main())
