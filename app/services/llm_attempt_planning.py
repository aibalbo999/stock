from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

from app.services.llm_quota import normalize_model_name

KeyCandidate = tuple[int | None, str | None]
AttemptRecordFunc = Callable[..., dict[str, object]]


@dataclass(frozen=True)
class ModelAttemptPlan:
    model: str
    key_candidates: tuple[KeyCandidate, ...] = ()
    skipped_attempt: dict[str, object] | None = None

    @property
    def skipped(self) -> bool:
        return self.skipped_attempt is not None


def iter_model_attempt_plans(
    models: Sequence[str],
    *,
    provider: str,
    daily_exhausted_model_keys: set[str],
    cooldown_remaining_func: Callable[[str], float],
    key_candidates_func: Callable[[str], Sequence[KeyCandidate]],
    attempt_record_func: AttemptRecordFunc,
    use_model_fallback: bool,
    max_key_candidates: int | None = None,
    max_key_candidates_when_fallback: int | None = 2,
) -> Iterator[ModelAttemptPlan]:
    for model in models:
        if normalize_model_name(model) in daily_exhausted_model_keys:
            yield ModelAttemptPlan(
                model=model,
                skipped_attempt=attempt_record_func(
                    provider=provider,
                    model=model,
                    outcome="quota_daily_exhausted",
                    retryable=True,
                ),
            )
            continue
        if use_model_fallback:
            cooldown_remaining = cooldown_remaining_func(model)
            if cooldown_remaining > 0:
                yield ModelAttemptPlan(
                    model=model,
                    skipped_attempt=attempt_record_func(
                        provider=provider,
                        model=model,
                        outcome="quota_cooldown",
                        retryable=True,
                        cooldown_seconds=cooldown_remaining,
                    ),
                )
                continue
        key_candidates = tuple(key_candidates_func(model))
        limit = (
            max_key_candidates
            if max_key_candidates is not None
            else max_key_candidates_when_fallback
            if use_model_fallback
            else None
        )
        if limit is not None and limit >= 0:
            key_candidates = key_candidates[:limit]
        yield ModelAttemptPlan(model=model, key_candidates=key_candidates)
