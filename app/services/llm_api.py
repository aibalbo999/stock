from __future__ import annotations

from collections.abc import Callable
from importlib.util import find_spec
from typing import Any

from app.core.config import get_settings
from app.services.llm_client import LLMClient, summarize_llm_attempts
from app.services.llm_observability import llm_observability_status
from app.services.llm_quota import LLMQuotaGovernanceService
from app.services.llm_usage import list_llm_usage_records
from app.services.persistence import LLMUsageRepository


class LLMApiService:
    def __init__(
        self,
        *,
        settings_provider: Callable[[], Any] = get_settings,
        llm_client_cls: type[LLMClient] = LLMClient,
        session_scope_factory: Callable | None = None,
        llm_usage_repository_cls: type[LLMUsageRepository] = LLMUsageRepository,
        llm_quota_service_cls: type[LLMQuotaGovernanceService] = LLMQuotaGovernanceService,
    ) -> None:
        self.settings_provider = settings_provider
        self.llm_client_cls = llm_client_cls
        self.session_scope_factory = session_scope_factory
        self.llm_usage_repository_cls = llm_usage_repository_cls
        self.llm_quota_service_cls = llm_quota_service_cls

    def status(self) -> dict:
        settings = self.settings_provider()
        provider = str(settings.llm_provider or "").lower().replace("-", "_")
        fallback_models = self._fallback_models(settings)
        local_gateway_configured = any(self._model_provider(model) == "local" for model in fallback_models)
        provider_keys = {
            "gemini": len(settings.gemini_api_keys) > 0,
            "openai": bool(settings.openai_api_key),
            "anthropic": bool(settings.anthropic_api_key),
            "local": local_gateway_configured,
        }
        fallback_readiness = [
            {
                "model": model,
                "provider": self._model_provider(model),
                "key_configured": (
                    bool(provider_keys.get(self._model_provider(model)))
                    if self._model_provider(model) in provider_keys
                    else None
                ),
            }
            for model in fallback_models
        ]
        sdk_dependency = (
            "litellm"
            if provider == "litellm"
            else "google.genai"
            if provider == "google_genai"
            else None
        )
        return {
            "primary_model": settings.primary_llm_model,
            "local_model": settings.local_llm_model,
            "gemini_key_count": len(settings.gemini_api_keys),
            "enabled": self._provider_enabled(provider, provider_keys),
            "provider": settings.llm_provider,
            "sdk_dependency": sdk_dependency,
            "sdk_dependency_available": self._module_available(sdk_dependency) if sdk_dependency else None,
            "fallback_models": fallback_models,
            "fallback_model_readiness": fallback_readiness,
            "fallback_model_ready_count": sum(1 for item in fallback_readiness if item["key_configured"] is True),
            "provider_keys_configured": provider_keys,
            "observability": llm_observability_status(settings),
            "retry_policy": {
                "max_retries_per_key": max(0, int(settings.llm_max_retries_per_key)),
                "model_quota_cooldown_seconds": max(
                    0.0,
                    float(getattr(settings, "llm_model_quota_cooldown_seconds", 0.0)),
                ),
                "base_retry_delay_seconds": max(0.0, float(settings.llm_base_retry_delay_seconds)),
                "max_retry_delay_seconds": max(0.0, float(settings.llm_max_retry_delay_seconds)),
            },
        }

    def healthcheck(self) -> dict:
        result = self.llm_client_cls().healthcheck()
        return {
            "ok": not result.fallback,
            "model": result.model,
            "key_index": result.key_index,
            "provider": result.provider,
            "fallback": result.fallback,
            "message": result.text[:200],
            "attempts": list(result.attempts[-10:]),
            "attempt_summary": summarize_llm_attempts(result.attempts),
            "observability": result.observability,
        }

    def usage_records(self, limit: int = 50) -> list[dict]:
        if self.session_scope_factory is None:
            return []
        return list_llm_usage_records(
            limit=limit,
            session_scope_factory=self.session_scope_factory,
            llm_usage_repository_cls=self.llm_usage_repository_cls,
        )

    def quota_summary(self) -> dict:
        if self.session_scope_factory is None:
            return {}
        return self.llm_quota_service_cls(
            settings_provider=self.settings_provider,
            session_scope_factory=self.session_scope_factory,
            llm_usage_repository_cls=self.llm_usage_repository_cls,
        ).summary()

    @staticmethod
    def _model_provider(model: str) -> str:
        normalized = str(model or "").strip().lower()
        if normalized.startswith(("gemini", "gemma")) or normalized.startswith("google/"):
            return "gemini"
        if normalized.startswith("anthropic/") or normalized.startswith("claude"):
            return "anthropic"
        if normalized.startswith("openai/") or normalized.startswith("gpt-"):
            return "openai"
        if normalized.startswith(("ollama/", "lm_studio/", "local/")):
            return "local"
        return "unknown"

    @staticmethod
    def _provider_enabled(provider: str, provider_keys: dict[str, bool]) -> bool:
        if provider == "litellm":
            return any(bool(value) for value in provider_keys.values())
        if provider == "google_genai":
            return bool(provider_keys.get("gemini"))
        if provider == "gemini_http":
            return bool(provider_keys.get("gemini"))
        return any(bool(value) for value in provider_keys.values())

    @classmethod
    def _fallback_models(cls, settings: Any) -> list[str]:
        models = [
            model.strip()
            for model in str(settings.llm_fallback_models or "").split(",")
            if model.strip()
        ]
        provider = str(getattr(settings, "llm_provider", "") or "").lower().replace("-", "_")
        local_model = str(getattr(settings, "local_llm_model", "") or "").strip()
        if provider == "litellm" and local_model:
            models.append(local_model)
        primary = str(getattr(settings, "primary_llm_model", "") or "").strip()
        return list(dict.fromkeys(model for model in models if model and model != primary))

    @staticmethod
    def _module_available(module_name: str | None) -> bool:
        if not module_name:
            return False
        try:
            return find_spec(module_name) is not None
        except (ImportError, ValueError):
            return False
