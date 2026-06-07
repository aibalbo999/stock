from __future__ import annotations

from types import SimpleNamespace

from app.core.config import Settings
from app.services.llm_client import LLMResult
from app.services.visual_rag import (
    VISUAL_RAG_PROVENANCE_PREFIX,
    VISUAL_RAG_UNSUPPORTED_MODEL_MESSAGE,
    VisualPageImage,
    build_visual_rag_prompt,
    extract_visual_pdf_text,
    render_pdf_page_images,
    visual_rag_status,
)


def test_visual_rag_status_reports_disabled_when_config_disabled() -> None:
    status = visual_rag_status(Settings(_env_file=None, company_filing_visual_rag_enabled=False))

    assert status["enabled"] is False
    assert status["mode"] == "fallback"
    assert status["runtime_available"] is False
    assert status["fallback_reason"] == "visual_rag_disabled"
    assert status["renderer"] == "pymupdf"


def test_visual_rag_status_requires_supported_mode_and_vision_text_model(monkeypatch) -> None:
    monkeypatch.setattr("app.services.visual_rag._module_available", lambda name: True)
    unsupported_mode = visual_rag_status(
        Settings(
            _env_file=None,
            company_filing_visual_rag_enabled=True,
            company_filing_visual_rag_mode="always",
            company_filing_visual_rag_model="gemini-3.5-flash",
            google_api_key="key",
        )
    )

    assert unsupported_mode["mode"] == "always"
    assert unsupported_mode["mode_supported"] is False
    assert unsupported_mode["model_supported"] is True
    assert unsupported_mode["runtime_available"] is False
    assert unsupported_mode["fallback_reason"] == "unsupported_visual_rag_mode"

    unsupported_model = visual_rag_status(
        Settings(
            _env_file=None,
            company_filing_visual_rag_enabled=True,
            company_filing_visual_rag_model="imagen-4-ultra-generate",
            google_api_key="key",
        )
    )

    assert unsupported_model["mode_supported"] is True
    assert unsupported_model["model_supported"] is False
    assert unsupported_model["vision_model_key_configured"] is True
    assert unsupported_model["runtime_available"] is False
    assert unsupported_model["fallback_reason"] == "unsupported_visual_rag_model"


def test_render_pdf_page_images_uses_pymupdf(monkeypatch) -> None:
    captured = {}

    class FakePixmap:
        def tobytes(self, fmt: str) -> bytes:
            captured["format"] = fmt
            return b"png-bytes"

    class FakePage:
        def get_pixmap(self, *, matrix, alpha: bool):
            captured["matrix"] = matrix
            captured["alpha"] = alpha
            return FakePixmap()

    class FakeDocument:
        def __len__(self) -> int:
            return 3

        def load_page(self, page_index: int):
            captured.setdefault("pages", []).append(page_index)
            return FakePage()

        def close(self) -> None:
            captured["closed"] = True

    fake_fitz = SimpleNamespace(
        Matrix=lambda x, y: ("matrix", x, y),
        open=lambda **_kwargs: FakeDocument(),
    )
    monkeypatch.setattr("app.services.visual_rag.import_module", lambda name: fake_fitz)

    images = render_pdf_page_images(b"%PDF fake", max_pages=2, dpi=144)

    assert [image.page_number for image in images] == [1, 2]
    assert images[0].mime_type == "image/png"
    assert images[0].data == b"png-bytes"
    assert captured["matrix"] == ("matrix", 2.0, 2.0)
    assert captured["pages"] == [0, 1]
    assert captured["alpha"] is False
    assert captured["closed"] is True


def test_extract_visual_pdf_text_adds_provenance(monkeypatch) -> None:
    settings = Settings(
        company_filing_visual_rag_enabled=True,
        company_filing_visual_rag_model="gemini-vision-test",
        google_api_key="key",
    )

    class FakeVisionClient:
        def generate_vision_with_metadata(self, prompt, *, images, model=None):
            assert "台灣上市櫃公司財報" in prompt
            assert images == [
                {
                    "page_number": 1,
                    "mime_type": "image/png",
                    "data": b"page",
                }
            ]
            assert model == "gemini-vision-test"
            return LLMResult(
                text="營收 | 毛利率\n100 | 42%",
                model=model,
                provider="gemini_http",
                attempts=({"provider": "gemini_http", "outcome": "success"},),
                observability={"latency_ms": 12.34, "total_token_estimate": 55},
            )

    monkeypatch.setattr("app.services.visual_rag._module_available", lambda name: True)
    monkeypatch.setattr(
        "app.services.visual_rag.render_pdf_page_images",
        lambda *_args, **_kwargs: [VisualPageImage(1, "image/png", b"page")],
    )

    text = extract_visual_pdf_text(
        b"%PDF fake",
        reason="PDF 公司文件沒有可抽取文字",
        llm_client=FakeVisionClient(),
        settings=settings,
    )

    assert text.startswith(VISUAL_RAG_PROVENANCE_PREFIX)
    assert "mode=fallback" in text
    assert "model=gemini-vision-test" in text
    assert "latency_ms=12.34" in text
    assert "營收 | 毛利率" in text


def test_extract_visual_pdf_text_rejects_unsupported_model_before_render(monkeypatch) -> None:
    settings = Settings(
        company_filing_visual_rag_enabled=True,
        company_filing_visual_rag_model="gemma-4-31b-it",
        google_api_key="key",
    )

    monkeypatch.setattr("app.services.visual_rag._module_available", lambda name: True)
    monkeypatch.setattr(
        "app.services.visual_rag.render_pdf_page_images",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("render should not run")),
    )

    try:
        extract_visual_pdf_text(b"%PDF fake", settings=settings)
    except ValueError as exc:
        assert str(exc) == VISUAL_RAG_UNSUPPORTED_MODEL_MESSAGE
    else:
        raise AssertionError("unsupported Visual RAG model should fail before rendering")


def test_build_visual_rag_prompt_preserves_tables_and_no_fabrication() -> None:
    prompt = build_visual_rag_prompt(page_count=2, reason="掃描型 PDF")

    assert "欄位 | 欄位" in prompt
    assert "不要補寫圖片中沒有的數字" in prompt
    assert "頁面數：2" in prompt
    assert "觸發原因：掃描型 PDF" in prompt
