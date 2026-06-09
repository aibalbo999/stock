from __future__ import annotations

import httpx

from app.services.llm_attempt_planning import iter_model_attempt_plans
from app.services.llm_quota import LLMQuotaGovernanceService, normalize_model_name
from app.services.llm_runtime import (
    DEFAULT_MODEL_QUOTA_COOLDOWN_SECONDS,
    daily_quota_exhausted_model_keys as _runtime_daily_quota_exhausted_model_keys,
    model_daily_quota_exhausted as _runtime_model_daily_quota_exhausted,
    model_quota_cooldown_remaining as _runtime_model_quota_cooldown_remaining,
    start_model_quota_cooldown as _runtime_start_model_quota_cooldown,
)


class LLMQuotaRoutingMixin:
    @property
    def model_quota_cooldown_seconds(self) -> float:
        return max(
            0.0,
            float(
                getattr(
                    self.settings,
                    "llm_model_quota_cooldown_seconds",
                    DEFAULT_MODEL_QUOTA_COOLDOWN_SECONDS,
                )
            ),
        )

    def _model_quota_cooldown_remaining(self, model: str) -> float:
        return max(
            _runtime_model_quota_cooldown_remaining(model),
            self._persisted_model_quota_cooldown_remaining(model),
        )

    def _persisted_model_quota_cooldown_remaining(self, model: str) -> float:
        if not bool(getattr(self.settings, "llm_quota_hard_routing_enabled", True)):
            return 0.0
        model_key = normalize_model_name(model)
        if not model_key:
            return 0.0
        summary = self._quota_summary()
        for item in summary.get("models", []) if isinstance(summary.get("models"), list) else []:
            if not isinstance(item, dict):
                continue
            item_key = normalize_model_name(str(item.get("model_key") or item.get("model") or ""))
            if item_key == model_key:
                return max(0.0, float(item.get("active_cooldown_seconds") or 0.0))
        return 0.0

    def _quota_summary(self) -> dict:
        quota_summary_cache = getattr(self, "_quota_summary_cache", None)
        if quota_summary_cache is not None:
            return quota_summary_cache
        try:
            self._quota_summary_cache = self._quota_governance_service_cls()(
                settings_provider=lambda: self.settings
            ).summary()
        except Exception:
            self._quota_summary_cache = {}
        return self._quota_summary_cache

    @staticmethod
    def _quota_governance_service_cls() -> type[LLMQuotaGovernanceService]:
        return LLMQuotaGovernanceService

    def _start_model_quota_cooldown(
        self,
        model: str,
        response: httpx.Response | None,
    ) -> None:
        cooldown_seconds = self._retry_delay_seconds(response, 0) if response is not None else 0.0
        if cooldown_seconds <= 0 or cooldown_seconds == self.base_retry_delay_seconds:
            cooldown_seconds = self.model_quota_cooldown_seconds
        if cooldown_seconds <= 0:
            return
        _runtime_start_model_quota_cooldown(model, cooldown_seconds)

    def _daily_quota_exhausted_model_keys(self) -> set[str]:
        return _runtime_daily_quota_exhausted_model_keys(self.settings)

    @staticmethod
    def _model_daily_quota_exhausted(model: str, exhausted_model_keys: set[str]) -> bool:
        return _runtime_model_daily_quota_exhausted(model, exhausted_model_keys)

    def _iter_model_attempt_plans(
        self,
        models: list[str],
        *,
        provider: str,
        use_model_fallback: bool,
        key_candidates_func,
        max_key_candidates: int | None = None,
    ):
        return iter_model_attempt_plans(
            models,
            provider=provider,
            daily_exhausted_model_keys=self._daily_quota_exhausted_model_keys(),
            cooldown_remaining_func=self._model_quota_cooldown_remaining,
            key_candidates_func=key_candidates_func,
            attempt_record_func=self._attempt_record,
            use_model_fallback=use_model_fallback,
            max_key_candidates=max_key_candidates,
        )
