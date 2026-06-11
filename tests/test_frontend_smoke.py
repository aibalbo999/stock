from __future__ import annotations

import struct
import zlib

from app.services.frontend_smoke import (
    DEFAULT_API_ENDPOINTS,
    DEFAULT_FORBIDDEN_TEXT_FRAGMENTS,
    DEFAULT_OPERATOR_PRIMARY_ACTION_MOBILE_MAX_TOP_PX,
    DEFAULT_REQUIRED_TEXT_SCOPE_SELECTOR,
    DEFAULT_VISUAL_TEXT_FRAGMENTS,
    check_api_runtime_identity,
    frontend_runtime_identity_result,
    check_http_target,
    check_streamlit_mpa_route_health_fallback,
    check_streamlit_page_import_contract,
    format_frontend_smoke_report,
    missing_required_text_fragments,
    operator_primary_action_layout_failures,
    operator_primary_action_viewport_layout_failures,
    png_has_nonblank_pixels,
    present_forbidden_text_fragments,
    required_text_layout_failures,
    run_frontend_smoke,
)


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, _limit: int) -> bytes:
        return self.body


def test_check_http_target_accepts_expected_fragment() -> None:
    captured = {}

    def opener(_request, timeout):
        assert timeout == 3.0
        captured["url"] = _request.full_url
        return FakeResponse(b"<!doctype html><html>Streamlit app</html>")

    result = check_http_target(
        "http://localhost:8501/查詢?question=上下游衝擊",
        expected_fragments=("streamlit",),
        timeout_seconds=3.0,
        opener=opener,
    )

    assert result["status"] == "passed"
    assert result["status_code"] == 200
    assert result["matched_fragments"] == ["streamlit"]
    assert "%E6%9F%A5%E8%A9%A2" in captured["url"]
    assert "%E4%B8%8A%E4%B8%8B%E6%B8%B8" in captured["url"]


def test_check_http_target_fails_missing_required_fragment() -> None:
    result = check_http_target(
        "http://localhost:8000/services/status",
        expected_fragments=("{",),
        opener=lambda *_args, **_kwargs: FakeResponse(b"not json"),
        require_any_fragment=False,
    )

    assert result["status"] == "failed"


def test_check_streamlit_mpa_route_health_fallback_documents_known_route_noise() -> None:
    captured_urls: list[str] = []

    def opener(request, timeout):
        assert timeout == 10.0
        captured_urls.append(request.full_url)
        if request.full_url.endswith(
            "/%E7%B3%BB%E7%B5%B1%E8%A8%AD%E5%AE%9A/_stcore/health"
        ):
            return FakeResponse(b"Not Found", status=404)
        if request.full_url.endswith("/_stcore/health"):
            return FakeResponse(b"ok", status=200)
        return FakeResponse(b"<!doctype html><html>Streamlit app</html>", status=200)

    result = check_streamlit_mpa_route_health_fallback(
        "http://localhost:8501",
        route_path="/系統設定",
        opener=opener,
    )

    assert result["status"] == "passed"
    assert result["reason"] == "streamlit_mpa_route_health_fallback"
    assert result["root_health_status_code"] == 200
    assert result["route_health_status_code"] == 404
    assert result["route_page_status_code"] == 200
    assert captured_urls == [
        "http://localhost:8501/_stcore/health",
        "http://localhost:8501/%E7%B3%BB%E7%B5%B1%E8%A8%AD%E5%AE%9A/_stcore/health",
        "http://localhost:8501/%E7%B3%BB%E7%B5%B1%E8%A8%AD%E5%AE%9A",
    ]


def test_png_has_nonblank_pixels_detects_blank_and_nonblank_png() -> None:
    assert png_has_nonblank_pixels(_png(width=2, height=1, pixels=[(255, 255, 255), (255, 255, 255)])) is False
    assert png_has_nonblank_pixels(_png(width=2, height=1, pixels=[(255, 255, 255), (0, 0, 0)])) is True


def test_missing_required_text_fragments_reports_absent_operator_markers() -> None:
    assert DEFAULT_VISUAL_TEXT_FRAGMENTS == ("下一步建議",)
    assert DEFAULT_REQUIRED_TEXT_SCOPE_SELECTOR == ".operator-decision-card"
    assert missing_required_text_fragments(
        "今日狀態\n下一步建議\n待處理事件",
        ("下一步建議", "待處理事件"),
    ) == []
    assert missing_required_text_fragments(
        "今日狀態",
        ("下一步建議", "待處理事件"),
    ) == ["下一步建議", "待處理事件"]


def test_present_forbidden_text_fragments_reports_streamlit_and_runtime_warnings() -> None:
    assert "Missing Submit Button" in DEFAULT_FORBIDDEN_TEXT_FRAGMENTS
    assert present_forbidden_text_fragments(
        "建立一次分析\nMissing Submit Button\nTraceback (most recent call last)",
        DEFAULT_FORBIDDEN_TEXT_FRAGMENTS,
    ) == ["Missing Submit Button", "Traceback"]
    assert present_forbidden_text_fragments(
        "建立一次分析\n下一步建議",
        DEFAULT_FORBIDDEN_TEXT_FRAGMENTS,
    ) == []


def test_required_text_layout_failures_flags_missing_and_late_operator_markers() -> None:
    assert required_text_layout_failures(
        [
            {"fragment": "下一步建議", "found": True, "top": 420},
            {"fragment": "待處理事件", "found": True, "top": 720},
            {"fragment": "資料缺口", "found": False, "top": None},
        ],
        max_top_px=560,
    ) == [
        "待處理事件 below 560px (top=720px)",
        "資料缺口 missing",
    ]


def test_operator_primary_action_layout_failures_require_visible_button_before_fold() -> None:
    assert operator_primary_action_layout_failures(
        {
            "marker_found": True,
            "marker_top": 790,
            "button_found": True,
            "button_top": 825,
            "button_text": "查看事件",
        },
        max_button_top_px=900,
    ) == []
    assert operator_primary_action_layout_failures(
        {
            "marker_found": False,
            "button_found": False,
        },
        max_button_top_px=900,
    ) == [
        "primary action marker missing",
        "primary action button missing",
    ]
    assert operator_primary_action_layout_failures(
        {
            "marker_found": True,
            "marker_top": 930,
            "button_found": True,
            "button_top": 960,
            "button_text": "查看事件",
        },
        max_button_top_px=900,
    ) == ["primary action button below 900px (top=960px)"]


def test_operator_primary_action_viewport_layout_failures_names_mobile_failures() -> None:
    assert DEFAULT_OPERATOR_PRIMARY_ACTION_MOBILE_MAX_TOP_PX == 720

    assert operator_primary_action_viewport_layout_failures(
        {
            "desktop": {
                "marker_found": True,
                "button_found": True,
                "button_top": 825,
                "button_text": "查看事件",
            },
            "mobile": {
                "marker_found": True,
                "button_found": True,
                "button_top": 760,
                "button_text": "查看事件",
            },
        },
        max_button_top_px={
            "desktop": 900,
            "mobile": DEFAULT_OPERATOR_PRIMARY_ACTION_MOBILE_MAX_TOP_PX,
        },
    ) == {
        "desktop": [],
        "mobile": ["primary action button below 720px (top=760px)"],
    }


def test_check_streamlit_page_import_contract_accepts_project_pages() -> None:
    result = check_streamlit_page_import_contract()

    assert result["status"] == "passed"
    assert result["missing_exports"] == []
    assert result["failed_pages"] == []
    assert result["exports"]["configure_page"] is True
    assert {page["render"] for page in result["pages"]} == {
        "render_analysis_workspace",
        "render_report_center",
        "render_data_enrichment",
        "render_system_settings",
    }


def test_check_streamlit_page_import_contract_fails_when_pages_are_missing(tmp_path) -> None:
    class FakeDashboard:
        configure_page = staticmethod(lambda *_args, **_kwargs: None)
        render_analysis_workspace = staticmethod(lambda: None)
        render_report_center = staticmethod(lambda: None)
        render_data_enrichment = staticmethod(lambda: None)
        render_system_settings = staticmethod(lambda: None)

    result = check_streamlit_page_import_contract(
        root_path=tmp_path,
        module_loader=lambda _name: FakeDashboard,
    )

    assert result["status"] == "failed"
    assert result["missing_exports"] == []
    assert result["failed_pages"] == [
        "pages/01_分析工作區.py",
        "pages/02_報告中心.py",
        "pages/03_資料補強.py",
        "pages/04_系統設定.py",
    ]


def test_run_frontend_smoke_can_skip_browser_with_fake_http(monkeypatch) -> None:
    def fake_check(url, **kwargs):
        return {
            "label": kwargs["label"],
            "url": url,
            "status": "passed",
            "status_code": 200,
        }

    monkeypatch.setattr("app.services.frontend_smoke.check_http_target", fake_check)
    monkeypatch.setattr(
        "app.services.frontend_smoke.check_streamlit_page_import_contract",
        lambda: {"label": "streamlit_page_import_contract", "status": "passed"},
    )
    monkeypatch.setattr(
        "app.services.frontend_smoke.check_streamlit_mpa_route_health_fallback",
        lambda *_args, **_kwargs: {
            "label": "streamlit_mpa_route_health_fallback",
            "status": "passed",
        },
    )

    report = run_frontend_smoke(
        skip_browser=True,
        api_endpoints=("/services/status", "/llm/quota"),
        check_runtime_identity=False,
    )

    assert report["status"] == "passed"
    assert report["skipped_count"] == 1
    assert [check["label"] for check in report["checks"]] == [
        "streamlit_http",
        "streamlit_mpa_route_health_fallback",
        "api_http:/services/status",
        "api_http:/llm/quota",
        "streamlit_page_import_contract",
        "streamlit_playwright",
    ]


def test_run_frontend_smoke_defaults_include_external_env_check(monkeypatch) -> None:
    def fake_check(url, **kwargs):
        return {
            "label": kwargs["label"],
            "url": url,
            "status": "passed",
            "status_code": 200,
        }

    monkeypatch.setattr("app.services.frontend_smoke.check_http_target", fake_check)
    monkeypatch.setattr(
        "app.services.frontend_smoke.check_streamlit_page_import_contract",
        lambda: {"label": "streamlit_page_import_contract", "status": "passed"},
    )
    monkeypatch.setattr(
        "app.services.frontend_smoke.check_api_runtime_identity",
        lambda *_args, **_kwargs: {"label": "api_runtime_identity", "status": "passed"},
    )
    monkeypatch.setattr(
        "app.services.frontend_smoke.check_streamlit_mpa_route_health_fallback",
        lambda *_args, **_kwargs: {
            "label": "streamlit_mpa_route_health_fallback",
            "status": "passed",
        },
    )

    report = run_frontend_smoke(skip_browser=True)

    assert DEFAULT_API_ENDPOINTS == (
        "/services/status",
        "/services/external-deployment/env-check",
    )
    assert [check["label"] for check in report["checks"]] == [
        "streamlit_http",
        "streamlit_mpa_route_health_fallback",
        "api_http:/services/status",
        "api_http:/services/external-deployment/env-check",
        "api_runtime_identity",
        "streamlit_page_import_contract",
        "streamlit_playwright",
    ]


def test_check_api_runtime_identity_matches_commit_prefix() -> None:
    result = check_api_runtime_identity(
        "http://localhost:8000",
        expected_commit="commit-main-test",
        opener=lambda *_args, **_kwargs: FakeResponse(
            b'{"git_commit":"commit-main-test","source":"git","git_dirty":false}'
        ),
    )

    assert result["status"] == "passed"
    assert result["actual_commit_short"] == "commit-main-"


def test_check_api_runtime_identity_fails_on_commit_mismatch() -> None:
    result = check_api_runtime_identity(
        "http://localhost:8000",
        expected_commit="commit-main-test",
        opener=lambda *_args, **_kwargs: FakeResponse(
            b'{"git_commit":"commit-old-test","source":"git","git_dirty":false}'
        ),
    )

    assert result["status"] == "failed"
    assert result["reason"] == "api_runtime_commit_mismatch"


def test_check_api_runtime_identity_fails_on_dirty_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.api_runtime_identity_check.runtime_identity_status",
        lambda: {"git_commit": "commit-main-test", "git_dirty": True},
    )

    result = check_api_runtime_identity(
        "http://localhost:8000",
        opener=lambda *_args, **_kwargs: FakeResponse(
            b'{"git_commit":"commit-main-test","source":"env","git_dirty":false}'
        ),
    )

    assert result["status"] == "failed"
    assert result["reason"] == "api_runtime_dirty_mismatch"
    assert result["expected_dirty"] is True
    assert result["actual_dirty"] is False


def test_check_api_runtime_identity_fails_when_runtime_commit_missing() -> None:
    result = check_api_runtime_identity(
        "http://localhost:8000",
        expected_commit="commit-main-test",
        opener=lambda *_args, **_kwargs: FakeResponse(b'{"status":"ok"}'),
    )

    assert result["status"] == "failed"
    assert result["reason"] == "api_runtime_commit_unavailable"


def test_frontend_runtime_identity_result_matches_commit_prefix() -> None:
    result = frontend_runtime_identity_result(
        {
            "git_commit": "commit-main-test",
            "source": "git",
            "git_dirty": "false",
        },
        expected_commit="commit-main-test-extra",
    )

    assert result["status"] == "passed"
    assert result["actual_commit_short"] == "commit-main-"
    assert result["actual_dirty"] is False


def test_frontend_runtime_identity_result_fails_on_commit_mismatch() -> None:
    result = frontend_runtime_identity_result(
        {"git_commit": "commit-old-test", "source": "git"},
        expected_commit="commit-main-test",
    )

    assert result["status"] == "failed"
    assert result["reason"] == "streamlit_runtime_commit_mismatch"
    assert result["expected_commit_short"] == "commit-main-"
    assert result["actual_commit_short"] == "commit-old-t"


def test_frontend_runtime_identity_result_fails_on_dirty_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.frontend_smoke.runtime_identity_status",
        lambda: {"git_commit": "commit-main-test", "git_dirty": True},
    )

    result = frontend_runtime_identity_result(
        {
            "git_commit": "commit-main-test",
            "source": "env",
            "git_dirty": "false",
        }
    )

    assert result["status"] == "failed"
    assert result["reason"] == "streamlit_runtime_dirty_mismatch"
    assert result["expected_dirty"] is True
    assert result["actual_dirty"] is False


def test_frontend_runtime_identity_result_fails_when_marker_missing() -> None:
    result = frontend_runtime_identity_result({}, expected_commit="commit-main-test")

    assert result["status"] == "failed"
    assert result["reason"] == "streamlit_runtime_identity_marker_missing"


def test_format_frontend_smoke_report_includes_streamlit_runtime_identity() -> None:
    output = format_frontend_smoke_report(
        {
            "status": "failed",
            "failed_count": 1,
            "skipped_count": 0,
            "checks": [
                {
                    "label": "streamlit_playwright",
                    "status": "failed",
                    "url": "http://127.0.0.1:8501",
                    "frontend_runtime_identity": {
                        "status": "failed",
                        "reason": "streamlit_runtime_commit_mismatch",
                        "expected_commit_short": "commit-main-",
                        "actual_commit_short": "commit-old-t",
                    },
                }
            ],
        }
    )

    assert "frontend commit: expected=commit-main- actual=commit-old-t" in output
    assert "frontend reason: streamlit_runtime_commit_mismatch" in output


def test_format_frontend_smoke_report_includes_streamlit_route_health_fallback() -> None:
    output = format_frontend_smoke_report(
        {
            "status": "passed",
            "failed_count": 0,
            "skipped_count": 0,
            "checks": [
                {
                    "label": "streamlit_mpa_route_health_fallback",
                    "status": "passed",
                    "url": "http://127.0.0.1:8501/%E7%B3%BB%E7%B5%B1%E8%A8%AD%E5%AE%9A",
                    "reason": "streamlit_mpa_route_health_fallback",
                    "root_health_status_code": 200,
                    "route_health_status_code": 404,
                    "route_page_status_code": 200,
                }
            ],
        }
    )

    assert "route health: root=200 route=404 page=200" in output
    assert "reason: streamlit_mpa_route_health_fallback" in output


def test_format_frontend_smoke_report_includes_mobile_operator_layout_failures() -> None:
    output = format_frontend_smoke_report(
        {
            "status": "failed",
            "failed_count": 1,
            "skipped_count": 0,
            "checks": [
                {
                    "label": "streamlit_playwright",
                    "status": "failed",
                    "operator_primary_action_viewport_layout_failures": {
                        "desktop": [],
                        "mobile": ["primary action button below 720px (top=760px)"],
                    },
                }
            ],
        }
    )

    assert "operator action layout (mobile): primary action button below 720px (top=760px)" in output


def test_format_frontend_smoke_report_includes_forbidden_text_failures() -> None:
    output = format_frontend_smoke_report(
        {
            "status": "failed",
            "failed_count": 1,
            "skipped_count": 0,
            "checks": [
                {
                    "label": "streamlit_playwright",
                    "status": "failed",
                    "present_forbidden_text": ["Missing Submit Button"],
                }
            ],
        }
    )

    assert "forbidden text: Missing Submit Button" in output


def _png(*, width: int, height: int, pixels: list[tuple[int, int, int]]) -> bytes:
    raw_rows = []
    for row_index in range(height):
        row_pixels = pixels[row_index * width : (row_index + 1) * width]
        raw_rows.append(b"\x00" + b"".join(bytes(pixel) for pixel in row_pixels))
    raw = zlib.compress(b"".join(raw_rows))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", raw)
        + _chunk(b"IEND", b"")
    )


def _chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return len(payload).to_bytes(4, "big") + chunk_type + payload + checksum.to_bytes(4, "big")
