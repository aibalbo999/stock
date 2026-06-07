from __future__ import annotations

from types import SimpleNamespace

from app.core.config import Settings
from app.services.llm_client import LLMResult
from app.services.visual_rag import (
    VISUAL_RAG_PROVENANCE_PREFIX,
    VISUAL_RAG_UNSUPPORTED_MODEL_MESSAGE,
    VisualPageImage,
    assess_pdf_text_visual_rag_risk,
    build_visual_rag_prompt,
    extract_visual_pdf_text,
    maybe_augment_pdf_text_with_visual_rag,
    render_pdf_page_images,
    visual_rag_model_chain,
    visual_rag_status,
)


def test_visual_rag_status_reports_disabled_when_config_disabled() -> None:
    status = visual_rag_status(Settings(_env_file=None, company_filing_visual_rag_enabled=False))

    assert status["enabled"] is False
    assert status["mode"] == "fallback"
    assert status["runtime_available"] is False
    assert status["fallback_reason"] == "visual_rag_disabled"
    assert status["renderer"] == "pymupdf"
    assert status["augment_policy"] == "risk_only"
    assert status["routing_policy"]["table_risk_min_score"] == 3


def test_visual_rag_status_requires_supported_mode_policy_and_vision_text_model(
    monkeypatch,
) -> None:
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

    unsupported_policy = visual_rag_status(
        Settings(
            _env_file=None,
            company_filing_visual_rag_enabled=True,
            company_filing_visual_rag_mode="augment",
            company_filing_visual_rag_augment_policy="eager",
            company_filing_visual_rag_model="gemini-3.5-flash",
            google_api_key="key",
        )
    )

    assert unsupported_policy["augment_policy"] == "eager"
    assert unsupported_policy["augment_policy_supported"] is False
    assert unsupported_policy["runtime_available"] is False
    assert unsupported_policy["fallback_reason"] == "unsupported_visual_rag_augment_policy"

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


def test_visual_rag_status_exposes_quota_aware_vision_model_chain(monkeypatch) -> None:
    monkeypatch.setattr("app.services.visual_rag._module_available", lambda name: True)
    settings = Settings(
        _env_file=None,
        company_filing_visual_rag_enabled=True,
        company_filing_visual_rag_model="models/gemini-3.5-flash",
        google_api_key="key",
        llm_fallback_models=(
            "gemini-2.5-flash,imagen-4-ultra-generate,gemma-4-31b-it,"
            "gemini-2.5-flash-lite,gemini-embedding-2,gemini-3-flash-live"
        ),
        local_llm_model="gemma-4-31b-it",
        llm_model_daily_request_budgets=(
            "gemini-3.5-flash=250,gemini-2.5-flash=250,"
            "gemini-2.5-flash-lite=250,gemma-4-31b-it=14400"
        ),
    )

    status = visual_rag_status(settings)
    chain = status["model_chain"]

    assert status["quota_governed"] is True
    assert status["routing_policy"]["quota_aware_model_fallback"] is True
    assert status["routing_policy"]["vision_candidate_count"] == 3
    assert chain == visual_rag_model_chain(settings)
    assert chain["vision_candidate_models"] == [
        "models/gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ]
    assert chain["provider_compatible_vision_candidate_models"] == [
        "models/gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ]
    assert chain["vision_candidates"][0]["model_key"] == "gemini-3.5-flash"
    assert chain["vision_candidates"][0]["request_budget"] == 250
    assert chain["vision_candidates"][0]["key_configured"] is True
    assert status["runtime_model"] == "models/gemini-3.5-flash"
    assert status["runtime_model_selection_reason"] == "preferred_visual_rag_model"
    rejected = {item["model"]: item["rejection_reason"] for item in chain["rejected_candidates"]}
    assert rejected == {
        "imagen-4-ultra-generate": "non_vision_media_embedding_or_live_model",
        "gemma-4-31b-it": "text_only_gemma_fallback",
        "gemini-embedding-2": "non_vision_media_embedding_or_live_model",
        "gemini-3-flash-live": "non_vision_media_embedding_or_live_model",
    }
    assert chain["excluded_non_vision_models"] == list(rejected)


def test_visual_rag_status_selects_litellm_vision_fallback_when_preferred_key_missing(
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.services.visual_rag._module_available", lambda name: True)
    provider_auth = "configured"
    settings = Settings(
        _env_file=None,
        llm_provider="litellm",
        company_filing_visual_rag_enabled=True,
        company_filing_visual_rag_model="models/gemini-3.5-flash",
        llm_fallback_models="openai/gpt-4o-mini,gemma-4-31b-it",
        local_llm_model="",
        openai_api_key=provider_auth,
        google_api_key=None,
    )

    status = visual_rag_status(settings)

    assert status["model"] == "models/gemini-3.5-flash"
    assert status["model_supported"] is True
    assert status["vision_model_key_configured"] is False
    assert status["runtime_available"] is True
    assert status["runtime_model"] == "openai/gpt-4o-mini"
    assert status["runtime_model_key_configured"] is True
    assert status["runtime_model_provider_compatible"] is True
    assert status["runtime_model_selection_reason"] == "fallback_visual_rag_model"
    assert status["fallback_reason"] is None
    assert status["model_chain"]["provider_compatible_vision_candidate_models"] == [
        "models/gemini-3.5-flash",
        "openai/gpt-4o-mini",
    ]


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


def test_extract_visual_pdf_text_uses_selected_runtime_fallback_model(monkeypatch) -> None:
    provider_auth = "configured"
    settings = Settings(
        _env_file=None,
        llm_provider="litellm",
        company_filing_visual_rag_enabled=True,
        company_filing_visual_rag_model="gemini-3.5-flash",
        llm_fallback_models="openai/gpt-4o-mini",
        local_llm_model="",
        openai_api_key=provider_auth,
        google_api_key=None,
    )

    class FakeVisionClient:
        def generate_vision_with_metadata(self, prompt, *, images, model=None):
            assert "台灣上市櫃公司財報" in prompt
            assert model == "openai/gpt-4o-mini"
            return LLMResult(
                text="營收 | 毛利率\n100 | 42%",
                model=model,
                provider="litellm",
                attempts=({"provider": "litellm", "outcome": "success"},),
                observability={"latency_ms": 10.0, "total_token_estimate": 40},
            )

    monkeypatch.setattr("app.services.visual_rag._module_available", lambda name: True)
    monkeypatch.setattr(
        "app.services.visual_rag.render_pdf_page_images",
        lambda *_args, **_kwargs: [VisualPageImage(1, "image/png", b"page")],
    )

    text = extract_visual_pdf_text(
        b"%PDF fake",
        reason="preferred key missing",
        llm_client=FakeVisionClient(),
        settings=settings,
    )

    assert "model=openai/gpt-4o-mini" in text
    assert "preferred_model=gemini-3.5-flash" in text
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


def test_pdf_text_risk_assessment_flags_complex_financial_tables() -> None:
    text = "\n".join(
        [
            "[PDF 解析資訊] parser=pdfplumber; mode=auto; extract_tables=true",
            "[PDF 表格抽取 p.1 #1]",
            "年度 | 營收 | 毛利率 | EPS | 資本支出",
            "2024 | 營收 1,000 | 毛利率 41.2% | EPS 5.1 | 資本支出 300",
            "2025 | 營收 1,250 | 毛利率 42.1% | EPS 5.8 | 資本支出 360",
            "2026 | 營收 1,480 | 毛利率 43.0% | EPS 6.4 | 資本支出 390",
        ]
    )

    assessment = assess_pdf_text_visual_rag_risk(text)

    assert assessment.should_augment is True
    assert assessment.reason == "complex_table_layout_detected"
    assert "wide_table_rows" in assessment.signals
    assert assessment.wide_table_row_count >= 3


def test_pdf_text_risk_assessment_keeps_plain_text_low_risk() -> None:
    assessment = assess_pdf_text_visual_rag_risk("台積電 2026 年報\nAI/HPC 需求與風險因素")

    assert assessment.should_augment is False
    assert assessment.level == "low"
    assert assessment.score < 3


def test_visual_rag_augment_policy_skips_low_risk_text_to_save_quota(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        company_filing_visual_rag_enabled=True,
        company_filing_visual_rag_mode="augment",
        company_filing_visual_rag_augment_policy="risk_only",
        company_filing_visual_rag_model="gemini-vision-test",
        google_api_key="key",
    )

    monkeypatch.setattr(
        "app.services.visual_rag.extract_visual_pdf_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("low-risk text should not call Visual RAG")
        ),
    )

    text = "台積電 2026 年報\nAI/HPC 需求與風險因素"

    assert maybe_augment_pdf_text_with_visual_rag(
        b"%PDF fake",
        text,
        settings=settings,
    ) == text


def test_visual_rag_augment_policy_runs_for_complex_table_layout(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        company_filing_visual_rag_enabled=True,
        company_filing_visual_rag_mode="augment",
        company_filing_visual_rag_augment_policy="risk_only",
        company_filing_visual_rag_model="gemini-vision-test",
        google_api_key="key",
    )
    captured = {}

    def fake_visual_extract(content: bytes, *, reason: str, settings: Settings):
        captured["content"] = content
        captured["reason"] = reason
        captured["settings"] = settings
        return "[Visual RAG 解析資訊] mode=augment\n營收 | 毛利率\n1,250 | 42.1%"

    monkeypatch.setattr("app.services.visual_rag.extract_visual_pdf_text", fake_visual_extract)
    text = "\n".join(
        [
            "[PDF 表格抽取 p.1 #1]",
            "年度 | 營收 | 毛利率 | EPS | 資本支出",
            "2024 | 營收 1,000 | 毛利率 41.2% | EPS 5.1 | 資本支出 300",
            "2025 | 營收 1,250 | 毛利率 42.1% | EPS 5.8 | 資本支出 360",
            "2026 | 營收 1,480 | 毛利率 43.0% | EPS 6.4 | 資本支出 390",
        ]
    )

    result = maybe_augment_pdf_text_with_visual_rag(
        b"%PDF fake",
        text,
        settings=settings,
    )

    assert captured["content"] == b"%PDF fake"
    assert captured["settings"] is settings
    assert "complex_table_layout_detected" in captured["reason"]
    assert "wide_table_rows" in captured["reason"]
    assert "營收 | 毛利率" in result
