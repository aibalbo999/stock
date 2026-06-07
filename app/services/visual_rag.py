from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from importlib.util import find_spec
from typing import Any

from app.core.config import Settings, get_settings
from app.services.llm_client import LLMClient


VISUAL_RAG_PROVENANCE_PREFIX = "[Visual RAG 解析資訊]"
SUPPORTED_VISUAL_RAG_MODES = {"fallback", "augment"}
VISUAL_RAG_MISSING_RENDERER_MESSAGE = (
    "Visual RAG PDF 轉圖需要安裝 PyMuPDF；請安裝 pip install -e \".[visual]\" 後再重試。"
)
VISUAL_RAG_DISABLED_MESSAGE = "Visual RAG 尚未啟用；請設定 COMPANY_FILING_VISUAL_RAG_ENABLED=true。"
VISUAL_RAG_UNSUPPORTED_MODE_MESSAGE = "Visual RAG 模式不支援；請使用 fallback 或 augment。"
VISUAL_RAG_UNSUPPORTED_MODEL_MESSAGE = (
    "Visual RAG 需要支援圖片輸入的文字 LLM；請使用 Gemini/GPT/Claude vision-capable model。"
)
VISUAL_RAG_MISSING_KEY_MESSAGE = "Visual RAG vision LLM API key 或本地 gateway 尚未配置。"
VISUAL_RAG_EMPTY_PDF_MESSAGE = "Visual RAG 無法從 PDF 產生頁面圖片。"


@dataclass(frozen=True)
class VisualPageImage:
    page_number: int
    mime_type: str
    data: bytes

    def as_llm_payload(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "mime_type": self.mime_type,
            "data": self.data,
        }


def visual_rag_status(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    enabled = bool(settings.company_filing_visual_rag_enabled)
    mode = normalized_visual_rag_mode(settings.company_filing_visual_rag_mode)
    mode_supported = mode in SUPPORTED_VISUAL_RAG_MODES
    renderer_dependency_available = _module_available("fitz")
    model = visual_rag_model(settings)
    model_supported = _is_visual_rag_model_candidate(model)
    provider = str(settings.llm_provider or "gemini_http").strip().lower().replace("-", "_")
    vision_key_configured = _vision_model_key_configured(model, settings)
    runtime_available = bool(
        enabled
        and mode_supported
        and model_supported
        and renderer_dependency_available
        and vision_key_configured
    )
    fallback_reason = None
    if not enabled:
        fallback_reason = "visual_rag_disabled"
    elif not mode_supported:
        fallback_reason = "unsupported_visual_rag_mode"
    elif not model_supported:
        fallback_reason = "unsupported_visual_rag_model"
    elif not renderer_dependency_available:
        fallback_reason = "missing_dependency:pymupdf"
    elif not vision_key_configured:
        fallback_reason = "missing_vision_llm_key_or_gateway"

    return {
        "enabled": enabled,
        "mode": mode,
        "mode_supported": mode_supported,
        "supported_modes": sorted(SUPPORTED_VISUAL_RAG_MODES),
        "renderer": "pymupdf",
        "renderer_dependency": "fitz",
        "renderer_dependency_available": renderer_dependency_available,
        "provider": provider,
        "model": model,
        "model_supported": model_supported,
        "vision_model_key_configured": vision_key_configured,
        "max_pages": max(1, int(settings.company_filing_visual_rag_max_pages)),
        "dpi": max(72, int(settings.company_filing_visual_rag_dpi)),
        "timeout_seconds": max(1.0, float(settings.company_filing_visual_rag_timeout_seconds)),
        "runtime_available": runtime_available,
        "fallback_reason": fallback_reason,
        "trigger_policy": (
            "fallback mode runs only when text/table PDF parsing fails; "
            "augment mode appends VLM extraction after text/table parsing succeeds."
        ),
        "captured_outputs": [
            "page_image_count",
            "vision_model",
            "structured_table_text",
            "observability",
        ],
    }


def normalized_visual_rag_mode(mode: str) -> str:
    normalized = str(mode or "fallback").strip().lower().replace("-", "_")
    return normalized or "fallback"


def visual_rag_model(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    configured_model = str(settings.company_filing_visual_rag_model or "").strip()
    return configured_model or str(settings.primary_llm_model)


def visual_rag_enabled(settings: Settings | None = None) -> bool:
    return bool((settings or get_settings()).company_filing_visual_rag_enabled)


def visual_rag_fallback_enabled(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return visual_rag_enabled(settings) and normalized_visual_rag_mode(
        settings.company_filing_visual_rag_mode
    ) == "fallback"


def visual_rag_augment_enabled(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return visual_rag_enabled(settings) and normalized_visual_rag_mode(
        settings.company_filing_visual_rag_mode
    ) == "augment"


def extract_visual_pdf_text(
    content: bytes,
    *,
    reason: str = "",
    llm_client: LLMClient | None = None,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    status = visual_rag_status(settings)
    if not status["enabled"]:
        raise ValueError(VISUAL_RAG_DISABLED_MESSAGE)
    if not status["mode_supported"]:
        raise ValueError(VISUAL_RAG_UNSUPPORTED_MODE_MESSAGE)
    if not status["model_supported"]:
        raise ValueError(VISUAL_RAG_UNSUPPORTED_MODEL_MESSAGE)
    if not status["renderer_dependency_available"]:
        raise ValueError(VISUAL_RAG_MISSING_RENDERER_MESSAGE)
    if not status["vision_model_key_configured"]:
        raise ValueError(VISUAL_RAG_MISSING_KEY_MESSAGE)

    images = render_pdf_page_images(
        content,
        max_pages=int(status["max_pages"]),
        dpi=int(status["dpi"]),
    )
    if not images:
        raise ValueError(VISUAL_RAG_EMPTY_PDF_MESSAGE)

    prompt = build_visual_rag_prompt(page_count=len(images), reason=reason)
    client = llm_client or LLMClient()
    result = client.generate_vision_with_metadata(
        prompt,
        images=[image.as_llm_payload() for image in images],
        model=str(status["model"]),
    )
    if result.fallback or not result.text.strip():
        raise ValueError(f"Visual RAG LLM extraction failed: {result.text}")
    return with_visual_rag_provenance(
        result.text,
        status=status,
        page_count=len(images),
        reason=reason,
        observability=result.observability,
    )


def maybe_augment_pdf_text_with_visual_rag(
    content: bytes,
    text: str,
    *,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    if not visual_rag_augment_enabled(settings):
        return text
    try:
        visual_text = extract_visual_pdf_text(
            content,
            reason="text_parser_succeeded_visual_table_augmentation",
            settings=settings,
        )
    except Exception as exc:
        return "\n\n".join(
            [
                text,
                f"{VISUAL_RAG_PROVENANCE_PREFIX} status=skipped; reason={exc}",
            ]
        )
    return "\n\n".join([text, visual_text])


def render_pdf_page_images(
    content: bytes,
    *,
    max_pages: int,
    dpi: int,
) -> list[VisualPageImage]:
    try:
        fitz = import_module("fitz")
    except ImportError as exc:
        raise ValueError(VISUAL_RAG_MISSING_RENDERER_MESSAGE) from exc

    document = fitz.open(stream=content, filetype="pdf")
    try:
        page_limit = min(len(document), max(1, int(max_pages)))
        scale = max(72, int(dpi)) / 72
        matrix = fitz.Matrix(scale, scale)
        images: list[VisualPageImage] = []
        for page_index in range(page_limit):
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            images.append(
                VisualPageImage(
                    page_number=page_index + 1,
                    mime_type="image/png",
                    data=pixmap.tobytes("png"),
                )
            )
        return images
    finally:
        document.close()


def build_visual_rag_prompt(*, page_count: int, reason: str = "") -> str:
    reason_line = f"\n觸發原因：{reason}" if reason else ""
    return (
        "你正在協助台灣上市櫃公司財報/法說會 PDF 的 Visual RAG 萃取。"
        "請閱讀附上的頁面圖片，只根據圖片內容輸出可檢索文字。"
        "請使用繁體中文，保留公司名稱、股票代號、期間、金額單位、表格欄列、"
        "管理層展望、風險、資本支出與財務指標。"
        "遇到表格時用「欄位 | 欄位」格式逐列保留；看不清楚的欄位標示為「無法判讀」。"
        "不要補寫圖片中沒有的數字或結論。"
        f"\n頁面數：{page_count}"
        f"{reason_line}"
    )


def with_visual_rag_provenance(
    text: str,
    *,
    status: dict,
    page_count: int,
    reason: str,
    observability: dict[str, object] | None = None,
) -> str:
    observability = observability or {}
    marker = (
        f"{VISUAL_RAG_PROVENANCE_PREFIX} mode={status.get('mode')}; "
        f"renderer={status.get('renderer')}; pages={page_count}; "
        f"model={status.get('model')}; reason={reason or 'not_specified'}"
    )
    latency = observability.get("latency_ms")
    token_estimate = observability.get("total_token_estimate")
    if latency is not None:
        marker += f"; latency_ms={round(float(latency), 2)}"
    if token_estimate is not None:
        marker += f"; total_token_estimate={token_estimate}"
    return f"{marker}\n{text.strip()}"


def _vision_model_key_configured(model: str, settings: Settings) -> bool:
    normalized = str(model or "").strip().lower()
    if not normalized:
        return False
    if normalized.startswith(("gemini", "gemma", "google/")):
        return len(settings.gemini_api_keys) > 0
    if normalized.startswith(("openai/", "gpt-")):
        return bool(settings.openai_api_key)
    if normalized.startswith(("anthropic/", "claude")):
        return bool(settings.anthropic_api_key)
    if normalized.startswith(("ollama/", "lm_studio/", "local/")):
        return True
    return bool(
        len(settings.gemini_api_keys) > 0
        or settings.openai_api_key
        or settings.anthropic_api_key
    )


def _is_visual_rag_model_candidate(model: str) -> bool:
    normalized = str(model or "").strip().lower()
    if normalized.startswith(("models/", "gemini/", "google/")):
        normalized = normalized.split("/", 1)[1]
    if normalized.startswith("gemma"):
        return False
    if not normalized.startswith(("gemini", "gpt-", "openai/", "claude", "anthropic/")):
        return False
    return not any(
        blocked in normalized
        for blocked in ("embedding", "imagen", "image", "live", "tts", "audio")
    )


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False
