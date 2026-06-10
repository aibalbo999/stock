from __future__ import annotations

import importlib
import json
import zlib
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from app.services.api_runtime_identity_check import check_api_runtime_identity
from app.services.runtime_identity import runtime_identity_status


DEFAULT_API_ENDPOINTS = (
    "/services/status",
    "/services/external-deployment/env-check",
)
DEFAULT_VISUAL_TEXT_FRAGMENTS = ("下一步建議",)
DEFAULT_REQUIRED_TEXT_MAX_TOP_PX = 560
DEFAULT_REQUIRED_TEXT_SCOPE_SELECTOR = ".operator-decision-card"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
STREAMLIT_DASHBOARD_REQUIRED_EXPORTS = (
    "configure_page",
    "render_analysis_workspace",
    "render_report_center",
    "render_data_enrichment",
    "render_system_settings",
)
STREAMLIT_PAGE_CONTRACTS = (
    ("pages/01_分析工作區.py", "render_analysis_workspace"),
    ("pages/02_報告中心.py", "render_report_center"),
    ("pages/03_資料補強.py", "render_data_enrichment"),
    ("pages/04_系統設定.py", "render_system_settings"),
)


def run_frontend_smoke(
    *,
    streamlit_url: str = "http://127.0.0.1:8501",
    api_url: str = "http://127.0.0.1:8000",
    api_endpoints: tuple[str, ...] = DEFAULT_API_ENDPOINTS,
    screenshot_path: str | Path | None = "artifacts/frontend_smoke/streamlit.png",
    skip_browser: bool = False,
    check_runtime_identity: bool = True,
    expected_api_commit: str | None = None,
    required_text_fragments: tuple[str, ...] = DEFAULT_VISUAL_TEXT_FRAGMENTS,
    required_text_max_top_px: float | None = DEFAULT_REQUIRED_TEXT_MAX_TOP_PX,
    required_text_scope_selector: str | None = DEFAULT_REQUIRED_TEXT_SCOPE_SELECTOR,
    timeout_seconds: float = 10.0,
) -> dict:
    checks = [
        check_http_target(
            streamlit_url,
            expected_fragments=("streamlit", "<!doctype", "<html"),
            timeout_seconds=timeout_seconds,
            label="streamlit_http",
            require_any_fragment=True,
        )
    ]
    for endpoint in api_endpoints:
        checks.append(
            check_http_target(
                _join_url(api_url, endpoint),
                expected_fragments=("{",),
                timeout_seconds=timeout_seconds,
                label=f"api_http:{endpoint}",
                require_any_fragment=False,
            )
        )
    if check_runtime_identity:
        checks.append(
            check_api_runtime_identity(
                api_url,
                expected_commit=expected_api_commit,
                timeout_seconds=timeout_seconds,
            )
        )
    checks.append(check_streamlit_page_import_contract())
    if skip_browser:
        checks.append(
            {
                "label": "streamlit_playwright",
                "status": "skipped",
                "reason": "skip_browser_requested",
            }
        )
    else:
        checks.append(
            run_playwright_visual_smoke(
                streamlit_url,
                screenshot_path=screenshot_path,
                check_frontend_runtime_identity=check_runtime_identity,
                expected_frontend_commit=expected_api_commit,
                required_text_fragments=required_text_fragments,
                required_text_max_top_px=required_text_max_top_px,
                required_text_scope_selector=required_text_scope_selector,
                timeout_seconds=timeout_seconds,
            )
        )
    failed = [check for check in checks if check.get("status") == "failed"]
    return {
        "status": "failed" if failed else "passed",
        "checks": checks,
        "failed_count": len(failed),
        "skipped_count": sum(1 for check in checks if check.get("status") == "skipped"),
    }


def check_http_target(
    url: str,
    *,
    expected_fragments: tuple[str, ...] = (),
    timeout_seconds: float = 10.0,
    label: str = "http",
    require_any_fragment: bool = True,
    opener: Callable[..., Any] | None = None,
) -> dict:
    opener = opener or urlopen
    url = _iri_to_uri(url)
    request = Request(url, headers={"User-Agent": "stock-ai-frontend-smoke/1.0"})
    try:
        with opener(request, timeout=timeout_seconds) as response:
            status_code = int(getattr(response, "status", getattr(response, "code", 0)) or 0)
            body = response.read(250_000).decode("utf-8", errors="ignore")
    except (OSError, URLError, TimeoutError) as exc:
        return {
            "label": label,
            "url": url,
            "status": "failed",
            "error": str(exc) or exc.__class__.__name__,
        }
    body_lower = body.casefold()
    fragments = [fragment.casefold() for fragment in expected_fragments if fragment]
    matched_fragments = [fragment for fragment in fragments if fragment in body_lower]
    fragment_ok = True
    if fragments:
        fragment_ok = bool(matched_fragments) if require_any_fragment else all(
            fragment in body_lower for fragment in fragments
        )
    passed = 200 <= status_code < 500 and fragment_ok
    return {
        "label": label,
        "url": url,
        "status": "passed" if passed else "failed",
        "status_code": status_code,
        "matched_fragments": matched_fragments,
        "body_bytes_sampled": len(body.encode("utf-8")),
    }


def check_streamlit_page_import_contract(
    *,
    root_path: str | Path = ".",
    module_name: str = "app.ui.streamlit_dashboard",
    module_loader: Callable[[str], Any] | None = None,
) -> dict:
    module_loader = module_loader or importlib.import_module
    try:
        dashboard_module = module_loader(module_name)
    except Exception as exc:
        return {
            "label": "streamlit_page_import_contract",
            "status": "failed",
            "module": module_name,
            "error": str(exc) or exc.__class__.__name__,
        }

    exports = {
        export_name: callable(getattr(dashboard_module, export_name, None))
        for export_name in STREAMLIT_DASHBOARD_REQUIRED_EXPORTS
    }
    pages = [
        _check_streamlit_page_contract(Path(root_path), relative_path, render_name)
        for relative_path, render_name in STREAMLIT_PAGE_CONTRACTS
    ]
    missing_exports = [export_name for export_name, ok in exports.items() if not ok]
    failed_pages = [page["path"] for page in pages if page["status"] == "failed"]
    passed = not missing_exports and not failed_pages
    return {
        "label": "streamlit_page_import_contract",
        "status": "passed" if passed else "failed",
        "module": module_name,
        "exports": exports,
        "missing_exports": missing_exports,
        "pages": pages,
        "failed_pages": failed_pages,
    }


def _check_streamlit_page_contract(root_path: Path, relative_path: str, render_name: str) -> dict:
    page_path = root_path / relative_path
    result = {
        "path": relative_path,
        "render": render_name,
        "exists": page_path.exists(),
        "imports_facade": False,
        "calls_configure_page": False,
        "calls_render": False,
    }
    if not page_path.exists():
        return {**result, "status": "failed"}
    try:
        source = page_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {
            **result,
            "status": "failed",
            "error": str(exc) or exc.__class__.__name__,
        }
    result["imports_facade"] = (
        f"from app.ui.streamlit_dashboard import configure_page, {render_name}" in source
    )
    result["calls_configure_page"] = "configure_page(" in source
    result["calls_render"] = f"{render_name}()" in source
    return {
        **result,
        "status": "passed"
        if result["imports_facade"] and result["calls_configure_page"] and result["calls_render"]
        else "failed",
    }


def run_playwright_visual_smoke(
    url: str,
    *,
    screenshot_path: str | Path | None = "artifacts/frontend_smoke/streamlit.png",
    check_frontend_runtime_identity: bool = True,
    expected_frontend_commit: str | None = None,
    required_text_fragments: tuple[str, ...] = DEFAULT_VISUAL_TEXT_FRAGMENTS,
    required_text_max_top_px: float | None = DEFAULT_REQUIRED_TEXT_MAX_TOP_PX,
    required_text_scope_selector: str | None = DEFAULT_REQUIRED_TEXT_SCOPE_SELECTOR,
    timeout_seconds: float = 10.0,
) -> dict:
    url = _iri_to_uri(url)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return {
            "label": "streamlit_playwright",
            "status": "skipped",
            "reason": "playwright_unavailable",
            "error": str(exc) or exc.__class__.__name__,
        }
    target = Path(screenshot_path) if screenshot_path else None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=int(timeout_seconds * 1000),
            )
            page.wait_for_selector("body", state="attached", timeout=int(timeout_seconds * 1000))
            try:
                page.wait_for_selector(
                    '[data-testid="stApp"], .stApp',
                    state="attached",
                    timeout=int(timeout_seconds * 1000),
                )
            except Exception:
                pass
            page.wait_for_function(
                "() => document.body && (document.body.innerText || '').trim().length >= 80",
                timeout=int(timeout_seconds * 1000),
            )
            frontend_marker = page.evaluate(
                """() => {
                    const marker = document.querySelector("[data-stock-frontend-runtime='true']");
                    if (!marker) {
                        return {};
                    }
                    return {
                        git_commit: marker.dataset.gitCommit || "",
                        git_commit_short: marker.dataset.gitCommitShort || "",
                        git_dirty: marker.dataset.gitDirty || "",
                        source: marker.dataset.source || "",
                    };
                }"""
            )
            frontend_identity = (
                frontend_runtime_identity_result(
                    frontend_marker,
                    expected_commit=expected_frontend_commit,
                )
                if check_frontend_runtime_identity
                else {
                    "status": "skipped",
                    "reason": "runtime_identity_check_disabled",
                }
            )
            if required_text_fragments and frontend_identity.get("status") != "failed":
                page.wait_for_function(
                    """({fragments, scopeSelector}) => {
                        const root = scopeSelector
                            ? document.querySelector(scopeSelector)
                            : document.body;
                        const text = root
                            ? (root.innerText || root.textContent || "")
                            : "";
                        return fragments.every(fragment => text.includes(fragment));
                    }""",
                    arg={
                        "fragments": list(required_text_fragments),
                        "scopeSelector": required_text_scope_selector,
                    },
                    timeout=int(timeout_seconds * 1000),
                )
            if target:
                target.parent.mkdir(parents=True, exist_ok=True)
            screenshot = page.screenshot(path=str(target) if target else None, full_page=True)
            title = page.title()
            body_text = page.evaluate(
                "() => document.body ? (document.body.innerText || document.body.textContent || '') : ''"
            )
            required_text_measurements = _required_text_measurements(
                page,
                required_text_fragments,
                scope_selector=required_text_scope_selector,
            )
            browser.close()
    except Exception as exc:
        return {
            "label": "streamlit_playwright",
            "status": "failed",
            "url": url,
            "error": str(exc) or exc.__class__.__name__,
        }
    nonblank = png_has_nonblank_pixels(screenshot)
    missing_required_text = missing_required_text_fragments(body_text, required_text_fragments)
    text_layout_failures = required_text_layout_failures(
        required_text_measurements,
        max_top_px=required_text_max_top_px,
    )
    passed = bool(
        nonblank
        and len(screenshot) > 1000
        and len(body_text.strip()) >= 80
        and not missing_required_text
        and not text_layout_failures
        and frontend_identity.get("status") in {"passed", "skipped"}
    )
    return {
        "label": "streamlit_playwright",
        "status": "passed" if passed else "failed",
        "url": url,
        "http_status": getattr(response, "status", None) if response else None,
        "title": title,
        "body_text_length": len(body_text.strip()),
        "screenshot_path": str(target) if target else None,
        "screenshot_bytes": len(screenshot),
        "screenshot_nonblank": nonblank,
        "missing_required_text": missing_required_text,
        "required_text_max_top_px": required_text_max_top_px,
        "required_text_scope_selector": required_text_scope_selector,
        "required_text_measurements": required_text_measurements,
        "required_text_layout_failures": text_layout_failures,
        "frontend_runtime_identity": frontend_identity,
    }


def frontend_runtime_identity_result(
    marker: dict,
    *,
    expected_commit: str | None = None,
) -> dict:
    local_identity = runtime_identity_status()
    expected = str(
        expected_commit if expected_commit is not None else local_identity.get("git_commit") or ""
    )
    result = {
        "expected_commit": expected,
        "expected_commit_short": expected[:12] if expected else "",
    }
    actual = str(marker.get("git_commit") or "")
    if not expected:
        return {
            **result,
            "status": "skipped",
            "reason": "local_git_commit_unavailable",
            "actual_commit": actual,
            "actual_commit_short": actual[:12] if actual else "",
        }
    if not marker:
        return {
            **result,
            "status": "failed",
            "reason": "streamlit_runtime_identity_marker_missing",
            "actual_commit": "",
        }
    if not actual:
        return {
            **result,
            "status": "failed",
            "reason": "streamlit_runtime_commit_unavailable",
            "actual_commit": "",
        }
    matched = _commits_match(expected, actual)
    return {
        **result,
        "status": "passed" if matched else "failed",
        "actual_commit": actual,
        "actual_commit_short": actual[:12],
        "actual_source": marker.get("source"),
        "actual_dirty": _marker_bool(marker.get("git_dirty")),
        "reason": None if matched else "streamlit_runtime_commit_mismatch",
    }


def _marker_bool(value: object) -> bool | None:
    text = str(value or "").strip().casefold()
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def _commits_match(expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    if len(expected) >= 7 and len(actual) >= 7:
        return expected.startswith(actual) or actual.startswith(expected)
    return False


def required_text_layout_failures(
    measurements: list[dict[str, Any]],
    *,
    max_top_px: float | None,
) -> list[str]:
    if max_top_px is None:
        return []
    failures = []
    max_label = _px_label(max_top_px)
    for measurement in measurements:
        fragment = str(measurement.get("fragment") or "-")
        if not measurement.get("found"):
            failures.append(f"{fragment} missing")
            continue
        top = measurement.get("top")
        if not isinstance(top, int | float):
            failures.append(f"{fragment} missing")
            continue
        if top > max_top_px:
            failures.append(
                f"{fragment} below {max_label}px (top={_px_label(float(top))}px)"
            )
    return failures


def missing_required_text_fragments(
    body_text: str, required_text_fragments: tuple[str, ...]
) -> list[str]:
    return [fragment for fragment in required_text_fragments if fragment not in body_text]


def _required_text_measurements(
    page: Any,
    fragments: tuple[str, ...],
    *,
    scope_selector: str | None = DEFAULT_REQUIRED_TEXT_SCOPE_SELECTOR,
) -> list[dict[str, Any]]:
    if not fragments:
        return []
    return list(
        page.evaluate(
            """({fragments, scopeSelector}) => fragments.map(fragment => {
                const roots = scopeSelector
                    ? Array.from(document.querySelectorAll(scopeSelector))
                    : [document.body].filter(Boolean);
                const elements = roots.flatMap(root => [
                    root,
                    ...Array.from(root.querySelectorAll("*")),
                ]);
                const candidates = elements
                    .map(element => {
                        const text = element.innerText || element.textContent || "";
                        if (!text.includes(fragment)) {
                            return null;
                        }
                        const rect = element.getBoundingClientRect();
                        const style = window.getComputedStyle(element);
                        if (
                            rect.width <= 0 ||
                            rect.height <= 0 ||
                            style.display === "none" ||
                            style.visibility === "hidden"
                        ) {
                            return null;
                        }
                        const childHasFragment = Array.from(element.children).some(child => {
                            const childText = child.innerText || child.textContent || "";
                            return childText.includes(fragment);
                        });
                        return {
                            fragment,
                            found: true,
                            top: Math.round(rect.top),
                            height: Math.round(rect.height),
                            textLength: text.trim().length,
                            childHasFragment,
                        };
                    })
                    .filter(Boolean)
                    .sort((left, right) => {
                        if (left.childHasFragment !== right.childHasFragment) {
                            return left.childHasFragment ? 1 : -1;
                        }
                        if (left.top !== right.top) {
                            return left.top - right.top;
                        }
                        return left.textLength - right.textLength;
                    });
                return candidates[0] || {fragment, found: false, top: null};
            })""",
            {"fragments": list(fragments), "scopeSelector": scope_selector},
        )
    )


def _px_label(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def png_has_nonblank_pixels(data: bytes) -> bool:
    parsed = _parse_png_rgba_rows(data)
    if parsed is None:
        return len(set(data[: min(len(data), 2048)])) > 1
    width, _height, channels, rows = parsed
    first_pixel: bytes | None = None
    for row in rows:
        for offset in range(0, width * channels, channels):
            pixel = row[offset : offset + channels]
            if first_pixel is None:
                first_pixel = pixel
                continue
            if pixel != first_pixel:
                return True
    return False


def format_frontend_smoke_report(report: dict) -> str:
    lines = [
        f"Frontend smoke: {report['status']}",
        (
            f"Checks: {len(report.get('checks') or [])}, "
            f"failed={report.get('failed_count', 0)}, "
            f"skipped={report.get('skipped_count', 0)}"
        ),
    ]
    for check in report.get("checks") or []:
        lines.append(
            f"- [{str(check.get('status', 'unknown')).upper()}] "
            f"{check.get('label')}: {check.get('url') or check.get('reason') or ''}"
        )
        if check.get("error"):
            lines.append(f"  error: {check['error']}")
        for missing_text in check.get("missing_required_text") or []:
            lines.append(f"  missing text: {missing_text}")
        for layout_failure in check.get("required_text_layout_failures") or []:
            lines.append(f"  layout: {layout_failure}")
        if check.get("reason"):
            lines.append(f"  reason: {check['reason']}")
        if check.get("expected_commit_short") or check.get("actual_commit_short"):
            lines.append(
                "  commit: "
                f"expected={check.get('expected_commit_short') or '-'} "
                f"actual={check.get('actual_commit_short') or '-'}"
            )
        frontend_identity = check.get("frontend_runtime_identity")
        if isinstance(frontend_identity, dict):
            if frontend_identity.get("expected_commit_short") or frontend_identity.get(
                "actual_commit_short"
            ):
                lines.append(
                    "  frontend commit: "
                    f"expected={frontend_identity.get('expected_commit_short') or '-'} "
                    f"actual={frontend_identity.get('actual_commit_short') or '-'}"
                )
            if frontend_identity.get("reason"):
                lines.append(f"  frontend reason: {frontend_identity['reason']}")
    return "\n".join(lines)


def _parse_png_rgba_rows(data: bytes) -> tuple[int, int, int, list[bytes]] | None:
    if not data.startswith(PNG_SIGNATURE):
        return None
    offset = len(PNG_SIGNATURE)
    width = height = channels = 0
    idat_chunks: list[bytes] = []
    while offset + 8 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            width = int.from_bytes(chunk_data[0:4], "big")
            height = int.from_bytes(chunk_data[4:8], "big")
            bit_depth = chunk_data[8]
            color_type = chunk_data[9]
            if bit_depth != 8 or color_type not in {0, 2, 6}:
                return None
            channels = {0: 1, 2: 3, 6: 4}[color_type]
        elif chunk_type == b"IDAT":
            idat_chunks.append(chunk_data)
        elif chunk_type == b"IEND":
            break
    if not width or not height or not channels or not idat_chunks:
        return None
    try:
        raw = zlib.decompress(b"".join(idat_chunks))
    except zlib.error:
        return None
    return width, height, channels, _png_unfilter_rows(raw, width=width, height=height, channels=channels)


def _png_unfilter_rows(raw: bytes, *, width: int, height: int, channels: int) -> list[bytes]:
    row_length = width * channels
    rows: list[bytes] = []
    previous = bytes(row_length)
    offset = 0
    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        row = bytearray(raw[offset : offset + row_length])
        offset += row_length
        for index in range(row_length):
            left = row[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                row[index] = (row[index] + left) & 0xFF
            elif filter_type == 2:
                row[index] = (row[index] + up) & 0xFF
            elif filter_type == 3:
                row[index] = (row[index] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                row[index] = (row[index] + _paeth_predictor(left, up, upper_left)) & 0xFF
        previous = bytes(row)
        rows.append(previous)
    return rows


def _paeth_predictor(left: int, up: int, upper_left: int) -> int:
    prediction = left + up - upper_left
    distance_left = abs(prediction - left)
    distance_up = abs(prediction - up)
    distance_upper_left = abs(prediction - upper_left)
    if distance_left <= distance_up and distance_left <= distance_upper_left:
        return left
    if distance_up <= distance_upper_left:
        return up
    return upper_left


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


def to_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
