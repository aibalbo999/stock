from __future__ import annotations

import struct
import zlib

from app.services.frontend_smoke import (
    DEFAULT_API_ENDPOINTS,
    check_api_runtime_identity,
    check_http_target,
    check_streamlit_page_import_contract,
    png_has_nonblank_pixels,
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


def test_png_has_nonblank_pixels_detects_blank_and_nonblank_png() -> None:
    assert png_has_nonblank_pixels(_png(width=2, height=1, pixels=[(255, 255, 255), (255, 255, 255)])) is False
    assert png_has_nonblank_pixels(_png(width=2, height=1, pixels=[(255, 255, 255), (0, 0, 0)])) is True


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

    report = run_frontend_smoke(
        skip_browser=True,
        api_endpoints=("/services/status", "/llm/quota"),
        check_runtime_identity=False,
    )

    assert report["status"] == "passed"
    assert report["skipped_count"] == 1
    assert [check["label"] for check in report["checks"]] == [
        "streamlit_http",
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

    report = run_frontend_smoke(skip_browser=True)

    assert DEFAULT_API_ENDPOINTS == (
        "/services/status",
        "/services/external-deployment/env-check",
    )
    assert [check["label"] for check in report["checks"]] == [
        "streamlit_http",
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


def test_check_api_runtime_identity_fails_when_runtime_commit_missing() -> None:
    result = check_api_runtime_identity(
        "http://localhost:8000",
        expected_commit="commit-main-test",
        opener=lambda *_args, **_kwargs: FakeResponse(b'{"status":"ok"}'),
    )

    assert result["status"] == "failed"
    assert result["reason"] == "api_runtime_commit_unavailable"


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
