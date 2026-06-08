from __future__ import annotations

from collections.abc import Callable

from app.models.schemas import ReportRequest
from app.services import report_allocation


def source_label(context: dict) -> str:
    snapshot = context.get("snapshot")
    revenue = context.get("revenue")
    source = (
        f"{snapshot.trade_date.isoformat()} {snapshot.source}"
        if snapshot
        else "目前無足夠數據判斷"
    )
    if revenue:
        source += f"；{revenue.revenue_date.isoformat()} {revenue.source}"
    return source


def render_beginner_portfolio_plan(
    contexts: list[dict],
    request: ReportRequest,
    decision_reason_resolver: Callable,
) -> str:
    if not contexts:
        return "目前無足夠數據判斷。"

    capital = request.investor_capital
    reserve = int(capital * request.cash_reserve_pct)
    deployable = capital - reserve
    max_position = report_allocation.max_position_amount(request)
    first_tranche_ratio = report_allocation.first_tranche_ratio(request)
    first_tranche = int(max_position * first_tranche_ratio)
    downside_gate = report_allocation.downside_gate(request)

    candidate_contexts = []
    allocation_candidates = []
    avoid_rows = []
    watch_rows = []
    for context in contexts:
        label = context["label"]
        related_documents = context.get("documents") or []
        related_findings = context.get("findings") or []
        signal = context.get("leading_signal")
        estimate = context["estimate"]
        decision = context["decision"]
        source = source_label(context)
        reason = decision_reason_resolver(
            decision,
            estimate,
            context["quality"],
            related_findings,
            related_documents,
            downside_gate,
            request,
            signal,
        )

        if decision == "可小額分批研究":
            allocation_candidates.append(
                {
                    "label": label,
                    "upside_pct": estimate["upside_pct"],
                    "downside_pct": estimate["downside_pct"],
                    "source": source,
                }
            )
            candidate_contexts.append(
                {
                    "label": label,
                    "estimate": estimate,
                    "reason": reason,
                    "source": source,
                }
            )
        elif decision == "避開 / 降低曝險":
            avoid_rows.append(
                f"- {label}：避開或降低曝險。原因：目前情境降值分 {estimate['downside_pct']} 分，"
                f"目前情境升值分 {estimate['upside_pct']} 分；{reason}來源：{source}。"
            )
        else:
            watch_rows.append(
                f"- {label}：{decision}。原因：{reason}來源：{source}。"
            )

    allocation_amounts = report_allocation.allocation_amounts(
        allocation_candidates,
        deployable,
        first_tranche,
    )
    allocation_amount_by_label = {
        candidate["label"]: amount
        for candidate, amount in zip(allocation_candidates, allocation_amounts)
    }
    candidate_rows = []
    for context in candidate_contexts:
        estimate = context["estimate"]
        allocation_amount = allocation_amount_by_label.get(context["label"], first_tranche)
        candidate_rows.append(
            f"- {context['label']}：可列小額分批研究。首筆約 {allocation_amount:,} 元（配置草案），"
            f"單檔上限約 {max_position:,} 元；目前情境升值分 {estimate['upside_pct']} 分，"
            f"目前情境降值分 {estimate['downside_pct']} 分。原因：{context['reason']}"
            f"來源：{context['source']}。"
        )

    lines = [
        f"資金設定：總資金 {capital:,} 元以內；建議保留現金約 {reserve:,} 元，"
        f"本輪可投入資金上限約 {deployable:,} 元。",
        f"投資人設定：{report_allocation.profile_label(request)}；單檔部位上限 {request.max_position_pct:.0%}，"
        f"首筆試單約單檔上限的 {first_tranche_ratio:.0%}，"
        f"目前情境降值觀察門檻 {downside_gate} 分。",
        "原則：先控風險再追報酬；同一題材不宜一次滿倉，且資料不足時不進入可研究名單。",
    ]
    lines.extend(["", "### 首筆配置草案"])
    lines.extend(
        report_allocation.render_allocation_plan(
            allocation_candidates,
            deployable,
            first_tranche,
        )
    )
    lines.extend(["", "### 可小額分批研究"])
    lines.extend(candidate_rows or ["目前沒有同時通過資料完整度、風險門檻與投資理由一致性檢查的標的。"])
    lines.extend(["", "### 避開 / 降低曝險"])
    lines.extend(avoid_rows or ["目前無明確高風險名單。"])
    lines.extend(["", "### 觀察名單"])
    lines.extend(watch_rows or ["目前無觀察名單。"])
    return "\n".join(lines)
