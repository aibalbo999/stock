from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.models.schemas import RiskType
from app.services.leading_signals import LeadingSignal


@dataclass(frozen=True)
class PotentialDecisionContext:
    estimate: dict
    quality: dict
    related_findings: object
    downside_gate: int
    leading_signal: LeadingSignal | None


def decision_label_for(
    estimate: dict,
    quality: dict,
    related_findings,
    downside_gate: int,
    leading_signal: LeadingSignal | None = None,
) -> str:
    context = PotentialDecisionContext(
        estimate=estimate,
        quality=quality,
        related_findings=related_findings,
        downside_gate=downside_gate,
        leading_signal=leading_signal,
    )
    for rule in _decision_rules():
        label = rule(context)
        if label:
            return label
    return "觀察"


def _decision_rules() -> tuple[Callable[[PotentialDecisionContext], str | None], ...]:
    return (
        _missing_market_decision,
        _avoid_decision,
        _risk_gate_decision,
        _finding_risk_decision,
        _upside_decision,
        _weak_quality_decision,
    )


def _missing_market_decision(context: PotentialDecisionContext) -> str | None:
    if "缺股價" in context.quality["missing"]:
        return "資料不足"
    return None


def _avoid_decision(context: PotentialDecisionContext) -> str | None:
    if _downside_exceeds_upside(context.estimate):
        return "避開 / 降低曝險"
    if _financial_red_flag_exceeds_gate(context.estimate):
        return "避開 / 降低曝險"
    return None


def _risk_gate_decision(context: PotentialDecisionContext) -> str | None:
    if context.estimate["downside_pct"] > context.downside_gate:
        return "觀察 / 等風險降低"
    if context.leading_signal and context.leading_signal.direction == "偏空":
        return "觀察 / 等風險降低"
    if (context.estimate.get("financial_assessment") or {}).get("red_flag"):
        return "觀察 / 等風險降低"
    return None


def _finding_risk_decision(context: PotentialDecisionContext) -> str | None:
    if _has_risk_type(context.related_findings, RiskType.insufficient_data):
        return "觀察 / 資料待補"
    if _has_risk_type(context.related_findings, RiskType.structural_bottleneck):
        return "觀察 / 等風險降低"
    if _has_risk_type(context.related_findings, RiskType.short_term_volatility):
        return "觀察"
    return None


def _upside_decision(context: PotentialDecisionContext) -> str | None:
    if context.estimate["upside_pct"] <= 10:
        return None
    if context.quality["grade"] != "supported":
        return "觀察 / 資料待補"
    return "可小額分批研究"


def _weak_quality_decision(context: PotentialDecisionContext) -> str | None:
    if context.quality["grade"] == "weak":
        return "觀察 / 資料不足"
    return None


def _downside_exceeds_upside(estimate: dict) -> bool:
    return estimate["downside_pct"] > estimate["upside_pct"]


def _financial_red_flag_exceeds_gate(estimate: dict) -> bool:
    financial = estimate.get("financial_assessment") or {}
    return bool(financial.get("red_flag") and int(financial.get("risk_score") or 0) >= 5)


def _has_risk_type(related_findings, risk_type: RiskType) -> bool:
    return any(finding.risk_type == risk_type for finding in related_findings)


__all__ = ["decision_label_for"]
