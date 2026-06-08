from __future__ import annotations

from app.models.schemas import InvestorProfile, ReportRequest
from app.services.report_models import AllocationItem, AllocationPlan


def render_allocation_plan(
    candidates: list[dict],
    deployable: int,
    first_tranche: int,
) -> list[str]:
    if not candidates:
        return ["目前無可配置標的。"]
    amounts = allocation_amounts(candidates, deployable, first_tranche)
    plan = AllocationPlan(
        items=[
            AllocationItem(
                label=candidate["label"],
                amount=amount,
                upside_pct=int(candidate["upside_pct"]),
                downside_pct=int(candidate["downside_pct"]),
                source=str(candidate.get("source") or ""),
            )
            for candidate, amount in zip(candidates, amounts)
        ],
        declared_total=sum(amounts),
        deployable=deployable,
        first_tranche=first_tranche,
    )

    rows = [
        f"本輪首筆配置合計約 {plan.declared_total:,} 元；可投入上限 {plan.deployable:,} 元。"
        "配置採淨分（升值分 - 降值分）排序與權重，再套用單檔首筆上限與萬元取整。"
    ]
    for item in plan.items:
        cap_note = "；本檔已達首筆上限，並非完整等比例配置" if item.amount >= plan.first_tranche else ""
        rows.append(
            f"- {item.label}：首筆配置約 {item.amount:,} 元；"
            f"淨分 {item.net_score}，"
            f"升值分 {item.upside_pct} / 降值分 {item.downside_pct}{cap_note}。"
        )
    return rows


def allocation_amounts(
    candidates: list[dict],
    deployable: int,
    first_tranche: int,
) -> list[int]:
    if not candidates:
        return []
    weights = []
    for candidate in candidates:
        score = max(1, candidate["upside_pct"] - candidate["downside_pct"])
        weights.append(score)
    total_weight = sum(weights)
    budget = min(deployable, first_tranche * len(candidates))
    amounts = []
    remaining_budget = budget
    remaining_weight = total_weight
    for index, weight in enumerate(weights):
        if index == len(weights) - 1:
            amount = min(first_tranche, remaining_budget)
        else:
            raw_amount = int(remaining_budget * weight / remaining_weight)
            amount = min(first_tranche, max(0, raw_amount))
            amount = round_lot_amount(amount)
            if amount > remaining_budget:
                amount = round_down_lot_amount(remaining_budget)
        amounts.append(amount)
        remaining_budget -= amount
        remaining_weight -= weight
    return amounts


def round_lot_amount(amount: int) -> int:
    if amount <= 0:
        return 0
    return max(10_000, round(amount / 10_000) * 10_000)


def round_down_lot_amount(amount: int) -> int:
    if amount <= 0:
        return 0
    return max(10_000, (amount // 10_000) * 10_000)


def max_position_amount(request: ReportRequest) -> int:
    capital = request.investor_capital
    deployable = capital * (1 - request.cash_reserve_pct)
    return int(min(capital * request.max_position_pct, deployable * 0.25))


def profile(request: ReportRequest) -> InvestorProfile:
    if request.investor_profile != InvestorProfile.beginner:
        return request.investor_profile
    if not request.beginner_mode and request.investor_profile == InvestorProfile.beginner:
        return InvestorProfile.balanced
    return InvestorProfile.beginner


def profile_label(request: ReportRequest) -> str:
    labels = {
        InvestorProfile.beginner: "新手保守",
        InvestorProfile.balanced: "一般穩健",
        InvestorProfile.aggressive: "積極成長",
    }
    return labels[profile(request)]


def downside_gate(request: ReportRequest) -> int:
    gates = {
        InvestorProfile.beginner: 5,
        InvestorProfile.balanced: 8,
        InvestorProfile.aggressive: 12,
    }
    return gates[profile(request)]


def first_tranche_ratio(request: ReportRequest) -> float:
    ratios = {
        InvestorProfile.beginner: 0.30,
        InvestorProfile.balanced: 0.40,
        InvestorProfile.aggressive: 0.50,
    }
    return ratios[profile(request)]
