from __future__ import annotations

from collections.abc import Callable

from app.models.schemas import NewsDocument, ReportRequest, RiskType
from app.services import report_allocation, report_decision_rules, report_potential
from app.services.leading_signals import LeadingSignal


def thesis_reason(context: dict, request: ReportRequest) -> str:
    estimate = context.get("estimate") or {}
    quality = context.get("quality") or {}
    decision = context.get("decision") or "觀察"
    downside_gate = report_allocation.downside_gate(request)
    if decision == "避開 / 降低曝險":
        positive = (
            f"雖然目前情境升值分有 {estimate.get('upside_pct', 0)} 分，"
            if estimate.get("upside_pct", 0) > 10
            else ""
        )
        return (
            f"{positive}但{report_decision_rules.risk_warning_reason(estimate)}"
            "因此本段不是買進理由，而是說明為何暫不投入或降低曝險。"
        )
    if decision == "觀察 / 等風險降低":
        return (
            f"目前情境升值分 {estimate.get('upside_pct', 0)} 分，"
            f"目前情境降值分 {estimate.get('downside_pct', 0)} 分，"
            f"高於或接近投資人設定門檻 {downside_gate} 分；"
            "即使有題材或近況動能，也需等風險證據、財務紅旗或近況訊號改善後再研究配置。"
        )
    if decision == "觀察 / 資料待補":
        missing = "、".join(quality.get("missing") or [])
        return (
            f"目前情境升值分 {estimate.get('upside_pct', 0)} 分，"
            f"但資料層仍待補足（{missing or '公司層級證據不足'}），暫不視為可配置理由。"
        )
    reasons = []
    if estimate.get("upside_pct", 0) > 10:
        reasons.append(f"目前情境升值分 {estimate['upside_pct']} 高於 10 分的研究門檻")
    if estimate.get("downside_pct", 0) <= downside_gate:
        reasons.append(f"目前情境降值分 {estimate['downside_pct']} 未超過投資人設定門檻")
    if quality.get("grade") == "supported":
        reasons.append("新聞/主題歸因、股價、營收、財務/估值與公司文件的資料層較完整")
    if decision == "可小額分批研究":
        reasons.append("可先放入小額研究清單，用資金上限控管，而不是一次性建立大部位")
    if not reasons:
        missing = "、".join(quality.get("missing") or [])
        return f"目前投資理由尚未完整，主要卡在 {missing or '目前情境升值分與降值分差距不夠明確'}。"
    return "；".join(reasons) + "。"


def thesis_verification_items(
    quality: dict,
    findings,
    related_documents: list[NewsDocument],
) -> str:
    items = []
    items.extend(quality.get("missing") or [])
    if any(finding.risk_type == RiskType.structural_bottleneck for finding in findings):
        items.append("結構性瓶頸是否緩解")
    if len(related_documents) < 3:
        items.append("公司層級來源是否能增加到至少 3 筆")
    if not items:
        items.append("下一期月營收、法說或官方文件是否延續目前假設")
    return "、".join(list(dict.fromkeys(items))[:5])


def render_investment_thesis_map(
    contexts: list[dict],
    request: ReportRequest,
    reading_sort_note: str,
    representative_sources_resolver: Callable[[list[NewsDocument]], str],
    downside_sources_resolver: Callable[[list[NewsDocument], object], str],
) -> str:
    if not contexts:
        return "目前沒有通過證據門檻的正式分析股票；先補候選公司證據，再建立投資理由。"

    lines = [
        "本段把每檔股票拆成「為什麼值得研究」與「為什麼可能不成立」。這是研究假設，不是報酬保證或買賣指令。",
        reading_sort_note,
    ]
    for context in contexts:
        estimate = context["estimate"]
        quality = context["quality"]
        documents_for_company = context["documents"]
        findings_for_company = context["findings"]
        signal: LeadingSignal | None = context.get("leading_signal")
        downside_sources = downside_sources_resolver(documents_for_company, findings_for_company)
        lines.extend(
            [
                "",
                f"### {context['label']}",
                f"- 目前判斷：{context['decision']}；資料等級：{report_potential.quality_label(quality['grade'])}。",
                f"- 成長假設：{estimate['upside_reason']}",
                f"- 主要風險：{estimate['downside_reason']}",
                f"- 具體投資理由：{thesis_reason(context, request)}",
                *(
                    [f"- 營收口徑提醒：{estimate['mom_revenue_caveat']}"]
                    if estimate.get("mom_revenue_caveat")
                    else []
                ),
                f"- 近況訊號：{signal.summary if signal and signal.has_signal_data else '目前缺股價歷史、月營收或估值序列，無法形成完整近況訊號。'}",
                f"- 需要再確認：{thesis_verification_items(quality, findings_for_company, documents_for_company)}",
                f"- 代表性來源：{representative_sources_resolver(documents_for_company)}",
            ]
        )
        if downside_sources:
            lines.append(f"- 風險來源：{downside_sources}")
    return "\n".join(lines)
