from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.rag.timeouts import RagOperationTimeout


DISABLED_RERANKER_PROVIDERS = {"", "none", "disabled", "off"}
AUTO_RERANKER_PROVIDERS = {"auto", "model_auto", "auto_model"}
KEYWORD_RERANKER_PROVIDERS = {"keyword", "hybrid"}
CROSS_ENCODER_RERANKER_PROVIDERS = {
    "sentence_transformers",
    "sentence_transformer",
    "cross_encoder",
    "bge",
}
COHERE_RERANKER_PROVIDERS = {"cohere", "cohere_rerank", "cohere_reranker"}
LLM_RERANKER_PROVIDERS = {"llm", "llm_rerank", "llm_reranker"}
MODEL_NOT_PROVIDED = object()


@dataclass(frozen=True)
class RerankerStatusBuilder:
    configured_provider: str
    normalized_provider: str
    model_name: str
    cohere_model_name: str
    cohere_api_key: str
    llm_reranker_enabled: bool
    cross_encoder_factory_configured: bool
    cohere_client_factory_configured: bool
    llm_client_factory_configured: bool
    module_available: Callable[[str], bool]
    load_cross_encoder_model: Callable[[], Any]
    load_cohere_client: Callable[[], Any]

    def base_status(self, provider: str) -> dict:
        return {
            "provider": provider,
            "normalized_provider": provider,
            "model": self.model_name,
            "available": False,
            "execution_mode": "input_order",
            "quality_tier": "none",
            "is_model_reranker": False,
            "model_reranker_ready": False,
            "keyword_fallback": False,
            "dependency": None,
            "dependency_available": None,
            "api_key_required": False,
            "api_key_configured": None,
            "model_checked": False,
            "model_available": None,
            "model_reranker_gap": None,
            "fallback_reason": None,
        }

    def status_for_provider(
        self,
        provider: str,
        *,
        model_checked: bool,
        model: Any = MODEL_NOT_PROVIDED,
        prediction_error: str | None = None,
    ) -> dict:
        base = self.base_status(provider)
        if provider in DISABLED_RERANKER_PROVIDERS:
            return {
                **base,
                "execution_mode": "input_order",
                "model_reranker_gap": "reranker_disabled",
                "fallback_reason": "reranker_disabled",
            }
        if provider in AUTO_RERANKER_PROVIDERS:
            return self.auto_status(model_checked=model_checked)
        if provider in KEYWORD_RERANKER_PROVIDERS:
            return {
                **base,
                "available": True,
                "execution_mode": "keyword",
                "quality_tier": "lexical_fallback",
                "keyword_fallback": True,
                "model_checked": False,
                "model_reranker_gap": "keyword_provider_selected",
                "fallback_reason": None,
            }
        if provider not in CROSS_ENCODER_RERANKER_PROVIDERS:
            if provider in COHERE_RERANKER_PROVIDERS:
                return self.cohere_status(
                    base,
                    model_checked=model_checked,
                    model=model,
                    prediction_error=prediction_error,
                )
            if provider in LLM_RERANKER_PROVIDERS:
                return self.llm_status(
                    base,
                    model_checked=model_checked,
                    model=model,
                    prediction_error=prediction_error,
                )
            return {
                **base,
                "execution_mode": "input_order",
                "model_reranker_gap": f"unsupported_provider:{provider}",
                "fallback_reason": f"unsupported_provider:{provider}",
            }

        return self.cross_encoder_status(
            base,
            model_checked=model_checked,
            model=model,
            prediction_error=prediction_error,
        )

    def cross_encoder_status(
        self,
        base: dict,
        *,
        model_checked: bool,
        model: Any = MODEL_NOT_PROVIDED,
        prediction_error: str | None = None,
    ) -> dict:
        dependency = "sentence_transformers"
        dependency_available = (
            True if self.cross_encoder_factory_configured else self.module_available(dependency)
        )
        fallback_reason = None
        model_available = None
        if not self.model_name:
            fallback_reason = "missing_model"
            model_available = False if model_checked else None
        elif not dependency_available:
            fallback_reason = f"missing_dependency:{dependency}"
            model_available = False if model_checked else None
        elif model_checked:
            if model is MODEL_NOT_PROVIDED:
                try:
                    model = self.load_cross_encoder_model()
                except RagOperationTimeout:
                    model = None
                    fallback_reason = "timeout:cross_encoder_model_load"
            model_available = model is not None
            if model is None and fallback_reason is None:
                fallback_reason = "model_unavailable"
        if prediction_error:
            fallback_reason = f"prediction_failed:{prediction_error}"
            model_available = model is not None

        available = fallback_reason is None
        return {
            **base,
            "available": available,
            "execution_mode": "cross_encoder" if available else "input_order_fallback",
            "quality_tier": "model_reranker" if available else "model_reranker_unavailable",
            "is_model_reranker": True,
            "model_reranker_ready": available,
            "dependency": dependency,
            "dependency_available": dependency_available,
            "model_checked": model_checked,
            "model_available": model_available,
            "model_reranker_gap": None if available else fallback_reason,
            "fallback_reason": fallback_reason,
        }

    def cohere_status(
        self,
        base: dict,
        *,
        model_checked: bool,
        model: Any = MODEL_NOT_PROVIDED,
        prediction_error: str | None = None,
    ) -> dict:
        dependency = "cohere"
        dependency_available = True if self.cohere_client_factory_configured else self.module_available(dependency)
        api_key_configured = bool(self.cohere_api_key)
        fallback_reason = None
        model_available = None
        if not self.cohere_model_name:
            fallback_reason = "missing_model"
            model_available = False if model_checked else None
        elif not api_key_configured:
            fallback_reason = "missing_api_key"
            model_available = False if model_checked else None
        elif not dependency_available:
            fallback_reason = f"missing_dependency:{dependency}"
            model_available = False if model_checked else None
        elif model_checked:
            if model is MODEL_NOT_PROVIDED:
                model = self.load_cohere_client()
            model_available = model is not None
            if model is None:
                fallback_reason = "client_unavailable"
        if prediction_error:
            fallback_reason = f"prediction_failed:{prediction_error}"
            model_available = model is not None

        available = fallback_reason is None
        return {
            **base,
            "model": self.cohere_model_name,
            "available": available,
            "execution_mode": "cohere_api" if available else "input_order_fallback",
            "quality_tier": "api_model_reranker" if available else "model_reranker_unavailable",
            "is_model_reranker": True,
            "model_reranker_ready": available,
            "dependency": dependency,
            "dependency_available": dependency_available,
            "api_key_required": True,
            "api_key_configured": api_key_configured,
            "model_checked": model_checked,
            "model_available": model_available,
            "model_reranker_gap": None if available else fallback_reason,
            "fallback_reason": fallback_reason,
        }

    def auto_status(self, *, model_checked: bool) -> dict:
        cross_status = self.status_for_provider("bge", model_checked=model_checked)
        if cross_status.get("model_reranker_ready"):
            return self.auto_status_from_result(cross_status, candidate_statuses=[cross_status])

        cohere_status = self.status_for_provider("cohere", model_checked=model_checked)
        if cohere_status.get("model_reranker_ready"):
            return self.auto_status_from_result(
                cohere_status,
                candidate_statuses=[cross_status, cohere_status],
            )

        llm_status = self.status_for_provider("llm", model_checked=model_checked)
        if llm_status.get("model_reranker_ready"):
            return self.auto_status_from_result(
                llm_status,
                candidate_statuses=[cross_status, cohere_status, llm_status],
            )

        keyword_status = self.status_for_provider("keyword", model_checked=False)
        return self.auto_status_from_result(
            keyword_status,
            candidate_statuses=[cross_status, cohere_status, llm_status, keyword_status],
        )

    def auto_status_from_result(self, result_status: dict, *, candidate_statuses: list[dict]) -> dict:
        selected = str(result_status.get("normalized_provider") or result_status.get("provider") or "")
        model_gap = result_status.get("model_reranker_gap")
        if selected in KEYWORD_RERANKER_PROVIDERS:
            model_gap = "auto_model_reranker_unavailable:" + ";".join(
                str(status.get("model_reranker_gap") or status.get("fallback_reason") or "not_ready")
                for status in candidate_statuses
                if status.get("is_model_reranker")
            )
        return {
            **result_status,
            "provider": self.configured_provider,
            "normalized_provider": self.normalized_provider,
            "configured_provider": self.configured_provider,
            "resolved_provider": selected,
            "auto_candidates": [auto_candidate_summary(status) for status in candidate_statuses],
            "model_reranker_gap": model_gap,
        }

    def llm_status(
        self,
        base: dict,
        *,
        model_checked: bool,
        model: Any = MODEL_NOT_PROVIDED,
        prediction_error: str | None = None,
    ) -> dict:
        settings = get_settings()
        provider = str(getattr(settings, "llm_provider", "gemini_http") or "gemini_http").lower().replace("-", "_")
        dependency = "litellm" if provider == "litellm" else "google.genai" if provider == "google_genai" else None
        dependency_available = (
            None
            if dependency is None
            else True
            if self.llm_client_factory_configured
            else self.module_available(dependency)
        )
        api_key_configured = bool(
            self.llm_client_factory_configured
            or getattr(settings, "gemini_api_keys", [])
            or getattr(settings, "openai_api_key", None)
            or getattr(settings, "anthropic_api_key", None)
        )
        fallback_reason = None
        model_available = None
        if not self.llm_reranker_enabled:
            fallback_reason = "llm_reranker_disabled"
            model_available = False if model_checked else None
        elif dependency_available is False and not getattr(settings, "gemini_api_keys", []):
            fallback_reason = f"missing_dependency:{dependency}"
            model_available = False if model_checked else None
        elif not api_key_configured:
            fallback_reason = "missing_api_key"
            model_available = False if model_checked else None
        elif model_checked:
            if model is MODEL_NOT_PROVIDED:
                model = True
            model_available = model is not None
            if model is None:
                fallback_reason = "client_unavailable"
        if prediction_error:
            fallback_reason = f"prediction_failed:{prediction_error}"
            model_available = model is not None

        available = fallback_reason is None
        return {
            **base,
            "model": str(getattr(settings, "primary_llm_model", "") or "llm"),
            "available": available,
            "execution_mode": "llm_rerank" if available else "input_order_fallback",
            "quality_tier": "llm_model_reranker" if available else "model_reranker_unavailable",
            "is_model_reranker": True,
            "model_reranker_ready": available,
            "dependency": dependency,
            "dependency_available": dependency_available,
            "api_key_required": True,
            "api_key_configured": api_key_configured,
            "model_checked": model_checked,
            "model_available": model_available,
            "model_reranker_gap": None if available else fallback_reason,
            "fallback_reason": fallback_reason,
        }


def auto_candidate_summary(status: dict) -> dict:
    return {
        "provider": status.get("normalized_provider") or status.get("provider"),
        "execution_mode": status.get("execution_mode"),
        "quality_tier": status.get("quality_tier"),
        "model": status.get("model"),
        "model_reranker_ready": status.get("model_reranker_ready"),
        "dependency_available": status.get("dependency_available"),
        "api_key_configured": status.get("api_key_configured"),
        "model_available": status.get("model_available"),
        "fallback_reason": status.get("fallback_reason"),
    }
