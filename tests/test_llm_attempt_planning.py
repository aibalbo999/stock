from __future__ import annotations

from app.services.llm_attempt_planning import iter_model_attempt_plans


def test_model_attempt_plans_skip_exhausted_and_cooldown_models_then_trim_keys() -> None:
    def attempt_record(**kwargs):
        return dict(kwargs)

    plans = list(
        iter_model_attempt_plans(
            ["gemini/gemini-3.5-flash", "gemini-2.5-flash", "gemma-4-31b-it"],
            provider="litellm",
            daily_exhausted_model_keys={"gemini-3.5-flash"},
            cooldown_remaining_func=lambda model: 12.3456 if model == "gemini-2.5-flash" else 0.0,
            key_candidates_func=lambda _model: [(0, "a"), (1, "b"), (2, "c")],
            attempt_record_func=attempt_record,
            use_model_fallback=True,
        )
    )

    assert plans[0].skipped is True
    assert plans[0].skipped_attempt == {
        "provider": "litellm",
        "model": "gemini/gemini-3.5-flash",
        "outcome": "quota_daily_exhausted",
        "retryable": True,
    }
    assert plans[1].skipped is True
    assert plans[1].skipped_attempt == {
        "provider": "litellm",
        "model": "gemini-2.5-flash",
        "outcome": "quota_cooldown",
        "retryable": True,
        "cooldown_seconds": 12.3456,
    }
    assert plans[2].model == "gemma-4-31b-it"
    assert plans[2].key_candidates == ((0, "a"), (1, "b"))


def test_model_attempt_plans_can_apply_an_absolute_key_candidate_limit() -> None:
    plans = list(
        iter_model_attempt_plans(
            ["gemini-vision"],
            provider="gemini_http",
            daily_exhausted_model_keys=set(),
            cooldown_remaining_func=lambda _model: 0.0,
            key_candidates_func=lambda _model: [(0, "a"), (1, "b"), (2, "c")],
            attempt_record_func=lambda **kwargs: dict(kwargs),
            use_model_fallback=False,
            max_key_candidates=2,
        )
    )

    assert plans[0].key_candidates == ((0, "a"), (1, "b"))
