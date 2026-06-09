from __future__ import annotations


def quality_gate_action_policy(
    *,
    blockers: list[str],
    warnings: list[str],
    investor_capital: int | None,
    cash_reserve_pct: float | None,
) -> tuple[str, dict]:
    if blockers:
        status = "insufficient"
        policy = "research_only"
        max_deployable_multiplier = 0.0
        label = "僅供研究，不允許投入資金"
    elif warnings:
        status = "caution"
        policy = "manual_review_required"
        max_deployable_multiplier = 0.25
        label = "需人工覆核，最多只可動用可投入資金的 25%"
    else:
        status = "ready"
        policy = "actionable"
        max_deployable_multiplier = 1.0
        label = "品質門檻通過，可進入個股研究；是否投入仍以後續投資建議與風險控管為準"
    deployable_amount = None
    if investor_capital is not None and cash_reserve_pct is not None:
        deployable_base = max(0, int(investor_capital * (1 - cash_reserve_pct)))
        deployable_amount = int(deployable_base * max_deployable_multiplier)
    return status, {
        "policy": policy,
        "label": label,
        "max_deployable_multiplier": max_deployable_multiplier,
        "max_deployable_amount": deployable_amount,
    }


__all__ = ["quality_gate_action_policy"]
