from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from importlib.util import find_spec
import re
from typing import Any

from app.core.config import Settings, get_settings
from app.services.llm_client import LLMClient


VISUAL_RAG_PROVENANCE_PREFIX = "[Visual RAG 解析資訊]"
SUPPORTED_VISUAL_RAG_MODES = {"fallback", "augment"}
SUPPORTED_VISUAL_RAG_AUGMENT_POLICIES = {"always", "risk_only"}
VISUAL_RAG_TABLE_RISK_MIN_SCORE = 3
VISUAL_RAG_MISSING_RENDERER_MESSAGE = (
    "Visual RAG PDF 轉圖需要安裝 PyMuPDF；請安裝 pip install -e \".[visual]\" 後再重試。"
)
VISUAL_RAG_DISABLED_MESSAGE = "Visual RAG 尚未啟用；請設定 COMPANY_FILING_VISUAL_RAG_ENABLED=true。"
VISUAL_RAG_UNSUPPORTED_MODE_MESSAGE = "Visual RAG 模式不支援；請使用 fallback 或 augment。"
VISUAL_RAG_UNSUPPORTED_AUGMENT_POLICY_MESSAGE = (
    "Visual RAG augment policy 不支援；請使用 risk_only 或 always。"
)
VISUAL_RAG_UNSUPPORTED_MODEL_MESSAGE = (
    "Visual RAG 需要支援圖片輸入的文字 LLM；請使用 Gemini/GPT/Claude vision-capable model。"
)
VISUAL_RAG_MISSING_KEY_MESSAGE = "Visual RAG vision LLM API key 或本地 gateway 尚未配置。"
VISUAL_RAG_EMPTY_PDF_MESSAGE = "Visual RAG 無法從 PDF 產生頁面圖片。"
VISUAL_RAG_TABLE_RISK_SIGNALS = (
    "table_extraction_limit_reached",
    "wide_table_rows",
    "dense_numeric_financial_lines",
    "financial_numbers_without_table_structure",
    "many_table_blocks",
    "short_table_text",
)
_FINANCIAL_TABLE_TERMS = (
    "營收",
    "收入",
    "毛利",
    "毛利率",
    "營業利益",
    "稅後",
    "eps",
    "資產",
    "負債",
    "權益",
    "現金流",
    "資本支出",
    "存貨",
    "應收",
)
_NUMERIC_TOKEN_RE = re.compile(
    r"(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?%?|\(\d+(?:\.\d+)?\))"
)


@dataclass(frozen=True)
class VisualRAGTextRiskAssessment:
    score: int
    level: str
    reason: str
    signals: tuple[str, ...]
    should_augment: bool
    text_char_count: int
    table_block_count: int
    pipe_table_row_count: int
    wide_table_row_count: int
    dense_numeric_financial_line_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "level": self.level,
            "reason": self.reason,
            "signals": list(self.signals),
            "should_augment": self.should_augment,
            "text_char_count": self.text_char_count,
            "table_block_count": self.table_block_count,
            "pipe_table_row_count": self.pipe_table_row_count,
            "wide_table_row_count": self.wide_table_row_count,
            "dense_numeric_financial_line_count": self.dense_numeric_financial_line_count,
        }


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
    augment_policy = normalized_visual_rag_augment_policy(
        settings.company_filing_visual_rag_augment_policy
    )
    augment_policy_supported = augment_policy in SUPPORTED_VISUAL_RAG_AUGMENT_POLICIES
    renderer_dependency_available = _module_available("fitz")
    model = visual_rag_model(settings)
    model_supported = _is_visual_rag_model_candidate(model)
    provider = str(settings.llm_provider or "gemini_http").strip().lower().replace("-", "_")
    vision_key_configured = _vision_model_key_configured(model, settings)
    runtime_available = bool(
        enabled
        and mode_supported
        and augment_policy_supported
        and model_supported
        and renderer_dependency_available
        and vision_key_configured
    )
    fallback_reason = None
    if not enabled:
        fallback_reason = "visual_rag_disabled"
    elif not mode_supported:
        fallback_reason = "unsupported_visual_rag_mode"
    elif not augment_policy_supported:
        fallback_reason = "unsupported_visual_rag_augment_policy"
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
        "augment_policy": augment_policy,
        "augment_policy_supported": augment_policy_supported,
        "supported_augment_policies": sorted(SUPPORTED_VISUAL_RAG_AUGMENT_POLICIES),
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
            "fallback mode runs on parser failure and can add VLM context for high-risk "
            "financial table layouts when the runtime is ready; augment mode follows the "
            "configured augment_policy."
        ),
        "routing_policy": {
            "fallback_high_risk_table_augmentation": True,
            "augment_policy": augment_policy,
            "table_risk_min_score": VISUAL_RAG_TABLE_RISK_MIN_SCORE,
            "table_risk_signals": list(VISUAL_RAG_TABLE_RISK_SIGNALS),
        },
        "captured_outputs": [
            "page_image_count",
            "vision_model",
            "structured_table_text",
            "table_risk_score",
            "routing_reason",
            "observability",
        ],
    }


def normalized_visual_rag_mode(mode: str) -> str:
    normalized = str(mode or "fallback").strip().lower().replace("-", "_")
    return normalized or "fallback"


def normalized_visual_rag_augment_policy(policy: str) -> str:
    normalized = str(policy or "risk_only").strip().lower().replace("-", "_")
    return normalized or "risk_only"


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
    if not status["augment_policy_supported"]:
        raise ValueError(VISUAL_RAG_UNSUPPORTED_AUGMENT_POLICY_MESSAGE)
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
    if not visual_rag_enabled(settings):
        return text
    mode = normalized_visual_rag_mode(settings.company_filing_visual_rag_mode)
    if mode not in SUPPORTED_VISUAL_RAG_MODES:
        return text
    assessment = assess_pdf_text_visual_rag_risk(text)
    augment_policy = normalized_visual_rag_augment_policy(
        settings.company_filing_visual_rag_augment_policy
    )
    should_run = False
    if mode == "augment":
        should_run = augment_policy == "always" or assessment.should_augment
    elif mode == "fallback":
        status = visual_rag_status(settings)
        should_run = bool(status["runtime_available"] and assessment.should_augment)
    if not should_run:
        return text
    reason = _visual_rag_pdf_text_risk_reason(
        assessment,
        default_reason="text_parser_succeeded_visual_table_augmentation",
    )
    try:
        visual_text = extract_visual_pdf_text(
            content,
            reason=reason,
            settings=settings,
        )
    except Exception as exc:
        return "\n\n".join(
            [
                text,
                (
                    f"{VISUAL_RAG_PROVENANCE_PREFIX} status=skipped; "
                    f"reason={exc}; routing_reason={reason}; "
                    f"risk_score={assessment.score}"
                ),
            ]
        )
    return "\n\n".join([text, visual_text])


def assess_pdf_text_visual_rag_risk(text: str) -> VisualRAGTextRiskAssessment:
    raw_text = str(text or "")
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    table_block_count = sum(1 for line in lines if line.startswith("[PDF 表格抽取"))
    pipe_rows = [line for line in lines if "|" in line and not line.startswith("[")]
    wide_pipe_rows = [
        line
        for line in pipe_rows
        if len([cell for cell in line.split("|") if cell.strip()]) >= 5
    ]
    dense_numeric_financial_lines = [
        line
        for line in lines
        if _line_has_financial_term(line) and len(_NUMERIC_TOKEN_RE.findall(line)) >= 3
    ]

    score = 0
    signals: list[str] = []
    if "[PDF 表格抽取限制]" in raw_text or "表格已截斷" in raw_text:
        score += 4
        signals.append("table_extraction_limit_reached")
    if len(wide_pipe_rows) >= 3:
        score += 3
        signals.append("wide_table_rows")
    elif wide_pipe_rows:
        score += 1
    if len(dense_numeric_financial_lines) >= 3:
        score += 2
        signals.append("dense_numeric_financial_lines")
    if not pipe_rows and len(dense_numeric_financial_lines) >= 3:
        score += 2
        signals.append("financial_numbers_without_table_structure")
    if table_block_count >= 6:
        score += 1
        signals.append("many_table_blocks")
    if len(raw_text.strip()) < 1200 and table_block_count and dense_numeric_financial_lines:
        score += 1
        signals.append("short_table_text")

    should_augment = score >= VISUAL_RAG_TABLE_RISK_MIN_SCORE
    level = "high" if score >= 5 else "medium" if should_augment else "low"
    reason = (
        "complex_table_layout_detected"
        if should_augment
        else "text_parser_output_low_visual_rag_risk"
    )
    return VisualRAGTextRiskAssessment(
        score=score,
        level=level,
        reason=reason,
        signals=tuple(dict.fromkeys(signals)),
        should_augment=should_augment,
        text_char_count=len(raw_text.strip()),
        table_block_count=table_block_count,
        pipe_table_row_count=len(pipe_rows),
        wide_table_row_count=len(wide_pipe_rows),
        dense_numeric_financial_line_count=len(dense_numeric_financial_lines),
    )


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


def _line_has_financial_term(line: str) -> bool:
    lowered = line.casefold()
    return any(term in lowered for term in _FINANCIAL_TABLE_TERMS)


def _visual_rag_pdf_text_risk_reason(
    assessment: VisualRAGTextRiskAssessment,
    *,
    default_reason: str,
) -> str:
    if not assessment.should_augment:
        return default_reason
    signals = ",".join(assessment.signals) or "unknown"
    return (
        f"{assessment.reason}; level={assessment.level}; "
        f"score={assessment.score}; signals={signals}"
    )


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False
